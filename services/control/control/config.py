from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PE_", env_file=".env", extra="ignore")

    access_token: str | None = None
    allow_no_auth: bool = False  # développement local uniquement
    data_dir: Path = Path("./data")
    database_url: str | None = None

    device_backend: Literal["emulator", "demo"] = "demo"
    device_count: int = 4
    android_sdk_root: Path = Path("/opt/android-sdk")
    android_system_image: str = "system-images;android-30;google_apis;x86_64"
    emulator_gpu: str = "swiftshader_indirect"
    emulator_accel: Literal["auto", "off"] = "auto"
    emulator_stagger_s: float = 20.0  # démarrage échelonné (G08)

    llm_base_url: str = "http://127.0.0.1:8001/v1"
    llm_model: str = "Qwen/Qwen3.6-27B"
    llm_api_key: str = "EMPTY"
    llm_max_concurrency: int = 4
    llm_timeout_s: float = 180
    llm_coord_space: Literal["normalized_1000", "pixels"] = "normalized_1000"

    agent_max_steps: int = 300  # limite technique, pas limite métier (M15)
    agent_max_malformed: int = 4
    agent_settle_timeout_s: float = 6.0
    agent_revalidate_max_age_s: float = 2.0

    web_dist: Path = Path("apps/web/dist")

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{(self.data_dir / 'control.db').resolve()}"

    @property
    def device_ids(self) -> list[str]:
        return [f"tel-{i + 1}" for i in range(self.device_count)]
