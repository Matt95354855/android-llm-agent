"""Appareil factice pour développer l'interface et tester l'orchestration sans Android.

Il est toujours signalé comme « démo » : il ne vaut jamais validation matérielle (B18, Y19).
"""

from __future__ import annotations

import asyncio
import hashlib
import struct
import zlib

from .actions import ClearField, DeviceAction, Key, OpenApp, Swipe, Tap, TypeText, Wait
from .models import ActionOutcome, Bounds, Observation, OutcomeStatus, UiNode, utcnow

W, H = 720, 1280
BG = (18, 20, 26)
HEADER = [(61, 90, 254), (0, 150, 136), (233, 30, 99), (255, 152, 0)]


def encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + r for r in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


class DemoDevice:
    def __init__(self, device_id: str, index: int = 0):
        self.device_id = device_id
        self.index = index
        self.counter = 0
        self.note = ""
        self.foreground = "fr.demo.compteur"
        self._seq = 0
        self.actions: list[DeviceAction] = []

    async def is_ready(self) -> bool:
        return True

    def _nodes(self) -> list[UiNode]:
        def n(i: int, text: str, b: tuple[int, int, int, int], **kw) -> UiNode:
            return UiNode(
                index=i,
                text=text,
                bounds=Bounds(left=b[0], top=b[1], right=b[2], bottom=b[3]),
                package=self.foreground,
                **kw,
            )

        return [
            n(0, "Compteur démo", (0, 0, 720, 140), cls="TextView"),
            n(1, f"Valeur : {self.counter}", (40, 200, 680, 300), cls="TextView"),
            n(2, "Ajouter", (40, 360, 340, 480), cls="Button", clickable=True, resource_id="fr.demo:id/add"),
            n(
                3,
                "Réinitialiser",
                (380, 360, 680, 480),
                cls="Button",
                clickable=True,
                resource_id="fr.demo:id/reset",
            ),
            n(
                4,
                self.note,
                (40, 560, 680, 680),
                cls="EditText",
                clickable=True,
                editable=True,
                resource_id="fr.demo:id/note",
            ),
        ]

    def _render(self) -> bytes:
        bg = bytes(BG) * W
        rows = [bytearray(bg) for _ in range(H)]

        def rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
            seg = bytes(color) * (x1 - x0)
            for y in range(y0, y1):
                rows[y][x0 * 3 : x1 * 3] = seg

        rect(0, 0, W, 140, HEADER[self.index % len(HEADER)])
        rect(40, 360, 340, 480, (46, 125, 50))
        rect(380, 360, 680, 480, (120, 120, 130))
        rect(40, 560, 680, 680, (40, 44, 54))
        bar = min(640, 20 * self.counter)
        if bar:
            rect(40, 220, 40 + bar, 280, (255, 255, 255))
        if self.note:
            rect(60, 600, 60 + min(600, 12 * len(self.note)), 640, (200, 200, 210))
        return encode_png(W, H, [bytes(r) for r in rows])

    async def screenshot(self) -> bytes:
        return await asyncio.to_thread(self._render)

    async def observe(self, include_tree: bool = True) -> Observation:
        png = await self.screenshot()
        self._seq += 1
        return Observation(
            device_id=self.device_id,
            seq=self._seq,
            width=W,
            height=H,
            foreground_package=self.foreground,
            foreground_activity=self.foreground + ".Main",
            screenshot_png=png,
            screenshot_sha256=hashlib.sha256(png).hexdigest(),
            ui_nodes=self._nodes() if include_tree else [],
            ui_tree_status="ok" if include_tree else "unavailable",
        )

    async def execute(self, action: DeviceAction) -> ActionOutcome:
        started = utcnow()
        self.actions.append(action)
        await asyncio.sleep(0.05)
        match action:
            case Tap(x=x, y=y):
                if 40 <= x <= 340 and 360 <= y <= 480:
                    self.counter += 1
                elif 380 <= x <= 680 and 360 <= y <= 480:
                    self.counter = 0
            case TypeText(text=t, clear_first=c):
                self.note = t if c else self.note + t
            case ClearField():
                self.note = ""
            case OpenApp(package=p):
                self.foreground = p
            case Key() | Swipe() | Wait():
                pass
            case _:
                return ActionOutcome(
                    status=OutcomeStatus.rejected,
                    message="non simulé en démo",
                    started_at=started,
                    finished_at=utcnow(),
                )
        return ActionOutcome(status=OutcomeStatus.done, started_at=started, finished_at=utcnow())
