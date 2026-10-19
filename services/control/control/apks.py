"""Bibliothèque d'APK : import, téléchargement, identification et installation traçable (S01–S07)."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx

from android_bridge.models import utcnow

MAX_APK_BYTES = 2 * 1024**3


class ApkInvalid(ValueError):
    pass


def inspect_apk(path: Path) -> dict[str, Any]:
    """Vérifie qu'il s'agit bien d'un APK et lit les ABI natives embarquées."""
    with path.open("rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise ApkInvalid("le fichier reçu n'est pas un APK (page HTML ou téléchargement incomplet ?)")
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise ApkInvalid("archive APK corrompue") from exc
    if "AndroidManifest.xml" not in names:
        raise ApkInvalid("AndroidManifest.xml absent : ce n'est pas un APK installable")
    abis = sorted({m.group(1) for n in names if (m := re.match(r"lib/([^/]+)/[^/]+\.so$", n))})
    split = any(n.startswith("split_") for n in names) or path.suffix in (".apks", ".xapk")
    return {
        "abis": abis,
        "arm_only": bool(abis) and all(a.startswith("arm") for a in abis),
        "split": split,
    }


class ApkLibrary:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, apk_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", apk_id):
            raise ApkInvalid("identifiant d'APK invalide")
        return self.root / f"{apk_id}.apk"

    def _finalize(self, tmp: Path, filename: str, source_url: str | None) -> dict[str, Any]:
        h = hashlib.sha256()
        with tmp.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        apk_id = h.hexdigest()
        meta = inspect_apk(tmp)
        dest = self.path(apk_id)
        shutil.move(tmp, dest)
        return {
            "id": apk_id,
            "filename": filename,
            "source_url": source_url,
            "size": dest.stat().st_size,
            "sha256": apk_id,
            "downloaded_at": utcnow().isoformat(),
            **meta,
        }

    def import_file(self, src, filename: str) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False, suffix=".part") as tmp:
            total = 0
            for chunk in iter(lambda: src.read(1 << 20), b""):
                total += len(chunk)
                if total > MAX_APK_BYTES:
                    Path(tmp.name).unlink(missing_ok=True)
                    raise ApkInvalid("fichier trop volumineux")
                tmp.write(chunk)
        try:
            return self._finalize(Path(tmp.name), filename, None)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    async def download(self, url: str) -> dict[str, Any]:
        if not url.startswith(("https://", "http://")):
            raise ApkInvalid("URL http(s) attendue")
        tmp = Path(tempfile.mkstemp(dir=self.root, suffix=".part")[1])
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(30, read=300)
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise ApkInvalid(f"téléchargement refusé ({resp.status_code})")
                    total = 0
                    with tmp.open("wb") as f:
                        async for chunk in resp.aiter_bytes(1 << 20):
                            total += len(chunk)
                            if total > MAX_APK_BYTES:
                                raise ApkInvalid("fichier trop volumineux")
                            f.write(chunk)
                    final_url = str(resp.url)
            name = final_url.rsplit("/", 1)[-1].split("?")[0] or "app.apk"
            return self._finalize(tmp, name, url)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
