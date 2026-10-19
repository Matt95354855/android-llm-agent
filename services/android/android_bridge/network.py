"""IP publique de sortie vue depuis l'Android lui-même, pas depuis l'hôte (C08, C14).

L'image Android n'embarque pas toujours curl : repli sur le netcat de toybox en HTTP simple.
"""

from __future__ import annotations

import ipaddress
import shlex

from .adb import Adb, AdbError

ENDPOINTS = (("api.ipify.org", "/"), ("icanhazip.com", "/"))


def parse_ip(body: str) -> str | None:
    for token in reversed(body.replace("\r", "\n").split()):
        try:
            return str(ipaddress.ip_address(token.strip()))
        except ValueError:
            continue
    return None


async def egress_ip(adb: Adb) -> tuple[str | None, str]:
    """Retourne (ip, méthode). ip vaut None si aucune mesure n'a abouti."""
    for host, path in ENDPOINTS:
        out = await _try(adb, f"curl -4 -s --max-time 8 https://{host}{path}")
        if ip := parse_ip(out):
            return ip, f"curl https://{host}"
        # Séquences \r\n interprétées par printf côté Android : aucun vrai saut de ligne ne traverse adb shell.
        request = shlex.quote(
            f"GET {path} HTTP/1.0\\r\\nHost: {host}\\r\\nUser-Agent: phone-emulator\\r\\n\\r\\n"
        )
        out = await _try(adb, f"printf {request} | toybox nc {host} 80")
        if ip := parse_ip(out.split("\r\n\r\n", 1)[-1]):
            return ip, f"nc http://{host}"
    return None, "aucune méthode n'a abouti"


async def _try(adb: Adb, command: str) -> str:
    try:
        return await adb.shell(command, timeout=15, check=False)
    except AdbError:  # délai dépassé ou appareil injoignable : on essaie la méthode suivante
        return ""
