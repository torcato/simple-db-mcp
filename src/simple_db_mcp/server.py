from __future__ import annotations

from typing import Any

from simple_db_mcp import __version__
from simple_db_mcp.config import Settings
from simple_db_mcp.database import DatabaseConnection, DatabaseRegistry

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
    registry = DatabaseRegistry.from_settings(active_settings)
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
    async def ping_database(database: str | None = None) -> dict[str, object]:
        """Verify that the configured database connection works."""
        connection = _select_database(registry, database)
        if connection is None:
            return _not_configured()

        return await connection.ping()

    @mcp.tool
    async def list_schemas(database: str | None = None) -> dict[str, object]:
        """List available database schemas."""
        connection = _select_database(registry, database)
        if connection is None:
            return _not_configured()

        return await connection.list_schemas()

    @mcp.tool
    async def list_tables(
        schema: str | None = None,
        database: str | None = None,
    ) -> dict[str, object]:
        """List tables and views in a schema."""
        connection = _select_database(registry, database)
        if connection is None:
            return _not_configured()

        return await connection.list_tables(schema)

    @mcp.tool
    async def describe_table(
        table: str,
        schema: str | None = None,
        database: str | None = None,
    ) -> dict[str, object]:
        """Describe columns and primary key metadata for a table."""
        connection = _select_database(registry, database)
        if connection is None:
            return _not_configured()

        return await connection.describe_table(table, schema)

    @mcp.tool
    async def execute_query(
        sql: str,
        limit: int | None = None,
        database: str | None = None,
    ) -> dict[str, object]:
        """Execute a read-only SQL query with a configured row limit."""
        connection = _select_database(registry, database)
        if connection is None:
            return _not_configured()

        return await connection.execute_query(sql, limit)

    @mcp.tool
    async def explain_query(
        sql: str,
        database: str | None = None,
    ) -> dict[str, object]:
        """Return the database query plan for a read-only SQL query."""
        connection = _select_database(registry, database)
        if connection is None:
            return _not_configured()

        return await connection.explain_query(sql)

    return mcp


def _select_database(
    registry: DatabaseRegistry,
    database: str | None,
) -> DatabaseConnection | None:
    return registry.get(database)


def _not_configured() -> dict[str, object]:
    return {
        "status": "not_configured",
        "database_configured": False,
    }


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
