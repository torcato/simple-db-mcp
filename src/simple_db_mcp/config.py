from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


ENV_PREFIX = "SIMPLE_DB_MCP_"


@dataclass(frozen=True)
class Settings:
    database_url: str | None = None
    query_timeout_seconds: int = 30
    max_rows: int = 100
    read_only: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env

        return cls(
            database_url=_optional_string(source.get(f"{ENV_PREFIX}DATABASE_URL")),
            query_timeout_seconds=_int_from_env(
                source,
                "QUERY_TIMEOUT_SECONDS",
                default=30,
                minimum=1,
            ),
            max_rows=_int_from_env(source, "MAX_ROWS", default=100, minimum=1),
            read_only=_bool_from_env(source, "READ_ONLY", default=True),
        )

    @property
    def database_configured(self) -> bool:
        return self.database_url is not None

    def public_summary(self) -> dict[str, object]:
        return {
            "database_configured": self.database_configured,
            "query_timeout_seconds": self.query_timeout_seconds,
            "max_rows": self.max_rows,
            "read_only": self.read_only,
        }


def _optional_string(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None


def _int_from_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: int,
    minimum: int,
) -> int:
    env_key = f"{ENV_PREFIX}{key}"
    value = env.get(env_key)

    if value is None or value.strip() == "":
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{env_key} must be an integer.") from exc

    if parsed < minimum:
        raise ValueError(f"{env_key} must be at least {minimum}.")

    return parsed


def _bool_from_env(
    env: Mapping[str, str],
    key: str,
    *,
    default: bool,
) -> bool:
    env_key = f"{ENV_PREFIX}{key}"
    value = env.get(env_key)

    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{env_key} must be a boolean value.")
