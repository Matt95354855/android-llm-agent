"""Cycle de vie des Android Emulator dans le Pod, sans Docker imbriqué (B05, G01–G09)."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from . import exclusions
from .adb import Adb, AdbError
from .device import AdbDevice

log = logging.getLogger(__name__)


class EmulatorProfile(BaseModel):
    system_image: str = "system-images;android-30;google_apis;x86_64"
    device_definition: str = "pixel_4"
    width: int = 720
    height: int = 1280
    density: int = 320
    ram_mb: int = 3072
    data_partition: str = "6G"
    cores: int = 2
    gpu: str = "swiftshader_indirect"
    accel: str = "auto"  # "off" quand /dev/kvm est absent (émulation logicielle, très lente)
    locale: str = "fr-FR"
    timezone: str = "Europe/Paris"
    boot_timeout_s: float = 2400


@dataclass
class EmulatorInstance:
    device_id: str
    index: int
    avd_name: str
    port: int
    process: asyncio.subprocess.Process | None = None
    log_path: Path | None = None
    extra: dict = field(default_factory=dict)

    @property
    def serial(self) -> str:
        return f"emulator-{self.port}"


class EmulatorManager:
    """Chaque identifiant d'appareil possède son AVD, son disque et son port, indépendants de l'ordre de démarrage."""

    def __init__(self, sdk_root: Path, data_dir: Path, profile: EmulatorProfile, device_ids: list[str]):
        self.sdk_root = sdk_root
        self.avd_home = data_dir / "avd"
        self.log_dir = data_dir / "logs"
        self.tools_dir = data_dir / "tools"
        self.profile = profile
        self.instances = {
            did: EmulatorInstance(did, i, f"pe_{did.replace('-', '_')}", 5554 + 2 * i)
            for i, did in enumerate(device_ids)
        }
        self.avd_home.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # --- outils SDK -------------------------------------------------------------------------
    def _bin(self, *parts: str) -> str:
        p = self.sdk_root.joinpath(*parts)
        return str(p) if p.exists() else (shutil.which(parts[-1]) or str(p))

    @property
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["ANDROID_SDK_ROOT"] = str(self.sdk_root)
        env["ANDROID_AVD_HOME"] = str(self.avd_home)
        return env

    async def _run(self, *cmd: str, stdin: bytes | None = None, timeout: float = 300) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=self._env,
        )
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout)
        text = out.decode(errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} a échoué : {text[-2000:]}")
        return text

    async def accel_check(self) -> str:
        """Diagnostic d'accélération de l'émulateur, à conserver dans le rapport (B04)."""
        proc = await asyncio.create_subprocess_exec(
            self._bin("emulator", "emulator"),
            "-accel-check",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=self._env,
        )
        out, _ = await proc.communicate()
        return out.decode(errors="replace")

    # --- AVD --------------------------------------------------------------------------------
    def avd_dir(self, inst: EmulatorInstance) -> Path:
        return self.avd_home / f"{inst.avd_name}.avd"

    async def ensure_avd(self, device_id: str) -> None:
        inst = self.instances[device_id]
        if not self.avd_dir(inst).exists():
            await self._run(
                self._bin("cmdline-tools", "latest", "bin", "avdmanager"),
                "create",
                "avd",
                "-n",
                inst.avd_name,
                "-k",
                self.profile.system_image,
                "-d",
                self.profile.device_definition,
                stdin=b"no\n",
            )
        self._write_config(inst)

    def _write_config(self, inst: EmulatorInstance) -> None:
        cfg = self.avd_dir(inst) / "config.ini"
        lines = cfg.read_text().splitlines() if cfg.exists() else []
        values = dict(line.split("=", 1) for line in lines if "=" in line)
        values = {k.strip(): v.strip() for k, v in values.items()}
        p = self.profile
        values.update(
            {
                "hw.lcd.width": str(p.width),
                "hw.lcd.height": str(p.height),
                "hw.lcd.density": str(p.density),
                "hw.ramSize": str(p.ram_mb),
                "disk.dataPartition.size": p.data_partition,
                "hw.cpu.ncore": str(p.cores),
                "hw.keyboard": "yes",
                "hw.gpu.enabled": "yes",
                "hw.gpu.mode": p.gpu,
                **exclusions.AVD_HARDWARE_EXCLUSIONS,
            }
        )
        cfg.write_text("\n".join(f"{k}={v}" for k, v in sorted(values.items())) + "\n")

    # --- démarrage / arrêt ------------------------------------------------------------------
    async def start(self, device_id: str) -> AdbDevice:
        inst = self.instances[device_id]
        await self.ensure_avd(device_id)
        if inst.process is None or inst.process.returncode is not None:
            inst.log_path = self.log_dir / f"{device_id}-emulator.log"
            logf = inst.log_path.open("ab")
            inst.process = await asyncio.create_subprocess_exec(
                self._bin("emulator", "emulator"),
                "-avd",
                inst.avd_name,
                "-port",
                str(inst.port),
                "-no-window",
                "-no-boot-anim",
                "-no-snapshot",
                "-gpu",
                self.profile.gpu,
                "-accel",
                self.profile.accel,
                *exclusions.EMULATOR_FLAGS,
                stdout=logf,
                stderr=asyncio.subprocess.STDOUT,
                env=self._env,
            )
        device = AdbDevice(device_id, inst.serial)
        await self._wait_boot(inst, device)
        await self.provision(device)
        return device

    async def _wait_boot(self, inst: EmulatorInstance, device: AdbDevice) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.profile.boot_timeout_s
        while loop.time() < deadline:
            if inst.process and inst.process.returncode is not None:
                raise RuntimeError(f"l'émulateur {inst.device_id} s'est arrêté (voir {inst.log_path})")
            try:
                if await device.is_ready():
                    return
            except (AdbError, OSError):  # adb encore indisponible pendant le démarrage
                pass
            await asyncio.sleep(3)
        raise TimeoutError(f"{inst.device_id} n'a pas terminé son démarrage")

    async def provision(self, device: AdbDevice) -> None:
        """Réglages idempotents appliqués à chaque démarrage (F08, F11, J03–J05)."""
        adb = device.adb
        await adb.run("root", check=False, timeout=30)
        await adb.run("wait-for-device", timeout=60)
        p = self.profile
        for cmd in (
            f"setprop persist.sys.locale {p.locale}",
            f"setprop persist.sys.timezone {p.timezone}",
            "settings put global window_animation_scale 0",
            "settings put global transition_animation_scale 0",
            "settings put global animator_duration_scale 0",
            "svc power stayon true",
        ):
            await adb.shell(cmd, check=False)
        kb = self.tools_dir / "ADBKeyboard.apk"
        if kb.exists() and "com.android.adbkeyboard" not in await adb.shell("pm list packages", check=False):
            await adb.run("install", "-r", str(kb), timeout=120, check=False)
            await adb.shell("ime enable com.android.adbkeyboard/.AdbIME", check=False)
        await exclusions.enforce(adb)

    async def stop(self, device_id: str, timeout: float = 60) -> None:
        inst = self.instances[device_id]
        await Adb(inst.serial).run("emu", "kill", check=False, timeout=15)
        if inst.process and inst.process.returncode is None:
            try:
                await asyncio.wait_for(inst.process.wait(), timeout)
            except TimeoutError:
                inst.process.terminate()
                await inst.process.wait()
        inst.process = None

    def is_running(self, device_id: str) -> bool:
        p = self.instances[device_id].process
        return p is not None and p.returncode is None
