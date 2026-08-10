from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from simple_db_mcp.config import DatabaseSettings, Settings
from simple_db_mcp.database import (
    DatabaseConfigurationError,
    DatabaseConnection,
    DatabaseConnectionError,
    DatabaseQueryError,
    DatabaseRegistry,
    parse_database_url,
    redact_database_url,
    validate_read_only_query,
)


class FakeMappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.fetchmany_calls: list[int] = []

    def all(self) -> list[dict[str, object]]:
        return self.rows

    def fetchmany(self, size: int) -> list[dict[str, object]]:
        self.fetchmany_calls.append(size)
        return self.rows[:size]


class FakeResult:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        columns: list[str] | None = None,
    ) -> None:
        self.mapping_result = FakeMappingResult(rows)
        self.columns = columns or list(rows[0]) if rows else columns or []

    def mappings(self) -> FakeMappingResult:
        return self.mapping_result

    def keys(self) -> list[str]:
        return self.columns


class FakeAsyncConnection:
    def __init__(self, engine: FakeAsyncEngine) -> None:
        self.engine = engine

    async def __aenter__(self) -> FakeAsyncConnection:
        return self

    async def __aexit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None

    async def execute(
        self,
        statement: object,
        params: dict[str, object] | None = None,
    ) -> FakeResult:
        self.engine.statements.append(statement)
        self.engine.params.append(params)
        if self.engine.failure is not None:
            raise self.engine.failure
        return self.engine.result


class FakeAsyncEngine:
    def __init__(
        self,
        url: str,
        kwargs: dict[str, object],
        *,
        result: FakeResult | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.url = url
        self.kwargs = kwargs
        self.result = result or FakeResult([])
        self.failure = failure
        self.statements: list[object] = []
        self.params: list[dict[str, object] | None] = []
        self.dispose_calls = 0

    def connect(self) -> FakeAsyncConnection:
        return FakeAsyncConnection(self)

    async def dispose(self) -> None:
        self.dispose_calls += 1


def test_parse_database_url_accepts_postgresql_asyncpg() -> None:
    parsed = parse_database_url(
        "postgresql+asyncpg://user:secret@localhost:5432/app"
    )

    assert parsed.driver == "postgresql+asyncpg"
    assert parsed.backend == "PostgreSQL"
    assert parsed.safe == "postgresql+asyncpg://user:***@localhost:5432/app"


def test_parse_database_url_accepts_mysql_asyncmy() -> None:
    parsed = parse_database_url("mysql+asyncmy://user:secret@localhost:3306/app")

    assert parsed.driver == "mysql+asyncmy"
    assert parsed.backend == "MySQL"


def test_parse_database_url_rejects_unsupported_driver() -> None:
    with pytest.raises(DatabaseConfigurationError, match="Unsupported database driver"):
        parse_database_url("sqlite+aiosqlite:///tmp/app.db")


def test_parse_database_url_rejects_missing_hostname() -> None:
    with pytest.raises(DatabaseConfigurationError, match="hostname"):
        parse_database_url("postgresql+asyncpg:///app")


def test_redact_database_url_keeps_urls_without_password() -> None:
    url = "postgresql+asyncpg://localhost:5432/app"

    assert redact_database_url(url) == url


def test_from_settings_requires_database_url() -> None:
    with pytest.raises(DatabaseConfigurationError, match="not configured"):
        DatabaseConnection.from_settings(Settings(database_url=None))


def test_from_settings_rejects_multiple_databases() -> None:
    settings = Settings(
        databases=(
            DatabaseSettings(
                name="app",
                url="mysql+asyncmy://user:secret@localhost:3306/app",
            ),
            DatabaseSettings(
                name="warehouse",
                url="postgresql+asyncpg://user:secret@localhost:5432/warehouse",
            ),
        )
    )

    with pytest.raises(DatabaseConfigurationError, match="Multiple databases"):
        DatabaseConnection.from_settings(settings)


def test_ping_creates_engine_lazily_and_disposes_it() -> None:
    engines: list[FakeAsyncEngine] = []

    def engine_factory(url: str, **kwargs: Any) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url, kwargs)
        engines.append(engine)
        return engine

    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        query_timeout_seconds=5,
        engine_factory=engine_factory,
        statement_factory=lambda sql: f"text:{sql}",
    )

    assert engines == []

    result = asyncio.run(connection.ping())

    assert result == {
        "status": "ok",
        "backend": "PostgreSQL",
        "driver": "postgresql+asyncpg",
    }
    assert len(engines) == 1
    assert engines[0].url == "postgresql+asyncpg://user:secret@localhost:5432/app"
    assert engines[0].kwargs == {"pool_pre_ping": True}
    assert engines[0].statements == ["text:SELECT 1"]
    assert engines[0].params == [None]

    asyncio.run(connection.aclose())

    assert engines[0].dispose_calls == 1


