from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import UUID

from simple_db_mcp.config import DatabaseSettings, Settings

SUPPORTED_DATABASE_DRIVERS = {
    "postgresql+asyncpg": "PostgreSQL",
    "mysql+asyncmy": "MySQL",
}


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration is missing or unsupported."""


class DatabaseConnectionError(RuntimeError):
    """Raised when a configured database cannot be reached."""


class DatabaseQueryError(RuntimeError):
    """Raised when a database query cannot be safely executed."""


@dataclass(frozen=True)
class DatabaseUrl:
    raw: str
    driver: str
    backend: str
    safe: str
    database: str | None


EngineFactory = Callable[..., Any]
StatementFactory = Callable[[str], Any]


def parse_database_url(url: str) -> DatabaseUrl:
    stripped = url.strip()
    if not stripped:
        raise DatabaseConfigurationError("Database URL must not be empty.")

    parsed = urlsplit(stripped)
    backend = SUPPORTED_DATABASE_DRIVERS.get(parsed.scheme)
    if backend is None:
        supported = ", ".join(sorted(SUPPORTED_DATABASE_DRIVERS))
        raise DatabaseConfigurationError(
            f"Unsupported database driver '{parsed.scheme}'. "
            f"Supported drivers are: {supported}."
        )

    if parsed.hostname is None:
        raise DatabaseConfigurationError("Database URL must include a hostname.")

    return DatabaseUrl(
        raw=stripped,
        driver=parsed.scheme,
        backend=backend,
        safe=redact_database_url(stripped),
        database=unquote(parsed.path.lstrip("/")) or None,
    )


def redact_database_url(url: str) -> str:
    parsed = urlsplit(url)
    if "@" not in parsed.netloc:
        return url

    userinfo, hostinfo = parsed.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return url

    username = userinfo.split(":", 1)[0]
    redacted_netloc = f"{username}:***@{hostinfo}"
    return urlunsplit(
        (
            parsed.scheme,
            redacted_netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


class DatabaseConnection:
    def __init__(
        self,
        url: str,
        *,
        query_timeout_seconds: int = 30,
        max_rows: int = 100,
        read_only: bool = True,
        engine_factory: EngineFactory | None = None,
        statement_factory: StatementFactory | None = None,
    ) -> None:
        self.url = parse_database_url(url)
        self.query_timeout_seconds = query_timeout_seconds
        self.max_rows = max_rows
        self.read_only = read_only
        self._engine_factory = engine_factory
        self._statement_factory = statement_factory
        self._engine: Any | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        engine_factory: EngineFactory | None = None,
        statement_factory: StatementFactory | None = None,
    ) -> DatabaseConnection:
        databases = settings.configured_databases
        if not databases:
            raise DatabaseConfigurationError(
                "SIMPLE_DB_MCP_DATABASE_URL is not configured."
            )
        if len(databases) > 1:
            raise DatabaseConfigurationError(
                "Multiple databases are configured. Select a named database."
            )

        return cls.from_database_settings(
            databases[0],
            engine_factory=engine_factory,
            statement_factory=statement_factory,
        )

    @classmethod
    def from_database_settings(
        cls,
        settings: DatabaseSettings,
        *,
        engine_factory: EngineFactory | None = None,
        statement_factory: StatementFactory | None = None,
    ) -> DatabaseConnection:
        return cls(
            settings.url,
            query_timeout_seconds=settings.query_timeout_seconds,
            max_rows=settings.max_rows,
            read_only=settings.read_only,
            engine_factory=engine_factory,
            statement_factory=statement_factory,
        )

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = self._create_engine()

        return self._engine

    async def ping(self) -> dict[str, object]:
        try:
            await asyncio.wait_for(
                self._execute_ping(),
                timeout=self.query_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DatabaseConnectionError(
                f"Timed out while connecting to {self.url.backend} database."
            ) from exc
        except DatabaseConfigurationError:
            raise
        except Exception as exc:
            raise DatabaseConnectionError(
                f"Could not connect to configured {self.url.backend} database."
            ) from exc

        return {
            "status": "ok",
            "backend": self.url.backend,
            "driver": self.url.driver,
        }

    async def list_schemas(self) -> dict[str, object]:
        rows = await self._run_query(
            self._schema_query(),
            operation_name="list schemas",
        )

        return {
            "backend": self.url.backend,
            "schemas": [str(row["schema_name"]) for row in rows],
        }

    async def list_tables(self, schema: str | None = None) -> dict[str, object]:
        active_schema = self._resolve_schema(schema)
        rows = await self._run_query(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = :schema
            ORDER BY table_name
            """,
            {"schema": active_schema},
            operation_name="list tables",
        )

        return {
            "backend": self.url.backend,
            "schema": active_schema,
            "tables": [
                {
                    "name": str(row["table_name"]),
                    "type": _normalize_table_type(row["table_type"]),
                }
                for row in rows
            ],
        }

    async def describe_table(
        self,
        table: str,
        schema: str | None = None,
    ) -> dict[str, object]:
        table_name = table.strip()
        if not table_name:
            raise DatabaseQueryError("Table name must not be empty.")

        active_schema = self._resolve_schema(schema)
        rows = await self._run_query(
            """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                        AND tc.table_name = kcu.table_name
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                        AND tc.table_schema = c.table_schema
                        AND tc.table_name = c.table_name
                        AND kcu.column_name = c.column_name
                ) AS is_primary_key
            FROM information_schema.columns c
            WHERE c.table_schema = :schema
                AND c.table_name = :table
            ORDER BY c.ordinal_position
            """,
            {"schema": active_schema, "table": table_name},
            operation_name="describe table",
        )

        return {
            "backend": self.url.backend,
            "schema": active_schema,
            "table": table_name,
            "columns": [
                {
                    "name": str(row["column_name"]),
                    "type": str(row["data_type"]),
                    "nullable": _to_bool_from_database(row["is_nullable"]),
                    "default": _serialize_value(row["column_default"]),
                    "position": _to_int_from_database(row["ordinal_position"]),
                    "primary_key": _to_bool_from_database(row["is_primary_key"]),
                }
                for row in rows
            ],
        }

    async def execute_query(
        self,
        sql: str,
        limit: int | None = None,
    ) -> dict[str, object]:
        if self.read_only:
            validate_read_only_query(sql)

        row_limit = self._resolve_row_limit(limit)
        result = await self._run_result_query(
            sql,
            operation_name="execute query",
        )
        rows, columns, truncated = _serialize_limited_result(result, row_limit)

        return {
            "backend": self.url.backend,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "limit": row_limit,
        }

    async def explain_query(self, sql: str) -> dict[str, object]:
        if self.read_only:
            validate_read_only_query(sql)

        result = await self._run_result_query(
            self._explain_sql(sql),
            operation_name="explain query",
        )
        rows = [_serialize_row(row) for row in _fetch_all_mappings(result)]

        return {
            "backend": self.url.backend,
            "columns": list(rows[0]) if rows else _result_columns(result),
            "plan": rows,
        }

    async def aclose(self) -> None:
        if self._engine is None:
            return

        await self._engine.dispose()
        self._engine = None

    async def __aenter__(self) -> DatabaseConnection:
        return self

    async def __aexit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        await self.aclose()

    def _create_engine(self) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory(self.url.raw, pool_pre_ping=True)

        try:
            from sqlalchemy.ext.asyncio import create_async_engine
        except ModuleNotFoundError as exc:
            if exc.name != "sqlalchemy":
                raise

            raise RuntimeError(
                "SQLAlchemy is not installed. Install project dependencies "
                "before connecting to a database."
            ) from exc

        return create_async_engine(self.url.raw, pool_pre_ping=True)

    def _create_statement(self, sql: str) -> Any:
        if self._statement_factory is not None:
            return self._statement_factory(sql)

        try:
            from sqlalchemy import text
        except ModuleNotFoundError as exc:
            if exc.name != "sqlalchemy":
                raise

            raise RuntimeError(
                "SQLAlchemy is not installed. Install project dependencies "
                "before connecting to a database."
            ) from exc

        return text(sql)

    async def _execute_ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(self._create_statement("SELECT 1"))

    async def _run_query(
        self,
        sql: str,
        params: dict[str, object] | None = None,
        *,
        operation_name: str,
    ) -> list[dict[str, object]]:
        result = await self._run_result_query(
            sql,
            params,
            operation_name=operation_name,
        )
        return [_serialize_row(row) for row in _fetch_all_mappings(result)]

    async def _run_result_query(
        self,
        sql: str,
        params: dict[str, object] | None = None,
        *,
        operation_name: str,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                self._execute_statement(sql, params),
                timeout=self.query_timeout_seconds,
            )
        except TimeoutError as exc:
            raise DatabaseQueryError(
                f"Timed out while trying to {operation_name} on configured "
                f"{self.url.backend} database."
            ) from exc
        except DatabaseQueryError:
            raise
        except Exception as exc:
            raise DatabaseQueryError(
                f"Could not {operation_name} on configured {self.url.backend} "
                "database."
            ) from exc

    async def _execute_statement(
        self,
        sql: str,
        params: dict[str, object] | None = None,
    ) -> Any:
        async with self.engine.connect() as connection:
            statement = self._create_statement(sql)
            if params is None:
                return await connection.execute(statement)

            return await connection.execute(statement, params)

    def _schema_query(self) -> str:
        if self.url.driver == "postgresql+asyncpg":
            return """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
                AND schema_name NOT LIKE 'pg_toast%'
            ORDER BY schema_name
            """

        return """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN (
            'information_schema',
            'mysql',
            'performance_schema',
            'sys'
        )
        ORDER BY schema_name
        """

    def _resolve_schema(self, schema: str | None) -> str:
        if schema is not None and schema.strip():
            return schema.strip()

        if self.url.driver == "postgresql+asyncpg":
            return "public"

        if self.url.database is not None:
            return self.url.database

        raise DatabaseQueryError(
            "Schema must be provided when the database URL has no database name."
        )

    def _resolve_row_limit(self, limit: int | None) -> int:
        if limit is None:
            return self.max_rows

        if limit < 1:
            raise DatabaseQueryError("Query limit must be at least 1.")

        return min(limit, self.max_rows)

    def _explain_sql(self, sql: str) -> str:
        if self.url.driver == "postgresql+asyncpg":
            return f"EXPLAIN (FORMAT JSON)\n{sql}"

        return f"EXPLAIN\n{sql}"


