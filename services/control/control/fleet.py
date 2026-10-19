"""Flotte de téléphones : identité stable, état, santé et exécution exclusive (G01–G15, M08)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from android_bridge import exclusions, network
from android_bridge.actions import DeviceAction
from android_bridge.demo import DemoDevice
from android_bridge.device import AdbDevice, DeviceBackend
from android_bridge.emulator import EmulatorManager, EmulatorProfile
from android_bridge.models import ActionOutcome, Observation, utcnow

from .config import Settings
from .events import EventBus
from .locks import DeviceLocks, Lease
from .models import Controller, DeviceInfo, DeviceState

log = logging.getLogger(__name__)


class DeviceUnavailable(RuntimeError):
    pass


class _Slot:
    def __init__(self, info: DeviceInfo):
        self.info = info
        self.backend: DeviceBackend | None = None
        self.io_lock = asyncio.Lock()  # une seule mutation à la fois par téléphone
        self.last_screen: tuple[bytes, float] | None = None
        self.screen_lock = asyncio.Lock()
        self.failures = 0


class Fleet:
    def __init__(self, settings: Settings, bus: EventBus, locks: DeviceLocks):
        self.settings = settings
        self.bus = bus
        self.locks = locks
        self.slots: dict[str, _Slot] = {}
        self.emulators: EmulatorManager | None = None
        for i, did in enumerate(settings.device_ids):
            info = DeviceInfo(
                id=did, name=f"Téléphone {i + 1}", backend=settings.device_backend, state=DeviceState.stopped
            )
            self.slots[did] = _Slot(info)
        if settings.device_backend == "emulator":
            self.emulators = EmulatorManager(
                Path(settings.android_sdk_root),
                Path(settings.data_dir),
                EmulatorProfile(
                    system_image=settings.android_system_image,
                    gpu=settings.emulator_gpu,
                    accel=settings.emulator_accel,
                ),
                settings.device_ids,
            )
            for did, inst in self.emulators.instances.items():
                self.slots[did].info.serial = inst.serial
        self._health_task: asyncio.Task | None = None

    # --- accès ------------------------------------------------------------------------------
    def info(self, device_id: str) -> DeviceInfo:
        return self._slot(device_id).info

    def all(self) -> list[DeviceInfo]:
        for slot in self.slots.values():
            lease = self.locks.holder(slot.info.id)
            slot.info.controller = lease.kind if lease else Controller.none
        return [s.info for s in self.slots.values()]

    def _slot(self, device_id: str) -> _Slot:
        if device_id not in self.slots:
            raise KeyError(f"téléphone inconnu : {device_id}")
        return self.slots[device_id]

    def backend(self, device_id: str) -> DeviceBackend:
        slot = self._slot(device_id)
        if slot.backend is None or slot.info.state in (
            DeviceState.stopped,
            DeviceState.offline,
            DeviceState.error,
            DeviceState.booting,
        ):
            raise DeviceUnavailable(f"{slot.info.name} n'est pas prêt ({slot.info.state})")
        return slot.backend

    async def _set_state(self, device_id: str, state: DeviceState, error: str | None = None) -> None:
        info = self._slot(device_id).info
        if info.state == state and info.error == error:
            return
        info.state, info.error = state, error
        await self.bus.emit(
            "device.state",
            f"{info.name} : {state.value}",
            device_id=device_id,
            data={"state": state.value, "error": error},
        )

    # --- cycle de vie -----------------------------------------------------------------------
    async def start(self, device_id: str) -> None:
        slot = self._slot(device_id)
        if slot.info.state in (DeviceState.ready, DeviceState.busy, DeviceState.manual, DeviceState.booting):
            return
        await self._set_state(device_id, DeviceState.booting)
        try:
            if self.emulators:
                slot.backend = await self.emulators.start(device_id)
                if isinstance(slot.backend, AdbDevice):
                    report = await exclusions.check(slot.backend.adb)
                    slot.info.compliant = report.compliant
            else:
                index = list(self.slots).index(device_id)
                slot.backend = DemoDevice(device_id, index)
                slot.info.compliant = None
            slot.info.last_seen_at = utcnow()
            await self._set_state(device_id, DeviceState.ready)
        except Exception as exc:  # l'identité et l'historique de l'appareil sont conservés (G06)
            log.exception("démarrage de %s", device_id)
            await self._set_state(device_id, DeviceState.error, str(exc)[:500])

    async def start_all(self) -> None:
        for i, did in enumerate(self.slots):
            if i and self.emulators:
                await asyncio.sleep(self.settings.emulator_stagger_s)
            asyncio.create_task(self.start(did))

    async def stop(self, device_id: str) -> None:
        slot = self._slot(device_id)
        if self.emulators:
            await self.emulators.stop(device_id)
        slot.backend = None
        await self._set_state(device_id, DeviceState.stopped)

    @property
    def _health_timeout(self) -> float:
        return 90.0 if self.settings.emulator_accel == "off" else 20.0

    def run_health_loop(self, interval_s: float = 15.0) -> None:
        async def loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                for did, slot in self.slots.items():
                    if slot.backend is None or slot.info.state in (DeviceState.booting, DeviceState.stopped):
                        continue
                    try:
                        ok = await asyncio.wait_for(slot.backend.is_ready(), self._health_timeout)
                    except Exception:
                        ok = False
                    if ok:
                        slot.failures = 0
                        slot.info.last_seen_at = utcnow()
                        if slot.info.state in (DeviceState.offline, DeviceState.error):
                            await self._set_state(did, DeviceState.ready)
                        continue
                    slot.failures += 1
                    # Hors ligne seulement après plusieurs échecs : sous charge, une réponse lente n'est pas une panne.
                    if slot.failures >= 3 and slot.info.state not in (DeviceState.offline, DeviceState.error):
                        await self._set_state(did, DeviceState.offline)

        self._health_task = asyncio.create_task(loop())

    async def shutdown(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        # Les émulateurs survivent volontairement à l'arrêt du service : un redémarrage du contrôle
        # ne doit pas coûter plusieurs minutes de démarrage Android. Les éteindre = action explicite.
        if self.emulators and self.settings.stop_emulators_on_exit:
            for did in self.slots:
                if self.emulators.is_running(did):
                    await self.emulators.stop(did)

    # --- observation et action --------------------------------------------------------------
    async def observe(self, device_id: str, include_tree: bool = True) -> Observation:
        backend = self.backend(device_id)
        obs = await backend.observe(include_tree=include_tree)
        slot = self._slot(device_id)
        slot.info.last_seen_at = utcnow()
        if obs.screenshot_png:
            slot.last_screen = (obs.screenshot_png, obs.taken_at.timestamp())
        return obs

    async def screen(self, device_id: str, max_age_s: float = 0.7) -> tuple[bytes, float]:
        """Dernière capture pour le mur d'écrans (mode dégradé K06, en attendant le flux vidéo)."""
        slot = self._slot(device_id)
        async with slot.screen_lock:
            now = utcnow().timestamp()
            if slot.last_screen and now - slot.last_screen[1] <= max_age_s:
                return slot.last_screen
            png = await self.backend(device_id).screenshot()
            slot.last_screen = (png, utcnow().timestamp())
            return slot.last_screen

    async def execute(self, lease: Lease, action: DeviceAction) -> ActionOutcome:
        slot = self._slot(lease.device_id)
        async with slot.io_lock:
            self.locks.validate(lease)  # dernier contrôle avant injection (N05, O13)
            return await self.backend(lease.device_id).execute(action)

    async def check_egress(self, device_id: str) -> DeviceInfo:
        """Mesure l'IP de sortie depuis l'Android et la conserve avec sa date (C14)."""
        backend = self.backend(device_id)
        info = self._slot(device_id).info
        if isinstance(backend, AdbDevice):
            ip, method = await network.egress_ip(backend.adb)
        else:
            ip, method = None, "appareil de démonstration : pas de réseau réel"
        info.egress_ip, info.egress_checked_at = ip, utcnow()
        await self.bus.emit(
            "device.egress",
            f"{info.name} : IP de sortie {ip or 'non mesurée'}",
            device_id=device_id,
            data={"ip": ip, "method": method},
        )
        return info

    def mark_controller(
        self, device_id: str, kind: Controller, run_id: str | None = None, mission_id: str | None = None
    ) -> None:
        info = self._slot(device_id).info
        info.controller, info.run_id, info.mission_id = kind, run_id, mission_id
        if info.state in (DeviceState.ready, DeviceState.busy, DeviceState.manual):
            info.state = {Controller.agent: DeviceState.busy, Controller.user: DeviceState.manual}.get(
                kind, DeviceState.ready
            )