def test_ping_error_message_does_not_leak_password() -> None:
    password = "super-secret-password"
    failure = RuntimeError(
        f"Could not connect to postgresql+asyncpg://user:{password}@localhost/app"
    )

    def engine_factory(url: str, **kwargs: Any) -> FakeAsyncEngine:
        return FakeAsyncEngine(url, kwargs, failure=failure)

    connection = DatabaseConnection(
        f"postgresql+asyncpg://user:{password}@localhost:5432/app",
        engine_factory=engine_factory,
        statement_factory=lambda sql: sql,
    )

    with pytest.raises(DatabaseConnectionError) as exc_info:
        asyncio.run(connection.ping())

    assert password not in str(exc_info.value)
    assert str(exc_info.value) == (
        "Could not connect to configured PostgreSQL database."
    )


def test_list_schemas_returns_postgresql_schema_names() -> None:
    engine = FakeAsyncEngine(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        {},
        result=FakeResult(
            [
                {"schema_name": "public"},
                {"schema_name": "sales"},
            ]
        ),
    )
    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.list_schemas())

    assert result == {
        "backend": "PostgreSQL",
        "schemas": ["public", "sales"],
    }
    assert "information_schema.schemata" in str(engine.statements[0])
    assert "pg_catalog" in str(engine.statements[0])


def test_list_tables_defaults_to_mysql_database_name() -> None:
    engine = FakeAsyncEngine(
        "mysql+asyncmy://user:secret@localhost:3306/app",
        {},
        result=FakeResult(
            [
                {"table_name": "customers", "table_type": "BASE TABLE"},
                {"table_name": "customer_summary", "table_type": "VIEW"},
            ]
        ),
    )
    connection = DatabaseConnection(
        "mysql+asyncmy://user:secret@localhost:3306/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.list_tables())

    assert result == {
        "backend": "MySQL",
        "schema": "app",
        "tables": [
            {"name": "customers", "type": "table"},
            {"name": "customer_summary", "type": "view"},
        ],
    }
    assert engine.params == [{"schema": "app"}]


def test_list_tables_requires_schema_when_mysql_url_has_no_database_name() -> None:
    connection = DatabaseConnection("mysql+asyncmy://user:secret@localhost:3306")

    with pytest.raises(DatabaseQueryError, match="Schema must be provided"):
        asyncio.run(connection.list_tables())


def test_describe_table_returns_normalized_column_metadata() -> None:
    engine = FakeAsyncEngine(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        {},
        result=FakeResult(
            [
                {
                    "column_name": "id",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "column_default": "nextval('users_id_seq'::regclass)",
                    "ordinal_position": 1,
                    "is_primary_key": True,
                },
                {
                    "column_name": "email",
                    "data_type": "text",
                    "is_nullable": "YES",
                    "column_default": None,
                    "ordinal_position": 2,
                    "is_primary_key": False,
                },
            ]
        ),
    )
    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.describe_table("users"))

    assert result == {
        "backend": "PostgreSQL",
        "schema": "public",
        "table": "users",
        "columns": [
            {
                "name": "id",
                "type": "integer",
                "nullable": False,
                "default": "nextval('users_id_seq'::regclass)",
                "position": 1,
                "primary_key": True,
            },
            {
                "name": "email",
                "type": "text",
                "nullable": True,
                "default": None,
                "position": 2,
                "primary_key": False,
            },
        ],
    }
    assert engine.params == [{"schema": "public", "table": "users"}]


