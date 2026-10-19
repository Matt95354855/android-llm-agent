"""Contrats versionnés : missions, exécutions, appareils et événements (E05–E07)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from android_bridge.models import utcnow

SCHEMA_VERSION = 1


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class MissionStatus(StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"
    waiting_user = "waiting_user"
    recovering = "recovering"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL = {MissionStatus.succeeded, MissionStatus.failed, MissionStatus.cancelled}

TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
    MissionStatus.queued: {
        MissionStatus.running,
        MissionStatus.paused,
        MissionStatus.cancelled,
        MissionStatus.failed,
    },
    MissionStatus.running: {
        MissionStatus.paused,
        MissionStatus.waiting_user,
        MissionStatus.recovering,
        MissionStatus.succeeded,
        MissionStatus.failed,
        MissionStatus.cancelled,
    },
    MissionStatus.paused: {MissionStatus.running, MissionStatus.queued, MissionStatus.cancelled},
    MissionStatus.waiting_user: {MissionStatus.running, MissionStatus.paused, MissionStatus.cancelled},
    MissionStatus.recovering: {
        MissionStatus.running,
        MissionStatus.paused,
        MissionStatus.failed,
        MissionStatus.cancelled,
    },
    MissionStatus.succeeded: set(),
    MissionStatus.failed: set(),
    MissionStatus.cancelled: set(),
}


class InvalidTransition(ValueError):
    def __init__(self, current: MissionStatus, target: MissionStatus):
        super().__init__(f"transition interdite : {current} → {target}")
        self.current, self.target = current, target


def check_transition(current: MissionStatus, target: MissionStatus) -> None:
    if target != current and target not in TRANSITIONS[current]:
        raise InvalidTransition(current, target)


class MissionMode(StrEnum):
    independent = "independent"
    coordinated = "coordinated"


class Outcome(StrEnum):
    complete = "complete"
    partial = "partial"
    unverified = "unverified"  # l'agent annonce une réussite sans critère vérifié (M17)
    none = "none"


class DeviceState(StrEnum):
    created = "created"
    booting = "booting"
    ready = "ready"
    busy = "busy"
    manual = "manual"
    offline = "offline"
    error = "error"
    stopped = "stopped"


class SuccessCriteria(BaseModel):
    """Vérification déterministe optionnelle, évaluée sur une observation fraîche (RF05)."""

    text_visible: list[str] = []
    foreground_package: str | None = None


class DeviceTask(BaseModel):
    device_id: str
    prompt: str = Field(min_length=1, max_length=20_000)
    criteria: SuccessCriteria | None = None


class MissionCreate(BaseModel):
    title: str | None = Field(None, max_length=200)
    mode: MissionMode = MissionMode.independent
    prompt: str | None = Field(None, max_length=20_000)  # objectif commun, ou prompt identique à tous
    device_ids: list[str] = Field(min_length=1)
    tasks: list[DeviceTask] = []  # prompts distincts par téléphone en mode indépendant (R05)
    criteria: SuccessCriteria | None = None
    client_request_id: str | None = Field(None, max_length=100)  # déduplication (P06)


class RunInfo(BaseModel):
    id: str
    mission_id: str
    device_id: str
    goal: str
    depends_on: list[str] = []
    status: MissionStatus = MissionStatus.queued
    outcome: Outcome = Outcome.none
    summary: str | None = None
    evidence: list[str] = []
    steps: int = 0
    wait_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MissionInfo(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    title: str
    mode: MissionMode
    prompt: str | None
    device_ids: list[str]
    status: MissionStatus = MissionStatus.queued
    outcome: Outcome = Outcome.none
    summary: str | None = None
    plan: dict[str, Any] | None = None
    runs: list[RunInfo] = []
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Controller(StrEnum):
    none = "none"
    agent = "agent"
    user = "user"
    replay = "replay"
    system = "system"


class DeviceInfo(BaseModel):
    id: str
    name: str
    backend: Literal["emulator", "demo"]
    state: DeviceState
    serial: str | None = None
    controller: Controller = Controller.none
    run_id: str | None = None
    mission_id: str | None = None
    egress_ip: str | None = None
    egress_checked_at: datetime | None = None
    compliant: bool | None = None
    last_seen_at: datetime | None = None
    error: str | None = None


class EventIn(BaseModel):
    type: str
    summary: str
    mission_id: str | None = None
    run_id: str | None = None
    device_id: str | None = None
    data: dict[str, Any] = {}


class Event(EventIn):
    id: int
    ts: datetime


class ApiError(BaseModel):
    """Enveloppe d'erreur commune (E10)."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = {}
