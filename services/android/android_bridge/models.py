"""Objets échangés avec un appareil : observation, nœud UI et résultat brut d'action."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Bounds(BaseModel):
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def empty(self) -> bool:
        return self.right <= self.left or self.bottom <= self.top


class UiNode(BaseModel):
    """Élément d'accessibilité utile, identifié par un index stable dans une observation."""

    index: int
    text: str = ""
    desc: str = ""
    resource_id: str = ""
    cls: str = ""
    package: str = ""
    bounds: Bounds
    clickable: bool = False
    long_clickable: bool = False
    scrollable: bool = False
    editable: bool = False
    enabled: bool = True
    checked: bool | None = None
    selected: bool = False
    focused: bool = False
    password: bool = False


class Observation(BaseModel):
    device_id: str
    seq: int
    taken_at: datetime = Field(default_factory=utcnow)
    width: int
    height: int
    rotation: int = 0
    foreground_package: str | None = None
    foreground_activity: str | None = None
    keyboard_visible: bool = False
    screenshot_png: bytes | None = Field(default=None, exclude=True, repr=False)
    screenshot_sha256: str | None = None
    ui_nodes: list[UiNode] = []
    ui_tree_status: str = "ok"  # ok | empty | unavailable
    ui_tree_skew_ms: int | None = None  # écart entre capture et arbre (H04)

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or utcnow()) - self.taken_at).total_seconds()

    def node(self, index: int) -> UiNode | None:
        return next((n for n in self.ui_nodes if n.index == index), None)


class OutcomeStatus(StrEnum):
    done = "done"  # commande exécutée et accusée par l'appareil
    rejected = "rejected"  # refusée avant injection : rien n'a été envoyé
    failed = "failed"  # exécutée mais en erreur
    unknown = "unknown"  # interrompue : l'effet doit être vérifié avant répétition (I20)


class ActionOutcome(BaseModel):
    status: OutcomeStatus
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    data: dict = {}