def test_describe_table_requires_table_name() -> None:
    connection = DatabaseConnection("postgresql+asyncpg://user:secret@localhost/app")

    with pytest.raises(DatabaseQueryError, match="Table name"):
        asyncio.run(connection.describe_table(" "))


def test_execute_query_serializes_rows_and_columns() -> None:
    engine = FakeAsyncEngine(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        {},
        result=FakeResult(
            [
                {
                    "id": 1,
                    "created_on": date(2026, 8, 10),
                    "amount": Decimal("10.50"),
                    "payload": b"\x0f",
                }
            ]
        ),
    )
    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.execute_query("select * from orders"))

    assert result == {
        "backend": "PostgreSQL",
        "columns": ["id", "created_on", "amount", "payload"],
        "rows": [
            {
                "id": 1,
                "created_on": "2026-08-10",
                "amount": "10.50",
                "payload": "0f",
            }
        ],
        "row_count": 1,
        "truncated": False,
        "limit": 100,
    }


def test_execute_query_caps_limit_to_configured_max_rows() -> None:
    engine = FakeAsyncEngine(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        {},
        result=FakeResult(
            [
                {"id": 1},
                {"id": 2},
                {"id": 3},
            ]
        ),
    )
    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        max_rows=2,
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.execute_query("select * from users", limit=50))

    assert result["rows"] == [{"id": 1}, {"id": 2}]
    assert result["row_count"] == 2
    assert result["truncated"] is True
    assert result["limit"] == 2
    assert engine.result.mapping_result.fetchmany_calls == [3]


def test_execute_query_preserves_columns_for_empty_results() -> None:
    engine = FakeAsyncEngine(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        {},
        result=FakeResult([], columns=["id", "email"]),
    )
    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.execute_query("select id, email from users"))

    assert result["columns"] == ["id", "email"]
    assert result["rows"] == []
    assert result["row_count"] == 0


def test_execute_query_rejects_mutation_without_creating_engine() -> None:
    engines: list[FakeAsyncEngine] = []

    def engine_factory(url: str, **kwargs: Any) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url, kwargs)
        engines.append(engine)
        return engine

    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=engine_factory,
        statement_factory=lambda sql: sql,
    )

    with pytest.raises(DatabaseQueryError, match="Only read-only"):
        asyncio.run(connection.execute_query("update users set email = 'x'"))

    assert engines == []


def test_execute_query_rejects_multiple_statements() -> None:
    connection = DatabaseConnection("postgresql+asyncpg://user:secret@localhost/app")

    with pytest.raises(DatabaseQueryError, match="Only one SQL statement"):
        asyncio.run(connection.execute_query("select 1; select 2"))


def test_execute_query_rejects_invalid_limit() -> None:
    connection = DatabaseConnection("postgresql+asyncpg://user:secret@localhost/app")

    with pytest.raises(DatabaseQueryError, match="at least 1"):
        asyncio.run(connection.execute_query("select 1", limit=0))


def test_validate_read_only_query_ignores_comments_and_literals() -> None:
    validate_read_only_query(
        """
        -- drop table users
        select 'delete from users' as statement_text
        """
    )


def test_execute_query_error_message_does_not_leak_password() -> None:
    password = "super-secret-password"
    failure = RuntimeError(
        f"Could not query postgresql+asyncpg://user:{password}@localhost/app"
    )

    def engine_factory(url: str, **kwargs: Any) -> FakeAsyncEngine:
        return FakeAsyncEngine(url, kwargs, failure=failure)

    connection = DatabaseConnection(
        f"postgresql+asyncpg://user:{password}@localhost:5432/app",
        engine_factory=engine_factory,
        statement_factory=lambda sql: sql,
    )

    with pytest.raises(DatabaseQueryError) as exc_info:
        asyncio.run(connection.execute_query("select * from users"))

    assert password not in str(exc_info.value)
    assert str(exc_info.value) == (
        "Could not execute query on configured PostgreSQL database."
    )


