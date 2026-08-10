from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

from simple_db_mcp import __version__
from simple_db_mcp.config import Settings


class FakeFastMCP:
    def __init__(self, *, name: str) -> None:
        self.name = name
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(
        self,
        func: Callable[..., Any],
    ) -> Callable[..., Any]:
        self.tools[func.__name__] = func
        return func


def import_server_with_fake_fastmcp(monkeypatch):
    for key in (
        "SIMPLE_DB_MCP_CONFIG_FILE",
        "SIMPLE_DB_MCP_DATABASE_URL",
        "SIMPLE_DB_MCP_QUERY_TIMEOUT_SECONDS",
        "SIMPLE_DB_MCP_MAX_ROWS",
        "SIMPLE_DB_MCP_READ_ONLY",
    ):
        monkeypatch.delenv(key, raising=False)

    fake_fastmcp = ModuleType("fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "fastmcp", fake_fastmcp)
    sys.modules.pop("simple_db_mcp.server", None)

    return importlib.import_module("simple_db_mcp.server")


def test_create_server_registers_core_tools(monkeypatch) -> None:
    server_module = import_server_with_fake_fastmcp(monkeypatch)
    settings = Settings(
        database_url=None,
        query_timeout_seconds=20,
        max_rows=50,
        read_only=True,
    )

    server = server_module.create_server(settings)

    assert server.name == "simple-db-mcp"
    assert set(server.tools) == {
        "describe_table",
        "execute_query",
        "explain_query",
        "health",
        "list_schemas",
        "list_tables",
        "ping_database",
        "version",
    }
    assert server.tools["version"]() == {
        "server": "simple-db-mcp",
        "version": __version__,
    }
    assert server.tools["health"]() == {
        "status": "ok",
        "server": "simple-db-mcp",
        "version": __version__,
        "database_configured": False,
        "database_count": 0,
        "database_names": [],
        "requires_database_name": False,
        "query_timeout_seconds": 20,
        "max_rows": 50,
        "read_only": True,
    }


def test_database_tools_report_missing_configuration(monkeypatch) -> None:
    server_module = import_server_with_fake_fastmcp(monkeypatch)
    server = server_module.create_server(Settings(database_url=None))
    expected = {
        "status": "not_configured",
        "database_configured": False,
    }

    assert asyncio.run(server.tools["ping_database"]()) == expected
    assert asyncio.run(server.tools["list_schemas"]()) == expected
    assert asyncio.run(server.tools["list_tables"]()) == expected
    assert asyncio.run(server.tools["describe_table"]("users")) == expected
    assert asyncio.run(server.tools["execute_query"]("select 1")) == expected
    assert asyncio.run(server.tools["explain_query"]("select 1")) == expected


def test_database_tools_use_configured_connection(monkeypatch) -> None:
    server_module = import_server_with_fake_fastmcp(monkeypatch)

    class FakeDatabaseConnection:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        @classmethod
        def from_settings(
            cls,
            settings: Settings,
        ) -> FakeDatabaseConnection:
            return cls(settings)

        async def ping(self) -> dict[str, object]:
            assert self.settings.database_url is not None
            return {"status": "ok", "backend": "PostgreSQL"}

        async def list_schemas(self) -> dict[str, object]:
            return {"schemas": ["public"]}

        async def list_tables(self, schema: str | None = None) -> dict[str, object]:
            return {"schema": schema or "public", "tables": []}

        async def describe_table(
            self,
            table: str,
            schema: str | None = None,
        ) -> dict[str, object]:
            return {"schema": schema or "public", "table": table, "columns": []}

        async def execute_query(
            self,
            sql: str,
            limit: int | None = None,
        ) -> dict[str, object]:
            return {"sql": sql, "limit": limit, "rows": []}

        async def explain_query(self, sql: str) -> dict[str, object]:
            return {"sql": sql, "plan": []}

    class FakeDatabaseRegistry:
        requested_databases: list[str | None] = []

        def __init__(self, connection: FakeDatabaseConnection) -> None:
            self.connection = connection

        @classmethod
        def from_settings(
            cls,
            settings: Settings,
        ) -> FakeDatabaseRegistry:
            return cls(FakeDatabaseConnection(settings))

        def get(
            self,
            database: str | None = None,
        ) -> FakeDatabaseConnection | None:
            self.requested_databases.append(database)
            return self.connection

    monkeypatch.setattr(
        server_module,
        "DatabaseRegistry",
        FakeDatabaseRegistry,
    )
    server = server_module.create_server(
        Settings(
            database_url="postgresql+asyncpg://user:secret@localhost:5432/app",
        )
    )

    result = asyncio.run(server.tools["ping_database"]())

    assert result == {"status": "ok", "backend": "PostgreSQL"}
    assert asyncio.run(server.tools["list_schemas"]()) == {"schemas": ["public"]}
    assert asyncio.run(server.tools["list_tables"]("analytics")) == {
        "schema": "analytics",
        "tables": [],
    }
    assert asyncio.run(server.tools["describe_table"]("users", "public")) == {
        "schema": "public",
        "table": "users",
        "columns": [],
    }
    assert asyncio.run(server.tools["execute_query"]("select 1", 10)) == {
        "sql": "select 1",
        "limit": 10,
        "rows": [],
    }
    assert asyncio.run(server.tools["explain_query"]("select 1", "warehouse")) == {
        "sql": "select 1",
        "plan": [],
    }
    assert FakeDatabaseRegistry.requested_databases == [
        None,
        None,
        None,
        None,
        None,
        "warehouse",
    ]


def test_importing_server_requires_fastmcp(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "fastmcp", None)
    sys.modules.pop("simple_db_mcp.server", None)

    try:
        importlib.import_module("simple_db_mcp.server")
    except RuntimeError as exc:
        assert "FastMCP is not installed" in str(exc)
    else:
        raise AssertionError("Expected missing FastMCP to raise RuntimeError.")


def test_import_server_with_fake_fastmcp_registers_module_mcp(monkeypatch) -> None:
    server_module = import_server_with_fake_fastmcp(monkeypatch)

    assert server_module.mcp.name == "simple-db-mcp"
