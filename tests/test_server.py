from __future__ import annotations

import asyncio
import importlib
import sys
from types import ModuleType
from typing import Any, Callable

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
    monkeypatch.delenv("SIMPLE_DB_MCP_DATABASE_URL", raising=False)
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
    assert set(server.tools) == {"health", "ping_database", "version"}
    assert server.tools["version"]() == {
        "server": "simple-db-mcp",
        "version": __version__,
    }
    assert server.tools["health"]() == {
        "status": "ok",
        "server": "simple-db-mcp",
        "version": __version__,
        "database_configured": False,
        "query_timeout_seconds": 20,
        "max_rows": 50,
        "read_only": True,
    }


def test_ping_database_reports_missing_configuration(monkeypatch) -> None:
    server_module = import_server_with_fake_fastmcp(monkeypatch)
    server = server_module.create_server(Settings(database_url=None))

    result = asyncio.run(server.tools["ping_database"]())

    assert result == {
        "status": "not_configured",
        "database_configured": False,
    }


def test_ping_database_uses_configured_connection(monkeypatch) -> None:
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

    monkeypatch.setattr(
        server_module,
        "DatabaseConnection",
        FakeDatabaseConnection,
    )
    server = server_module.create_server(
        Settings(
            database_url="postgresql+asyncpg://user:secret@localhost:5432/app",
        )
    )

    result = asyncio.run(server.tools["ping_database"]())

    assert result == {"status": "ok", "backend": "PostgreSQL"}


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