def test_explain_query_uses_postgresql_json_format() -> None:
    engine = FakeAsyncEngine(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        {},
        result=FakeResult(
            [
                {
                    "QUERY PLAN": [
                        {
                            "Plan": {
                                "Node Type": "Seq Scan",
                                "Relation Name": "users",
                            }
                        }
                    ]
                }
            ]
        ),
    )
    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.explain_query("select * from users"))

    assert result == {
        "backend": "PostgreSQL",
        "columns": ["QUERY PLAN"],
        "plan": [
            {
                "QUERY PLAN": [
                    {
                        "Plan": {
                            "Node Type": "Seq Scan",
                            "Relation Name": "users",
                        }
                    }
                ]
            }
        ],
    }
    assert str(engine.statements[0]).startswith("EXPLAIN (FORMAT JSON)")


def test_explain_query_uses_mysql_explain() -> None:
    engine = FakeAsyncEngine(
        "mysql+asyncmy://user:secret@localhost:3306/app",
        {},
        result=FakeResult(
            [
                {
                    "id": 1,
                    "select_type": "SIMPLE",
                    "table": "users",
                    "type": "ALL",
                }
            ]
        ),
    )
    connection = DatabaseConnection(
        "mysql+asyncmy://user:secret@localhost:3306/app",
        engine_factory=lambda _url, **_kwargs: engine,
        statement_factory=lambda sql: sql,
    )

    result = asyncio.run(connection.explain_query("select * from users"))

    assert result == {
        "backend": "MySQL",
        "columns": ["id", "select_type", "table", "type"],
        "plan": [
            {
                "id": 1,
                "select_type": "SIMPLE",
                "table": "users",
                "type": "ALL",
            }
        ],
    }
    assert str(engine.statements[0]).startswith("EXPLAIN\n")


def test_explain_query_rejects_mutation_without_creating_engine() -> None:
    engines: list[FakeAsyncEngine] = []

    def engine_factory(url: str, **kwargs: Any) -> FakeAsyncEngine:
        engine = FakeAsyncEngine(url, kwargs)
        engines.append(engine)
        return engine

    connection = DatabaseConnection(
        "postgresql+asyncpg://user:secret@localhost:5432/app",
        engine_factory=engine_factory,
        statement_factory=lambda sql: sql,
    )

    with pytest.raises(DatabaseQueryError, match="Only read-only"):
        asyncio.run(connection.explain_query("delete from users"))

    assert engines == []


def test_database_registry_uses_single_database_by_default() -> None:
    created: list[str] = []

    def connection_factory(settings: DatabaseSettings) -> DatabaseConnection:
        created.append(settings.name)
        return DatabaseConnection(
            settings.url,
            query_timeout_seconds=settings.query_timeout_seconds,
            max_rows=settings.max_rows,
            read_only=settings.read_only,
            engine_factory=lambda _url, **_kwargs: FakeAsyncEngine(_url, _kwargs),
            statement_factory=lambda sql: sql,
        )

    registry = DatabaseRegistry.from_settings(
        Settings(
            database_url="postgresql+asyncpg://user:secret@localhost:5432/app",
        ),
        connection_factory=connection_factory,
    )

    assert registry.configured is True
    assert registry.requires_database_name is False
    assert registry.names == ["default"]
    assert registry.get() is registry.get("DEFAULT")
    assert created == ["default"]


def test_database_registry_requires_name_when_multiple_databases_configured() -> None:
    registry = DatabaseRegistry(
        (
            DatabaseSettings(
                name="app",
                url="mysql+asyncmy://user:secret@localhost:3306/app",
            ),
            DatabaseSettings(
                name="warehouse",
                url="postgresql+asyncpg://user:secret@localhost:5432/warehouse",
            ),
        ),
    )

    with pytest.raises(DatabaseConfigurationError, match="database name is required"):
        registry.get()


def test_database_registry_rejects_unknown_database_name() -> None:
    registry = DatabaseRegistry(
        (
            DatabaseSettings(
                name="app",
                url="mysql+asyncmy://user:secret@localhost:3306/app",
            ),
        ),
    )

    with pytest.raises(DatabaseConfigurationError, match="Unknown database"):
        registry.get("warehouse")
