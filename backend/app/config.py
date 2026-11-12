"""Runtime configuration. Secrets come from the environment / .env file, never from code."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_prefix="SONIC_", extra="ignore"
    )

    env: str = "production"
    secret_key: str = "dev-insecure-change-me"
    # Fernet key used to encrypt OAuth tokens and bot tokens at rest.
    encryption_key: str = ""
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8790
    # Cookies are marked Secure unless explicitly disabled (tests / plain-HTTP tunnel).
    cookie_secure: bool = True
    session_hours: int = 24 * 14
    public_base_url: str = ""
    frontend_dir: Path = PROJECT_ROOT / "frontend" / "out"
    # AI execution: "off" | "claude_cli". Never switched on implicitly.
    ai_mode: str = "off"
    claude_bin: str = "claude"
    ai_model: str = "haiku"
    http_user_agent: str = "SonicJobs/1.0 (personal job-search assistant)"
    # Safety valve: when false the submit step refuses to click the final button.
    allow_real_submit: bool = True

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'sonic.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.screenshots_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)
            try:
                d.chmod(0o700)
            except OSError:
                pass


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
