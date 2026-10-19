"""Catalogue d'actions Android typées (I01–I16). Coordonnées en pixels de l'écran Android."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class _Action(BaseModel):
    model_config = {"extra": "forbid"}

    @property
    def mutates(self) -> bool:
        return True


class Tap(_Action):
    tool: Literal["tap"] = "tap"
    x: int
    y: int


class DoubleTap(_Action):
    tool: Literal["double_tap"] = "double_tap"
    x: int
    y: int


class LongPress(_Action):
    tool: Literal["long_press"] = "long_press"
    x: int
    y: int
    duration_ms: int = Field(800, ge=300, le=10_000)


class Swipe(_Action):
    tool: Literal["swipe"] = "swipe"
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = Field(350, ge=50, le=10_000)


class TypeText(_Action):
    tool: Literal["type_text"] = "type_text"
    text: str = Field(min_length=1, max_length=5000)
    clear_first: bool = False
    submit: bool = False


class ClearField(_Action):
    tool: Literal["clear_field"] = "clear_field"


KeyName = Literal[
    "back", "home", "recents", "enter", "delete", "tab", "escape", "hide_keyboard", "wake", "power"
]


class Key(_Action):
    tool: Literal["key"] = "key"
    key: KeyName


class OpenApp(_Action):
    tool: Literal["open_app"] = "open_app"
    package: str

    @field_validator("package")
    @classmethod
    def _pkg(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+", v):
            raise ValueError("nom de package Android invalide")
        return v


class OpenUrl(_Action):
    tool: Literal["open_url"] = "open_url"
    url: str = Field(max_length=4000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", v) or any(c in v for c in "\n\r\0"):
            raise ValueError("URL ou deep link invalide")
        return v


class Rotate(_Action):
    tool: Literal["rotate"] = "rotate"
    orientation: Literal["portrait", "landscape"]


class InstallApk(_Action):
    tool: Literal["install_apk"] = "install_apk"
    path: str  # chemin local côté serveur, résolu par la bibliothèque d'APK, jamais fourni tel quel par le modèle


class UninstallApp(_Action):
    tool: Literal["uninstall_app"] = "uninstall_app"
    package: str
    keep_data: bool = False


class PushFile(_Action):
    tool: Literal["push_file"] = "push_file"
    local_path: str
    remote_path: str = "/sdcard/Download/"


class Shell(_Action):
    """Shell Android de l'invité (I15) : n'a aucun accès à l'hôte Runpod."""

    tool: Literal["shell"] = "shell"
    command: str = Field(min_length=1, max_length=2000)
    timeout_s: float = Field(20, gt=0, le=120)


class Wait(_Action):
    tool: Literal["wait"] = "wait"
    seconds: float = Field(1.0, ge=0.1, le=30)

    @property
    def mutates(self) -> bool:
        return False


DeviceAction = Annotated[
    Tap
    | DoubleTap
    | LongPress
    | Swipe
    | TypeText
    | ClearField
    | Key
    | OpenApp
    | OpenUrl
    | Rotate
    | InstallApk
    | UninstallApp
    | PushFile
    | Shell
    | Wait,
    Field(discriminator="tool"),
]

KEYCODES: dict[str, int] = {
    "back": 4,
    "home": 3,
    "recents": 187,
    "enter": 66,
    "delete": 67,
    "tab": 61,
    "escape": 111,
    "wake": 224,
    "power": 26,
}
