"""Application configuration, sourced entirely from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AutoBI"
    environment: str = "development"
    log_level: str = "INFO"

    # --- storage -----------------------------------------------------------
    # Local filesystem for the MVP. `StorageBackend` is an interface, so a
    # PostgreSQL/S3 implementation can be dropped in without touching services.
    storage_dir: Path = BACKEND_ROOT / "storage"
    storage_backend: str = "local"  # local | supabase
    retention_hours: int = 24

    # --- Supabase (when storage_backend=supabase) --------------------------
    # Files (raw CSV, cleaned Parquet) live in Supabase Storage; dataset
    # metadata, analysis artifacts and saved dashboards live in Postgres,
    # reached through PostgREST. The service-role key stays server-side only.
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "autobi"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    # --- upload limits -----------------------------------------------------
    max_upload_bytes: int = 100 * 1024 * 1024  # 100 MB
    max_rows_analyzed: int = 1_000_000
    allowed_extensions: tuple[str, ...] = (".csv", ".tsv", ".txt")

    # --- analysis tuning ---------------------------------------------------
    max_categorical_cardinality: int = 60
    high_cardinality_threshold: float = 0.6
    max_chart_categories: int = 20
    max_chart_points: int = 2000
    max_table_rows: int = 500

    # --- AI ----------------------------------------------------------------
    ai_provider: str = "none"  # anthropic | openai | none
    ai_model: str = "claude-sonnet-5"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_max_tokens: int = 4096
    ai_temperature: float = 0.2
    ai_timeout_seconds: float = 90.0
    ai_max_retries: int = 2
    ai_enabled: bool = True

    # --- CORS --------------------------------------------------------------
    # Comma-separated allowed origins, or "*" to allow any (handy for a first
    # deploy before a custom domain is set; tighten this in production).
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_allow_all(self) -> bool:
        return self.cors_origins.strip() == "*"

    @property
    def ai_configured(self) -> bool:
        return (
            self.ai_enabled
            and self.ai_provider.lower() not in ("", "none")
            and bool(self.ai_api_key)
        )

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def datasets_dir(self) -> Path:
        return self.storage_dir / "datasets"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.datasets_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
