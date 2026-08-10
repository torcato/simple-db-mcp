from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Callable

from simple_db_mcp import __version__
from simple_db_mcp.config import Settings


class FakeFastMCP:
    def __init__(self, *, name: str) -> None:
        self.name = name
        self.tools: dict[str, Callable[[], dict[str, object]]] = {}

    def tool(
        self,
        func: Callable[[], dict[str, object]],
    ) -> Callable[[], dict[str, object]]:
        self.tools[func.__name__] = func
        return func


def test_create_server_registers_phase_one_tools(monkeypatch) -> None:
    fake_fastmcp = ModuleType("fastmcp")
    fake_fastmcp.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "fastmcp", fake_fastmcp)
    sys.modules.pop("simple_db_mcp.server", None)

    server_module = importlib.import_module("simple_db_mcp.server")
    settings = Settings(
        database_url=None,
        query_timeout_seconds=20,
        max_rows=50,
        read_only=True,
    )

    server = server_module.create_server(settings)

    assert server.name == "simple-db-mcp"
    assert set(server.tools) == {"health", "version"}
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