ConnectionFactory = Callable[[DatabaseSettings], DatabaseConnection]


class DatabaseRegistry:
    def __init__(
        self,
        databases: tuple[DatabaseSettings, ...],
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._database_settings = databases
        self._connection_factory = connection_factory or (
            DatabaseConnection.from_database_settings
        )
        self._connections: dict[str, DatabaseConnection] = {}
        self._settings_by_name = {
            database.name.lower(): database for database in self._database_settings
        }

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> DatabaseRegistry:
        return cls(
            settings.configured_databases,
            connection_factory=connection_factory,
        )

    @property
    def configured(self) -> bool:
        return bool(self._database_settings)

    @property
    def requires_database_name(self) -> bool:
        return len(self._database_settings) > 1

    @property
    def names(self) -> list[str]:
        return [database.name for database in self._database_settings]

    def get(self, database: str | None = None) -> DatabaseConnection | None:
        if not self._database_settings:
            return None

        database_name = self._resolve_database_name(database)
        if database_name not in self._connections:
            self._connections[database_name] = self._connection_factory(
                self._settings_by_name[database_name]
            )

        return self._connections[database_name]

    async def aclose(self) -> None:
        for connection in self._connections.values():
            await connection.aclose()
        self._connections.clear()

    def _resolve_database_name(self, database: str | None) -> str:
        if database is None or not database.strip():
            if len(self._database_settings) == 1:
                return self._database_settings[0].name.lower()

            available = ", ".join(self.names)
            raise DatabaseConfigurationError(
                "A database name is required when multiple databases are "
                f"configured. Available databases: {available}."
            )

        database_name = database.strip()
        database_key = database_name.lower()
        if database_key not in self._settings_by_name:
            available = ", ".join(self.names)
            raise DatabaseConfigurationError(
                f"Unknown database '{database_name}'. Available databases: "
                f"{available}."
            )

        return database_key


READ_ONLY_START_KEYWORDS = {"select", "with", "show", "describe", "desc"}
MUTATING_KEYWORDS = {
    "alter",
    "begin",
    "call",
    "commit",
    "copy",
    "create",
    "delete",
    "drop",
    "execute",
    "grant",
    "insert",
    "load",
    "lock",
    "merge",
    "replace",
    "reset",
    "revoke",
    "rollback",
    "savepoint",
    "set",
    "start",
    "truncate",
    "update",
    "use",
    "vacuum",
}


def validate_read_only_query(sql: str) -> None:
    cleaned = _strip_sql_comments_and_literals(sql)
    statements = [part.strip() for part in cleaned.split(";") if part.strip()]

    if len(statements) != 1:
        raise DatabaseQueryError("Only one SQL statement can be executed at a time.")

    tokens = re.findall(r"[a-z_][a-z0-9_]*", statements[0].lower())
    if not tokens:
        raise DatabaseQueryError("SQL query must not be empty.")

    if tokens[0] not in READ_ONLY_START_KEYWORDS:
        allowed = ", ".join(sorted(READ_ONLY_START_KEYWORDS))
        raise DatabaseQueryError(
            f"Only read-only statements are allowed. Expected one of: {allowed}."
        )

    mutating_tokens = sorted(set(tokens) & MUTATING_KEYWORDS)
    if mutating_tokens:
        blocked = ", ".join(mutating_tokens)
        raise DatabaseQueryError(
            f"Query contains blocked mutating keyword(s): {blocked}."
        )


def _strip_sql_comments_and_literals(sql: str) -> str:
    output: list[str] = []
    index = 0
    length = len(sql)

    while index < length:
        current = sql[index]
        next_character = sql[index + 1] if index + 1 < length else ""

        if current == "-" and next_character == "-":
            output.extend("  ")
            index += 2
            while index < length and sql[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue

        if current == "/" and next_character == "*":
            output.extend("  ")
            index += 2
            while index < length:
                if sql[index] == "*" and index + 1 < length and sql[index + 1] == "/":
                    output.extend("  ")
                    index += 2
                    break
                output.append(" ")
                index += 1
            continue

        if current in {"'", '"'}:
            quote = current
            output.append(" ")
            index += 1
            while index < length:
                if sql[index] == quote:
                    if index + 1 < length and sql[index + 1] == quote:
                        output.extend("  ")
                        index += 2
                        continue
                    output.append(" ")
                    index += 1
                    break
                output.append(" ")
                index += 1
            continue

        output.append(current)
        index += 1

    return "".join(output)


def _fetch_all_mappings(result: Any) -> list[Any]:
    mappings = result.mappings() if hasattr(result, "mappings") else result
    if hasattr(mappings, "all"):
        return list(mappings.all())

    return list(mappings)


def _serialize_limited_result(
    result: Any,
    limit: int,
) -> tuple[list[dict[str, object]], list[str], bool]:
    mappings = result.mappings() if hasattr(result, "mappings") else result
    if hasattr(mappings, "fetchmany"):
        raw_rows = list(mappings.fetchmany(limit + 1))
    elif hasattr(mappings, "all"):
        raw_rows = list(mappings.all())[: limit + 1]
    else:
        raw_rows = list(mappings)[: limit + 1]

    truncated = len(raw_rows) > limit
    rows = [_serialize_row(row) for row in raw_rows[:limit]]
    columns = list(rows[0]) if rows else _result_columns(result)

    return rows, columns, truncated


def _serialize_row(row: Any) -> dict[str, object]:
    return {str(key): _serialize_value(value) for key, value in dict(row).items()}


def _serialize_value(value: Any) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, Decimal | UUID):
        return str(value)

    if isinstance(value, datetime | date | time):
        return value.isoformat()

    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()

    if isinstance(value, list | tuple):
        return [_serialize_value(item) for item in value]

    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}

    return str(value)


def _result_columns(result: Any) -> list[str]:
    if not hasattr(result, "keys"):
        return []

    return [str(column) for column in result.keys()]


def _normalize_table_type(value: object) -> str:
    normalized = str(value).strip().lower()
    if "view" in normalized:
        return "view"
    if "table" in normalized:
        return "table"

    return normalized


def _to_bool_from_database(value: object) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _to_int_from_database(value: object) -> int:
    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    return int(str(value))
