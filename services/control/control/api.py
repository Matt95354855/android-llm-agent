"""API HTTP : appareils, contrôle manuel, missions, événements et APK."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, TypeAdapter

from android_bridge import exclusions
from android_bridge.actions import DeviceAction, InstallApk
from android_bridge.device import AdbDevice

from .apks import ApkInvalid, ApkLibrary
from .config import Settings
from .db import Store
from .events import EventBus
from .fleet import DeviceUnavailable, Fleet
from .locks import DeviceLocks, LeaseLost
from .models import (
    TERMINAL,
    ApiError,
    Controller,
    InvalidTransition,
    MissionCreate,
    MissionInfo,
    MissionMode,
    MissionStatus,
    RunInfo,
    check_transition,
    new_id,
)

log = logging.getLogger(__name__)
API_VERSION = "1"
_action_adapter = TypeAdapter(DeviceAction)


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False, **details):
        self.status, self.err = (
            status,
            ApiError(code=code, message=message, retryable=retryable, details=details),
        )


class Login(BaseModel):
    token: str


class ApkUrl(BaseModel):
    url: str


class ApkInstall(BaseModel):
    device_ids: list[str]


def _session_value(token: str) -> str:
    return hmac.new(token.encode(), b"pe-session-v1", hashlib.sha256).hexdigest()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.access_token and not settings.allow_no_auth:
        raise RuntimeError("PE_ACCESS_TOKEN est obligatoire (ou PE_ALLOW_NO_AUTH=1 en développement local)")
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    store = Store(settings.db_url)
    bus = EventBus(store)
    locks = DeviceLocks()
    fleet = Fleet(settings, bus, locks)
    library = ApkLibrary(settings.data_dir / "apks")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await store.init()
        unknown = await store.mark_intended_unknown()
        if unknown:
            await bus.emit(
                "system.recovery",
                f"{unknown} action(s) au résultat inconnu après redémarrage",
                data={"count": unknown},
            )
        for run in await store.active_runs():  # à réconcilier, jamais annoncées terminées (P11)
            run.status = MissionStatus.paused
            run.wait_reason = "reprise après redémarrage du service : vérifier l'état avant de relancer"
            await store.save_run(run)
        await bus.emit(
            "system.started",
            "Service de contrôle démarré",
            data={"backend": settings.device_backend, "devices": settings.device_ids},
        )
        await fleet.start_all()
        fleet.run_health_loop()
        yield
        await fleet.shutdown()
        await store.close()

    app = FastAPI(title="phone_emulator", version=API_VERSION, lifespan=lifespan)
    app.state.settings, app.state.store, app.state.fleet, app.state.locks = settings, store, fleet, locks

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(exc.err.model_dump(), status_code=exc.status)

    @app.exception_handler(DeviceUnavailable)
    async def _dev_unavailable(_: Request, exc: DeviceUnavailable):
        return JSONResponse(
            ApiError(code="device_unavailable", message=str(exc), retryable=True).model_dump(),
            status_code=409,
        )

    @app.exception_handler(KeyError)
    async def _not_found(_: Request, exc: KeyError):
        return JSONResponse(
            ApiError(code="not_found", message=str(exc.args[0])).model_dump(), status_code=404
        )

    # --- authentification (T01–T04) ---------------------------------------------------------
    public = {"/api/health", "/api/login"}

    @app.middleware("http")
    async def auth(request: Request, call_next):
        path = request.url.path
        if settings.access_token and path.startswith("/api") and path not in public:
            expected = _session_value(settings.access_token)
            cookie = request.cookies.get("pe_session", "")
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            ok = hmac.compare_digest(cookie, expected) or (
                bearer and hmac.compare_digest(bearer, settings.access_token)
            )
            if not ok:
                return JSONResponse(
                    ApiError(code="unauthorized", message="Connexion requise").model_dump(), status_code=401
                )
        return await call_next(request)

    @app.post("/api/login")
    async def login(body: Login, request: Request, response: Response):
        if not settings.access_token:
            return {"ok": True, "auth": "disabled"}
        if not hmac.compare_digest(body.token, settings.access_token):
            raise AppError(401, "bad_token", "Jeton d'accès incorrect")
        response.set_cookie(
            "pe_session",
            _session_value(settings.access_token),
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=7 * 86400,
        )
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie("pe_session")
        return {"ok": True}

    # --- santé ------------------------------------------------------------------------------
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "api_version": API_VERSION}

    @app.get("/api/ready")
    async def ready():
        devices = fleet.all()
        return {
            "backend": settings.device_backend,
            "demo": settings.device_backend == "demo",
            "devices_ready": sum(d.state in ("ready", "busy", "manual") for d in devices),
            "devices_total": len(devices),
            "agent_connected": False,  # boucle agent pas encore branchée
        }

    # --- appareils --------------------------------------------------------------------------
    @app.get("/api/devices")
    async def devices():
        return [d.model_dump(mode="json") for d in fleet.all()]

    @app.post("/api/devices/{device_id}/start")
    async def device_start(device_id: str):
        fleet.info(device_id)
        import asyncio

        asyncio.create_task(fleet.start(device_id))
        return {"ok": True}

    @app.post("/api/devices/{device_id}/stop")
    async def device_stop(device_id: str):
        if locks.holder(device_id):
            raise AppError(
                409, "device_locked", "Téléphone en cours d'utilisation : arrêtez d'abord la mission"
            )
        await fleet.stop(device_id)
        return {"ok": True}

    @app.get("/api/devices/{device_id}/screen")
    async def device_screen(device_id: str):
        png, taken = await fleet.screen(device_id)
        return Response(
            png,
            media_type="image/png",
            headers={"Cache-Control": "no-store", "X-Screen-Taken-At": f"{taken:.3f}"},
        )

    @app.get("/api/devices/{device_id}/observation")
    async def device_observation(device_id: str):
        obs = await fleet.observe(device_id)
        return obs.model_dump(mode="json")

    @app.post("/api/devices/{device_id}/egress")
    async def device_egress(device_id: str):
        return (await fleet.check_egress(device_id)).model_dump(mode="json")

    @app.get("/api/devices/{device_id}/compliance")
    async def device_compliance(device_id: str):
        backend = fleet.backend(device_id)
        if not isinstance(backend, AdbDevice):
            return {"compliant": None, "notes": ["appareil de démonstration : non applicable"]}
        report = await exclusions.check(backend.adb)
        fleet.info(device_id).compliant = report.compliant
        return report.model_dump()

    # --- contrôle manuel (O05–O07, K10) -----------------------------------------------------
    def _user_owner(request: Request) -> str:
        return "user:" + hashlib.sha256(request.cookies.get("pe_session", "local").encode()).hexdigest()[:12]

    @app.post("/api/devices/{device_id}/control")
    async def take_control(device_id: str, request: Request):
        fleet.backend(device_id)
        lease = locks.try_acquire(device_id, _user_owner(request), Controller.user)
        if lease is None:
            holder = locks.holder(device_id)
            raise AppError(
                409,
                "device_locked",
                f"Téléphone contrôlé par : {holder.kind.value if holder else '?'}",
                retryable=True,
            )
        fleet.mark_controller(device_id, Controller.user)
        await bus.emit(
            "device.control", "Contrôle manuel pris", device_id=device_id, data={"controller": "user"}
        )
        return {"ok": True, "generation": lease.generation}

    @app.delete("/api/devices/{device_id}/control")
    async def release_control(device_id: str, request: Request):
        lease = locks.holder(device_id)
        if lease and lease.owner == _user_owner(request):
            await locks.release(lease)
            fleet.mark_controller(device_id, Controller.none)
            await bus.emit(
                "device.control", "Contrôle manuel rendu", device_id=device_id, data={"controller": "none"}
            )
        return {"ok": True}

    @app.post("/api/devices/{device_id}/actions")
    async def manual_action(device_id: str, request: Request, action: dict = Body(...)):
        lease = locks.holder(device_id)
        if lease is None or lease.owner != _user_owner(request):
            raise AppError(409, "no_control", "Prenez d'abord le contrôle manuel de ce téléphone")
        try:
            parsed = _action_adapter.validate_python(action)
        except Exception as exc:
            raise AppError(422, "invalid_action", "Action invalide", errors=str(exc)) from exc
        if parsed.tool in ("install_apk", "push_file"):
            raise AppError(422, "invalid_action", "Utilisez la bibliothèque d'APK et de fichiers")
        try:
            outcome = await fleet.execute(lease, parsed)
        except LeaseLost as exc:
            raise AppError(409, "lease_lost", str(exc)) from exc
        locks.renew(lease)
        await bus.emit(
            "action.manual",
            f"Geste manuel : {parsed.tool}",
            device_id=device_id,
            data={"action": parsed.model_dump(), "status": outcome.status},
        )
        return outcome.model_dump(mode="json")

    # --- missions ---------------------------------------------------------------------------
    @app.post("/api/missions", status_code=202)
    async def create_mission(body: MissionCreate):
        if body.client_request_id and (existing := await store.mission_by_request(body.client_request_id)):
            return await store.load_mission(existing)
        unknown = [d for d in body.device_ids if d not in fleet.slots]
        if unknown:
            raise AppError(422, "unknown_device", f"Téléphone(s) inconnu(s) : {', '.join(unknown)}")
        per_device = {t.device_id: t.prompt for t in body.tasks}
        if body.mode == MissionMode.independent:
            missing = [d for d in body.device_ids if not (per_device.get(d) or body.prompt)]
            if missing:
                raise AppError(422, "missing_prompt", f"Prompt manquant pour : {', '.join(missing)}")
        elif not body.prompt:
            raise AppError(422, "missing_prompt", "Objectif commun requis en mode coordonné")
        title = body.title or (body.prompt or next(iter(per_device.values()), ""))[:80]
        mission = MissionInfo(
            id=new_id("mis"), title=title, mode=body.mode, prompt=body.prompt, device_ids=body.device_ids
        )
        await store.save_mission(mission, body.client_request_id)
        if body.mode == MissionMode.independent:
            for did in body.device_ids:
                run = RunInfo(
                    id=new_id("run"),
                    mission_id=mission.id,
                    device_id=did,
                    goal=per_device.get(did) or body.prompt or "",
                    wait_reason="agent pas encore branché",
                )
                await store.save_run(run)
        await bus.emit(
            "mission.created",
            f"Mission créée : {title}",
            mission_id=mission.id,
            data={"mode": body.mode, "devices": body.device_ids},
        )
        return await store.load_mission(mission.id)

    @app.get("/api/missions")
    async def list_missions(limit: int = 50, status: str | None = None):
        return [m.model_dump(mode="json") for m in await store.list_missions(min(limit, 200), status)]

    @app.get("/api/missions/{mission_id}")
    async def get_mission(mission_id: str):
        m = await store.load_mission(mission_id)
        if not m:
            raise AppError(404, "not_found", "Mission introuvable")
        return m.model_dump(mode="json")

    async def _transition(mission_id: str, target: MissionStatus, label: str):
        m = await store.load_mission(mission_id)
        if not m:
            raise AppError(404, "not_found", "Mission introuvable")
        try:
            check_transition(m.status, target)
        except InvalidTransition as exc:
            raise AppError(409, "invalid_transition", str(exc), current=m.status, target=target) from exc
        m.status = target
        await store.save_mission(m)
        for r in m.runs:
            if r.status not in TERMINAL:
                try:
                    check_transition(r.status, target)
                    r.status = target
                    await store.save_run(r)
                except InvalidTransition:
                    pass
        await bus.emit(
            f"mission.{target.value}", f"Mission {label}", mission_id=mission_id, data={"status": target}
        )
        return (await store.load_mission(mission_id)).model_dump(mode="json")

    @app.post("/api/missions/{mission_id}/pause")
    async def pause(mission_id: str):
        return await _transition(mission_id, MissionStatus.paused, "mise en pause")

    @app.post("/api/missions/{mission_id}/resume")
    async def resume(mission_id: str):
        return await _transition(mission_id, MissionStatus.queued, "reprise (en file)")

    @app.post("/api/missions/{mission_id}/cancel")
    async def cancel(mission_id: str):
        return await _transition(mission_id, MissionStatus.cancelled, "annulée")

    # --- événements (SSE, reprise par Last-Event-ID) ----------------------------------------
    @app.get("/api/events")
    async def events(request: Request, after: int | None = None):
        last = after if after is not None else int(request.headers.get("last-event-id") or 0)

        async def gen():
            yield "retry: 3000\n\n"
            async for e in bus.stream(last):
                if await request.is_disconnected():
                    break
                yield f"id: {e.id}\nevent: {e.type}\ndata: {json.dumps(e.model_dump(mode='json'))}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/events/history")
    async def events_history(after: int = 0, mission_id: str | None = None, device_id: str | None = None):
        return [
            e.model_dump(mode="json") for e in await store.events_after(after, 500, mission_id, device_id)
        ]

    # --- APK --------------------------------------------------------------------------------
    @app.get("/api/apks")
    async def list_apks():
        return await store.list_apks()

    @app.post("/api/apks/upload", status_code=201)
    async def upload_apk(file: UploadFile = File(...)):
        try:
            doc = library.import_file(file.file, file.filename or "app.apk")
        except ApkInvalid as exc:
            raise AppError(422, "apk_invalid", str(exc)) from exc
        await store.save_apk(doc["id"], doc)
        await bus.emit("apk.added", f"APK importé : {doc['filename']}", data=doc)
        return doc

    @app.post("/api/apks/download", status_code=201)
    async def download_apk(body: ApkUrl):
        try:
            doc = await library.download(body.url)
        except ApkInvalid as exc:
            raise AppError(422, "apk_invalid", str(exc)) from exc
        await store.save_apk(doc["id"], doc)
        await bus.emit("apk.added", f"APK téléchargé : {doc['filename']}", data=doc)
        return doc

    @app.post("/api/apks/{apk_id}/install")
    async def install_apk(apk_id: str, body: ApkInstall):
        doc = await store.get_apk(apk_id)
        if not doc:
            raise AppError(404, "not_found", "APK introuvable")
        path = library.path(apk_id)
        results = {}
        for did in body.device_ids:
            lease = locks.try_acquire(did, f"system:install:{apk_id[:8]}", Controller.system)
            if lease is None:
                results[did] = {"status": "rejected", "message": "téléphone occupé"}
                continue
            try:
                backend = fleet.backend(did)
                before = (
                    set(await exclusions.third_party_packages(backend.adb))
                    if isinstance(backend, AdbDevice)
                    else set()
                )
                outcome = await fleet.execute(lease, InstallApk(path=str(path)))
                if outcome.status == "done" and isinstance(backend, AdbDevice):
                    for pkg in set(await exclusions.third_party_packages(backend.adb)) - before:
                        await exclusions.lock_package(backend.adb, pkg)  # S12, J10
                results[did] = outcome.model_dump(mode="json")
            except DeviceUnavailable as exc:
                results[did] = {"status": "rejected", "message": str(exc)}
            finally:
                await locks.release(lease)
            await bus.emit(
                "apk.install",
                f"Installation {doc['filename']} : {results[did]['status']}",
                device_id=did,
                data={"apk_id": apk_id, "result": results[did]},
            )
        return results

    # --- interface web ----------------------------------------------------------------------
    dist = Path(settings.web_dist)
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(dist / "index.html")

    return app
