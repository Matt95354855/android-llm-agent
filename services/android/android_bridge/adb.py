"""Appels ADB asynchrones, toujours ciblés sur un serial explicite."""

from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass


class AdbError(RuntimeError):
    def __init__(self, message: str, *, returncode: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class AdbTimeout(AdbError):
    """La commande n'a pas répondu à temps : son effet sur l'appareil est inconnu."""


@dataclass(frozen=True)
class AdbResult:
    stdout: bytes
    stderr: bytes
    returncode: int

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


class Adb:
    """Client ADB lié à un seul appareil. Aucun appel n'est envoyé sans `-s serial` (G02, T13)."""

    def __init__(self, serial: str, adb_path: str | None = None, default_timeout: float = 20.0):
        if not serial:
            raise ValueError("serial ADB obligatoire")
        self.serial = serial
        self.adb_path = adb_path or os.environ.get("PE_ADB_PATH", "adb")
        self.default_timeout = default_timeout

    async def run(self, *args: str, timeout: float | None = None, check: bool = True) -> AdbResult:
        cmd = [self.adb_path, "-s", self.serial, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout or self.default_timeout)
        except TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:  # déjà terminé entre-temps
                pass
            await proc.wait()
            raise AdbTimeout(f"délai dépassé : {shlex.join(args)}") from exc
        result = AdbResult(out, err, proc.returncode or 0)
        if check and result.returncode != 0:
            raise AdbError(
                f"adb {shlex.join(args)} a échoué ({result.returncode})",
                returncode=result.returncode,
                stderr=err.decode("utf-8", errors="replace"),
            )
        return result

    async def shell(self, command: str, timeout: float | None = None, check: bool = True) -> str:
        res = await self.run("shell", command, timeout=timeout, check=check)
        return res.text

    async def exec_out(self, command: str, timeout: float | None = None) -> bytes:
        res = await self.run("exec-out", command, timeout=timeout)
        return res.stdout

    async def get_state(self) -> str:
        try:  # le premier appel démarre le serveur adb, parfois lentement
            res = await self.run("get-state", timeout=30, check=False)
        except AdbError:
            return "offline"
        return res.text.strip() if res.returncode == 0 else "offline"
