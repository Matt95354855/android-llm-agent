"""Persistance transactionnelle : missions, exécutions, actions, événements et APK (P01, P03)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from android_bridge.models import utcnow

from .models import Event, EventIn, MissionInfo, RunInfo


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


metadata = MetaData()

missions = Table(
    "missions",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("client_request_id", String(100), unique=True, nullable=True),
    Column("doc", JSON, nullable=False),
    Column("status", String(20), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

runs = Table(
    "runs",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("mission_id", String(40), nullable=False, index=True),
    Column("device_id", String(40), nullable=False, index=True),
    Column("doc", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

actions = Table(
    "actions",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("run_id", String(40), nullable=False, index=True),
    Column("device_id", String(40), nullable=False),
    Column("observation_seq", Integer),
    Column("lease_generation", Integer),
    Column("tool", String(40), nullable=False),
    Column("params", JSON, nullable=False),
    Column("summary", Text),
    Column("status", String(20), nullable=False),  # intended | done | failed | rejected | unknown
    Column("result", JSON),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
)

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("type", String(60), nullable=False),
    Column("summary", Text, nullable=False),
    Column("mission_id", String(40), index=True),
    Column("run_id", String(40)),
    Column("device_id", String(40), index=True),
    Column("data", JSON, nullable=False),
)

apks = Table(
    "apks",
    metadata,
    Column("id", String(64), primary_key=True),  # sha256
    Column("doc", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class Store:
    def __init__(self, url: str):
        self.engine: AsyncEngine = create_async_engine(url)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    # --- missions / exécutions --------------------------------------------------------------
    async def save_mission(self, m: MissionInfo, client_request_id: str | None = None) -> None:
        m.updated_at = utcnow()
        doc = m.model_dump(mode="json", exclude={"runs"})
        async with self.engine.begin() as conn:
            exists = (await conn.execute(select(missions.c.id).where(missions.c.id == m.id))).first()
            if exists:
                await conn.execute(
                    update(missions)
                    .where(missions.c.id == m.id)
                    .values(doc=doc, status=m.status, updated_at=m.updated_at)
                )
            else:
                await conn.execute(
                    insert(missions).values(
                        id=m.id,
                        client_request_id=client_request_id,
                        doc=doc,
                        status=m.status,
                        created_at=m.created_at,
                        updated_at=m.updated_at,
                    )
                )

    async def save_run(self, r: RunInfo) -> None:
        r.updated_at = utcnow()
        doc = r.model_dump(mode="json")
        async with self.engine.begin() as conn:
            exists = (await conn.execute(select(runs.c.id).where(runs.c.id == r.id))).first()
            if exists:
                await conn.execute(
                    update(runs)
                    .where(runs.c.id == r.id)
                    .values(doc=doc, status=r.status, updated_at=r.updated_at)
                )
            else:
                await conn.execute(
                    insert(runs).values(
                        id=r.id,
                        mission_id=r.mission_id,
                        device_id=r.device_id,
                        doc=doc,
                        status=r.status,
                        updated_at=r.updated_at,
                    )
                )

    async def mission_by_request(self, client_request_id: str) -> str | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(missions.c.id).where(missions.c.client_request_id == client_request_id)
                )
            ).first()
        return row[0] if row else None

    async def load_mission(self, mission_id: str) -> MissionInfo | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(missions.c.doc).where(missions.c.id == mission_id))).first()
            if not row:
                return None
            run_rows = (await conn.execute(select(runs.c.doc).where(runs.c.mission_id == mission_id))).all()
        m = MissionInfo.model_validate(row[0])
        m.runs = sorted((RunInfo.model_validate(r[0]) for r in run_rows), key=lambda r: r.created_at)
        return m

    async def list_missions(self, limit: int = 50, status: str | None = None) -> list[MissionInfo]:
        q = select(missions.c.id).order_by(missions.c.created_at.desc()).limit(limit)
        if status:
            q = q.where(missions.c.status == status)
        async with self.engine.connect() as conn:
            ids = [r[0] for r in (await conn.execute(q)).all()]
        out = []
        for mid in ids:
            if m := await self.load_mission(mid):
                out.append(m)
        return out

    async def active_runs(self) -> list[RunInfo]:
        active = ("queued", "running", "paused", "waiting_user", "recovering")
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(runs.c.doc).where(runs.c.status.in_(active)))).all()
        return [RunInfo.model_validate(r[0]) for r in rows]

    # --- actions : intention avant envoi, résultat après (P03/P04) --------------------------
    async def action_intent(self, **values: Any) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(actions).values(status="intended", created_at=utcnow(), **values))

    async def action_result(self, action_id: str, status: str, result: dict[str, Any]) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                update(actions)
                .where(actions.c.id == action_id)
                .values(status=status, result=result, finished_at=utcnow())
            )

    async def mark_intended_unknown(self) -> int:
        """Au redémarrage : une action restée « intended » a un effet inconnu (P04, RF13)."""
        async with self.engine.begin() as conn:
            res = await conn.execute(
                update(actions)
                .where(actions.c.status == "intended")
                .values(status="unknown", finished_at=utcnow())
            )
        return res.rowcount or 0

    # --- événements -------------------------------------------------------------------------
    async def add_event(self, e: EventIn) -> Event:
        ts = utcnow()
        async with self.engine.begin() as conn:
            res = await conn.execute(insert(events).values(ts=ts, **e.model_dump()))
            eid = res.inserted_primary_key[0]
        return Event(id=eid, ts=ts, **e.model_dump())

    async def events_after(
        self, after_id: int, limit: int = 500, mission_id: str | None = None, device_id: str | None = None
    ) -> list[Event]:
        q = select(events).where(events.c.id > after_id).order_by(events.c.id).limit(limit)
        if mission_id:
            q = q.where(events.c.mission_id == mission_id)
        if device_id:
            q = q.where(events.c.device_id == device_id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(q)).mappings().all()
        # SQLite perd le fuseau : les horodatages sont stockés en UTC.
        return [Event(**(dict(r) | {"ts": _utc(r["ts"])})) for r in rows]

    async def last_event_id(self) -> int:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(events.c.id).order_by(events.c.id.desc()).limit(1))).first()
        return row[0] if row else 0

    # --- APK --------------------------------------------------------------------------------
    async def save_apk(self, apk_id: str, doc: dict[str, Any]) -> None:
        async with self.engine.begin() as conn:
            exists = (await conn.execute(select(apks.c.id).where(apks.c.id == apk_id))).first()
            if exists:
                await conn.execute(update(apks).where(apks.c.id == apk_id).values(doc=doc))
            else:
                await conn.execute(insert(apks).values(id=apk_id, doc=doc, created_at=utcnow()))

    async def list_apks(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(apks.c.doc).order_by(apks.c.created_at.desc()))).all()
        return [r[0] for r in rows]

    async def get_apk(self, apk_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(apks.c.doc).where(apks.c.id == apk_id))).first()
        return row[0] if row else None
