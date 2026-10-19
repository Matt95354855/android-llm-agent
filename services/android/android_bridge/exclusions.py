"""GPS, caméra et microphone exclus (J01–J11).

Défense en profondeur : périphériques absents dans le profil d'émulation (config AVD),
permissions révoquées et appops refusés pour chaque application, localisation désactivée,
et commandes shell de réactivation bloquées. Une consigne dans le prompt ne suffit pas (J08).
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from .adb import Adb

EXCLUDED_PERMISSIONS = (
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
)
EXCLUDED_APPOPS = ("CAMERA", "RECORD_AUDIO", "FINE_LOCATION", "COARSE_LOCATION", "MONITOR_LOCATION")

# Lignes à imposer dans le config.ini de chaque AVD, avant son premier démarrage (F11).
AVD_HARDWARE_EXCLUSIONS = {
    "hw.camera.back": "none",
    "hw.camera.front": "none",
    "hw.audioInput": "no",
    "hw.gps": "no",
}
EMULATOR_FLAGS = ["-camera-back", "none", "-camera-front", "none", "-no-audio"]

_FORBIDDEN_SHELL = [
    re.compile(r"\bpm\s+grant\b.*\b(CAMERA|RECORD_AUDIO|LOCATION)\b", re.I),
    re.compile(r"\bappops\s+set\b.*\b(CAMERA|RECORD_AUDIO|LOCATION)\b.*\ballow\b", re.I),
    re.compile(r"\blocation_mode\b|\bset-location-enabled\s+true\b|\blocation_providers_allowed\b", re.I),
    re.compile(r"\bgeo\s+fix\b|\bemu\s+geo\b", re.I),
    re.compile(r"/dev/video|tinycap|\bscreenrecord\b.*--mic", re.I),
]


def shell_command_violation(command: str) -> str | None:
    """Retourne la raison du refus si la commande tente de réactiver une capacité exclue."""
    for pat in _FORBIDDEN_SHELL:
        if pat.search(command):
            return "commande refusée : elle réactiverait le GPS, la caméra ou le microphone"
    return None


async def disable_location(adb: Adb) -> None:
    await adb.shell("settings put secure location_mode 0", check=False)
    await adb.shell("cmd location set-location-enabled false", check=False)


async def lock_package(adb: Adb, package: str) -> None:
    for perm in EXCLUDED_PERMISSIONS:
        await adb.shell(f"pm revoke {package} {perm}", check=False)
    for op in EXCLUDED_APPOPS:
        await adb.shell(f"appops set {package} {op} deny", check=False)


async def third_party_packages(adb: Adb) -> list[str]:
    out = await adb.shell("pm list packages -3", check=False)
    return [line.removeprefix("package:").strip() for line in out.splitlines() if line.startswith("package:")]


async def enforce(adb: Adb) -> None:
    await disable_location(adb)
    for pkg in await third_party_packages(adb):
        await lock_package(adb, pkg)


class ComplianceReport(BaseModel):
    compliant: bool
    camera_devices: int | None
    location_enabled: bool | None
    packages_with_grants: dict[str, list[str]]
    notes: list[str] = []


async def check(adb: Adb) -> ComplianceReport:
    notes: list[str] = []
    cams_out = await adb.shell("dumpsys media.camera | grep -i 'Number of camera devices'", check=False)
    m = re.search(r"(\d+)", cams_out)
    camera_devices = int(m.group(1)) if m else None
    if camera_devices is None:
        notes.append("nombre de caméras non lisible sur cette image")

    loc_out = (await adb.shell("settings get secure location_mode", check=False)).strip()
    location_enabled = None if loc_out in ("", "null") else loc_out != "0"

    grants: dict[str, list[str]] = {}
    for pkg in await third_party_packages(adb):
        dump = await adb.shell(f"dumpsys package {pkg}", check=False)
        granted = [p.rsplit(".", 1)[-1] for p in EXCLUDED_PERMISSIONS if f"{p}: granted=true" in dump]
        if granted:
            grants[pkg] = granted

    compliant = camera_devices in (0, None) and location_enabled is not True and not grants
    if camera_devices is None:
        compliant = False
    return ComplianceReport(
        compliant=compliant,
        camera_devices=camera_devices,
        location_enabled=location_enabled,
        packages_with_grants=grants,
        notes=notes,
    )
