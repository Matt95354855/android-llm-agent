"""Appareil Android piloté par ADB : observation fraîche et exécution d'actions typées."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import shlex
import time
from typing import Protocol

from . import exclusions
from .actions import (
    KEYCODES,
    ClearField,
    DeviceAction,
    DoubleTap,
    InstallApk,
    Key,
    LongPress,
    OpenApp,
    OpenUrl,
    PushFile,
    Rotate,
    Shell,
    Swipe,
    Tap,
    TypeText,
    UninstallApp,
    Wait,
)
from .adb import Adb, AdbError, AdbTimeout
from .models import ActionOutcome, Observation, OutcomeStatus, utcnow
from .uitree import parse_uiautomator_xml

ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


class DeviceBackend(Protocol):
    device_id: str

    async def is_ready(self) -> bool: ...
    async def observe(self, include_tree: bool = True) -> Observation: ...
    async def screenshot(self) -> bytes: ...
    async def execute(self, action: DeviceAction) -> ActionOutcome: ...


def _sha(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data else None


def escape_input_text(text: str) -> str:
    """Échappe un texte ASCII pour `input text` (les espaces deviennent %s)."""
    out = []
    for ch in text:
        if ch == " ":
            out.append("%s")
        elif ch in "\\'\"`$&|;<>()[]{}*?!#~%":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


class AdbDevice:
    def __init__(self, device_id: str, serial: str, adb: Adb | None = None):
        self.device_id = device_id
        self.serial = serial
        self.adb = adb or Adb(serial)
        self._seq = 0

    # --- état -------------------------------------------------------------------------------
    async def is_ready(self) -> bool:
        """Démarrage complet vérifié côté Android, pas seulement par le processus (G04)."""
        if await self.adb.get_state() != "device":
            return False
        boot = await self.adb.shell("getprop sys.boot_completed", timeout=5, check=False)
        if boot.strip() != "1":
            return False
        pm = await self.adb.shell("pm path android", timeout=10, check=False)
        return pm.startswith("package:")

    async def screen_size(self) -> tuple[int, int]:
        out = await self.adb.shell("wm size")
        sizes = re.findall(r"(\d+)x(\d+)", out)
        if not sizes:
            raise AdbError(f"taille d'écran illisible : {out!r}")
        w, h = sizes[-1]  # « Override size » prime sur « Physical size »
        return int(w), int(h)

    async def _rotation(self) -> int:
        out = await self.adb.shell("dumpsys input | grep -m1 SurfaceOrientation", check=False)
        m = re.search(r"SurfaceOrientation:\s*(\d)", out)
        return int(m.group(1)) * 90 if m else 0

    async def _foreground(self) -> tuple[str | None, str | None]:
        out = await self.adb.shell(
            "dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1",
            check=False,
        )
        m = re.search(r"u\d+\s+([\w.]+)/([\w.$]+)", out)
        if not m:
            out = await self.adb.shell("dumpsys window | grep -m1 mCurrentFocus", check=False)
            m = re.search(r"\s([\w.]+)/([\w.$]+)\}", out)
        if not m:
            return None, None
        pkg, act = m.groups()
        return pkg, (pkg + act if act.startswith(".") else act)

    async def _keyboard_visible(self) -> bool:
        out = await self.adb.shell("dumpsys input_method | grep -m1 mInputShown", check=False)
        return "mInputShown=true" in out

    async def screenshot(self) -> bytes:
        png = await self.adb.exec_out("screencap -p", timeout=15)
        if not png.startswith(b"\x89PNG"):
            raise AdbError("capture d'écran invalide")
        return png

    async def _ui_xml(self) -> str:
        return (
            await self.adb.exec_out(
                "sh -c 'uiautomator dump /sdcard/.pe_ui.xml >/dev/null 2>&1 && cat /sdcard/.pe_ui.xml'",
                timeout=20,
            )
        ).decode("utf-8", errors="replace")

    async def observe(self, include_tree: bool = True) -> Observation:
        shot_task = asyncio.create_task(self.screenshot())
        size_task = asyncio.create_task(self.screen_size())
        fg_task = asyncio.create_task(self._foreground())
        kb_task = asyncio.create_task(self._keyboard_visible())
        rot_task = asyncio.create_task(self._rotation())
        png = await shot_task
        t_shot = time.monotonic()
        nodes, status, skew = [], "unavailable", None
        if include_tree:
            try:
                xml = await self._ui_xml()
                nodes = parse_uiautomator_xml(xml)
                status = "ok" if nodes else "empty"
                skew = int((time.monotonic() - t_shot) * 1000)
            except (AdbError, ValueError, SyntaxError):
                status = "unavailable"  # écran animé, WebView, canvas… : la vision prend le relais (H07)
        (w, h), (pkg, act), kb, rot = await asyncio.gather(size_task, fg_task, kb_task, rot_task)
        self._seq += 1
        return Observation(
            device_id=self.device_id,
            seq=self._seq,
            width=w,
            height=h,
            rotation=rot,
            foreground_package=pkg,
            foreground_activity=act,
            keyboard_visible=kb,
            screenshot_png=png,
            screenshot_sha256=_sha(png),
            ui_nodes=nodes,
            ui_tree_status=status,
            ui_tree_skew_ms=skew,
        )

    # --- actions ----------------------------------------------------------------------------
    async def execute(self, action: DeviceAction) -> ActionOutcome:
        started = utcnow()
        try:
            data = await self._dispatch(action)
        except AdbTimeout as exc:
            return ActionOutcome(
                status=OutcomeStatus.unknown, message=str(exc), started_at=started, finished_at=utcnow()
            )
        except _Rejected as exc:
            return ActionOutcome(
                status=OutcomeStatus.rejected, message=str(exc), started_at=started, finished_at=utcnow()
            )
        except AdbError as exc:
            msg = f"{exc} {exc.stderr}".strip()
            return ActionOutcome(
                status=OutcomeStatus.failed, message=msg, started_at=started, finished_at=utcnow()
            )
        return ActionOutcome(
            status=OutcomeStatus.done, started_at=started, finished_at=utcnow(), data=data or {}
        )

    async def _dispatch(self, a: DeviceAction) -> dict | None:
        sh = self.adb.shell
        match a:
            case Tap(x=x, y=y):
                await sh(f"input tap {x} {y}")
            case DoubleTap(x=x, y=y):
                await sh(f"input tap {x} {y} && input tap {x} {y}")
            case LongPress(x=x, y=y, duration_ms=d):
                await sh(f"input swipe {x} {y} {x} {y} {d}")
            case Swipe(x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=d):
                await sh(f"input swipe {x1} {y1} {x2} {y2} {d}")
            case TypeText():
                await self._type_text(a)
            case ClearField():
                await self._clear_field()
            case Key(key="hide_keyboard"):
                if await self._keyboard_visible():
                    await sh(f"input keyevent {KEYCODES['back']}")
            case Key(key=k):
                await sh(f"input keyevent {KEYCODES[k]}")
            case OpenApp(package=p):
                out = await sh(f"monkey -p {p} -c android.intent.category.LAUNCHER 1", check=False)
                if "No activities found" in out or "monkey aborted" in out:
                    raise AdbError(f"application introuvable ou sans écran de lancement : {p}")
            case OpenUrl(url=u):
                out = await sh(f"am start -W -a android.intent.action.VIEW -d {shlex.quote(u)}")
                if "Error" in out:
                    raise AdbError(out.strip())
                pkg, act = await self._foreground()
                return {"received_by": pkg, "activity": act}
            case Rotate(orientation=o):
                await sh("settings put system accelerometer_rotation 0")
                await sh(f"settings put system user_rotation {0 if o == 'portrait' else 1}")
            case InstallApk(path=path):
                res = await self.adb.run("install", "-r", path, timeout=300)  # jamais -g (J05)
                if "Success" not in res.text:
                    raise AdbError(res.text.strip())
                return {"output": res.text.strip()}
            case UninstallApp(package=p, keep_data=keep):
                args = ["uninstall", *(["-k"] if keep else []), p]
                res = await self.adb.run(*args, timeout=120)
                if "Success" not in res.text:
                    raise AdbError(res.text.strip())
            case PushFile(local_path=lp, remote_path=rp):
                await self.adb.run("push", lp, rp, timeout=300)
            case Shell(command=c, timeout_s=t):
                if reason := exclusions.shell_command_violation(c):
                    raise _Rejected(reason)
                res = await self.adb.run("shell", c, timeout=t, check=False)
                return {"exit_code": res.returncode, "output": res.text[-4000:]}
            case Wait(seconds=s):
                await asyncio.sleep(s)
            case _:
                raise _Rejected(f"action non prise en charge : {a!r}")
        return None

    async def _type_text(self, a: TypeText) -> None:
        if a.clear_first:
            await self._clear_field()
        if a.text.isascii() and "\n" not in a.text:
            await self.adb.shell(f"input text {shlex.quote(escape_input_text(a.text))}")
        else:
            await self._type_unicode(a.text)
        if a.submit:
            await self.adb.shell(f"input keyevent {KEYCODES['enter']}")

    async def _type_unicode(self, text: str) -> None:
        """Saisie Unicode via ADBKeyBoard, installé au provisionnement de l'appareil (I03/I04)."""
        imes = await self.adb.shell("ime list -s", check=False)
        if ADB_KEYBOARD_IME not in imes:
            raise _Rejected(
                "saisie non ASCII impossible : le clavier ADBKeyBoard n'est pas installé sur cet appareil"
            )
        previous = (await self.adb.shell("settings get secure default_input_method", check=False)).strip()
        await self.adb.shell(f"ime set {ADB_KEYBOARD_IME}")
        try:
            b64 = base64.b64encode(text.encode("utf-8")).decode()
            await self.adb.shell(f"am broadcast -a ADB_INPUT_B64 --es msg {b64}")
        finally:
            if previous and previous != "null" and previous != ADB_KEYBOARD_IME:
                await self.adb.shell(f"ime set {shlex.quote(previous)}", check=False)

    async def _clear_field(self) -> None:
        await self.adb.shell("input keyevent 123")  # MOVE_END
        await self.adb.shell("input keyevent " + " ".join(["67"] * 80))


class _Rejected(Exception):
    pass
