"""Application configuration.

All settings come from environment variables (or a local .env file). Nothing
hard-codes credentials: defaults exist only for local development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: .../smart-campus-complaints
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Smart Campus Complaint Management System"
    environment: str = "development"
    debug: bool = True
    secret_key: str = "dev-only-insecure-key-change-me"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # --- PostgreSQL (authoritative store) ---
    # When postgres_host is a Unix socket directory (the default on Arch Linux),
    # the port must be omitted from the SQLAlchemy URL: a socket path may not be
    # followed by ":port" or SQLAlchemy parses it as part of the database name.
    postgres_host: str = "/run/postgresql"
    postgres_port: int = 5432
    postgres_user: str = "scms"
    postgres_password: str = "scms_dev_pw"
    postgres_db: str = "smart_campus"
    postgres_test_db: str = "smart_campus_test"

    def _pg_dsn(self, db_name: str) -> str:
        """Build a SQLAlchemy PostgreSQL URL.

        For a Unix socket directory SQLAlchemy 2.x expects the directory in the
        ``host`` query parameter, NOT as a path segment in the authority:
        ``postgresql+psycopg2://user:pw@/dbname?host=/run/postgresql``.
        Putting the path in the authority makes it parse as part of the
        database name.
        """
        credentials = f"{self.postgres_user}:{self.postgres_password}"
        if self.postgres_host.startswith("/"):
            return (
                f"postgresql+psycopg2://{credentials}@/{db_name}"
                f"?host={self.postgres_host}"
            )
        return (
            f"postgresql+psycopg2://{credentials}"
            f"@{self.postgres_host}:{self.postgres_port}/{db_name}"
        )

    # --- MongoDB (flexible event store) ---
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "smart_campus"
    mongo_test_db: str = "smart_campus_test"

    # --- Password hashing ---
    bcrypt_rounds: int = 12

    # --- Outbox relay ---
    outbox_poll_interval_seconds: float = 2.0
    outbox_max_attempts: int = 5

    # --- Triage rule cache TTL ---
    rule_cache_ttl_seconds: int = 60

    # --- ML ---
    ml_model_dir: str = str(PROJECT_ROOT / "ml" / "models")
    ml_report_dir: str = str(PROJECT_ROOT / "ml" / "reports")

    @property
    def database_url(self) -> str:
        return self._pg_dsn(self.postgres_db)

    @property
    def test_database_url(self) -> str:
        return self._pg_dsn(self.postgres_test_db)

    @property
    def sql_echo(self) -> bool:
        return self.debug


@lru_cache
def get_settings() -> Settings:
    return Settings()
