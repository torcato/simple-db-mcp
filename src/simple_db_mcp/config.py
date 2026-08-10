from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_PREFIX = "SIMPLE_DB_MCP_"
DEFAULT_DATABASE_NAME = "default"


@dataclass(frozen=True)
class DatabaseSettings:
    name: str
    url: str
    query_timeout_seconds: int = 30
    max_rows: int = 100
    read_only: bool = True

    def public_summary(self) -> dict[str, object]:
        return {
            "name": self.name,
            "query_timeout_seconds": self.query_timeout_seconds,
            "max_rows": self.max_rows,
            "read_only": self.read_only,
        }


@dataclass(frozen=True)
class Settings:
    database_url: str | None = None
    query_timeout_seconds: int = 30
    max_rows: int = 100
    read_only: bool = True
    databases: tuple[DatabaseSettings, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source: Mapping[str, str]
        if env is None:
            _load_dotenv()
            source = os.environ
        else:
            source = env

        config_file = _optional_string(source.get(f"{ENV_PREFIX}CONFIG_FILE"))
        if config_file is not None:
            return cls.from_toml(config_file)

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

    @classmethod
    def from_toml(cls, path: str | Path) -> Settings:
        data = _load_toml(path)
        databases_value = data.get("databases")

        if not isinstance(databases_value, list) or not databases_value:
            raise ValueError(
                "Config file must include at least one [[databases]] entry."
            )

        databases = tuple(
            _database_settings_from_toml(entry, index)
            for index, entry in enumerate(databases_value, start=1)
        )
        _validate_unique_database_names(databases)

        return cls(databases=databases)

    @property
    def database_configured(self) -> bool:
        return bool(self.configured_databases)

    @property
    def configured_databases(self) -> tuple[DatabaseSettings, ...]:
        if self.databases:
            return self.databases

        if self.database_url is None:
            return ()

        return (
            DatabaseSettings(
                name=DEFAULT_DATABASE_NAME,
                url=self.database_url,
                query_timeout_seconds=self.query_timeout_seconds,
                max_rows=self.max_rows,
                read_only=self.read_only,
            ),
        )

    def public_summary(self) -> dict[str, object]:
        databases = self.configured_databases
        summary: dict[str, object] = {
            "database_configured": self.database_configured,
            "database_count": len(databases),
            "database_names": [database.name for database in databases],
            "requires_database_name": len(databases) > 1,
        }

        if len(databases) <= 1:
            database = databases[0] if databases else None
            summary.update(
                {
                    "query_timeout_seconds": (
                        database.query_timeout_seconds
                        if database is not None
                        else self.query_timeout_seconds
                    ),
                    "max_rows": (
                        database.max_rows if database is not None else self.max_rows
                    ),
                    "read_only": (
                        database.read_only if database is not None else self.read_only
                    ),
                }
            )
        else:
            summary["databases"] = [
                database.public_summary() for database in databases
            ]

        return summary


def _load_dotenv() -> None:
    from dotenv import find_dotenv, load_dotenv

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)


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


def _load_toml(path: str | Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with Path(path).open("rb") as config_file:
        data = tomllib.load(config_file)

    if not isinstance(data, dict):
        raise ValueError("Config file must contain a TOML table.")

    return data


def _database_settings_from_toml(
    entry: object,
    index: int,
) -> DatabaseSettings:
    if not isinstance(entry, dict):
        raise ValueError(f"Database entry #{index} must be a TOML table.")

    context = f"databases entry #{index}"
    return DatabaseSettings(
        name=_string_from_toml(entry, "name", context),
        url=_string_from_toml(entry, "url", context),
        query_timeout_seconds=_int_from_toml(
            entry,
            "query_timeout_seconds",
            default=30,
            minimum=1,
            context=context,
        ),
        max_rows=_int_from_toml(
            entry,
            "max_rows",
            default=100,
            minimum=1,
            context=context,
        ),
        read_only=_bool_from_toml(entry, "read_only", default=True, context=context),
    )


def _string_from_toml(
    table: Mapping[str, object],
    key: str,
    context: str,
) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must include a non-empty '{key}' string.")

    return value.strip()


def _int_from_toml(
    table: Mapping[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    context: str,
) -> int:
    value = table.get(key)
    if value is None:
        return default

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} '{key}' must be an integer.")

    if value < minimum:
        raise ValueError(f"{context} '{key}' must be at least {minimum}.")

    return value


def _bool_from_toml(
    table: Mapping[str, object],
    key: str,
    *,
    default: bool,
    context: str,
) -> bool:
    value = table.get(key)
    if value is None:
        return default

    if not isinstance(value, bool):
        raise ValueError(f"{context} '{key}' must be a boolean.")

    return value


def _validate_unique_database_names(
    databases: tuple[DatabaseSettings, ...],
) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for database in databases:
        normalized = database.name.lower()
        if normalized in seen:
            duplicates.add(database.name)
        seen.add(normalized)

    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Database names must be unique: {duplicate_list}.")
