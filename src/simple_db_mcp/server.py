from __future__ import annotations

from typing import Any

from simple_db_mcp import __version__
from simple_db_mcp.config import Settings
from simple_db_mcp.database import DatabaseConnection, DatabaseConnectionError


SERVER_NAME = "simple-db-mcp"


def create_server(settings: Settings | None = None) -> Any:
    try:
        from fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        if exc.name != "fastmcp":
            raise

        raise RuntimeError(
            "FastMCP is not installed. Install project dependencies before "
            "starting the server."
        ) from exc

    active_settings = settings or Settings.from_env()
    database = (
        DatabaseConnection.from_settings(active_settings)
        if active_settings.database_configured
        else None
    )
    mcp = FastMCP(name=SERVER_NAME)

    @mcp.tool
    def health() -> dict[str, object]:
        """Return basic server health and non-sensitive configuration."""
        return {
            "status": "ok",
            "server": SERVER_NAME,
            "version": __version__,
            **active_settings.public_summary(),
        }

    @mcp.tool
    def version() -> dict[str, str]:
        """Return the server name and version."""
        return {
            "server": SERVER_NAME,
            "version": __version__,
        }

    @mcp.tool
    async def ping_database() -> dict[str, object]:
        """Verify that the configured database connection works."""
        if database is None:
            return {
                "status": "not_configured",
                "database_configured": False,
            }

        try:
            return await database.ping()
        except DatabaseConnectionError:
            raise

    return mcp


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
