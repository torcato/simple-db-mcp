# simple-db-mcp

A small Python MCP server for querying relational databases from MCP-compatible
clients. The server is built with
[FastMCP](https://github.com/PrefectHQ/fastmcp) and supports PostgreSQL and
MySQL.

## Goals

- Provide a simple MCP interface for common database inspection and query tasks.
- Support PostgreSQL and MySQL from the first working version.
- Keep database access safe by default, with read-only query execution as the
  default operating mode.
- Use clear configuration so the server can run locally through stdio or be
  deployed later over HTTP.
- Keep the codebase small, typed, tested, and easy to extend.

## Non-goals

- Replacing a database admin tool.
- Providing migrations, backups, replication, or schema editing in the MVP.
- Exposing unrestricted write access by default.
- Implementing database-specific SQL parsing from scratch.

## Tool Overview

The server exposes a small, predictable MCP tool surface:

| Tool | Purpose |
| --- | --- |
| `health` | Return server health and non-sensitive configuration. |
| `ping_database` | Verify that the configured database connection works. |
| `list_schemas` | List available schemas or databases, depending on backend. |
| `list_tables` | List tables and views for a schema. |
| `describe_table` | Return columns, types, nullability, defaults, and key metadata. |
| `execute_query` | Run a read-only SQL query with a row limit. |
| `explain_query` | Return the database query plan for a read-only query. |
| `version` | Return the server name and package version. |

## Database Support

The project should use SQLAlchemy as the database abstraction layer while keeping
backend-specific behavior isolated where needed.

Planned drivers:

- PostgreSQL: `asyncpg`
- MySQL: `asyncmy`

The current connection layer validates SQLAlchemy async URLs that use
`postgresql+asyncpg` or `mysql+asyncmy`, creates async engines lazily, and
disposes them through an explicit async close method.

Current introspection defaults:

- PostgreSQL table tools default to the `public` schema.
- MySQL table tools default to the database name in the connection URL.
- A schema can be supplied explicitly for table listing and table description.
- When multiple databases are configured, database tools require the
  `database` argument.

Example connection URLs:

```text
postgresql+asyncpg://user:password@localhost:5432/app
mysql+asyncmy://user:password@localhost:3306/app
```

## Quick Start

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

Show CLI options:

```bash
uv run simple-db-mcp --help
```

Start the server with the default stdio transport:

```bash
SIMPLE_DB_MCP_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/app \
  uv run simple-db-mcp
```

Run through the FastMCP CLI:

```bash
uv run fastmcp run src/simple_db_mcp/server.py --project .
```

For HTTP deployments, use FastMCP's streamable HTTP transport:

```bash
uv run simple-db-mcp --transport http --host 127.0.0.1 --port 8000
```

## Configuration

For one database, use environment variables:

```bash
SIMPLE_DB_MCP_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/app
SIMPLE_DB_MCP_QUERY_TIMEOUT_SECONDS=30
SIMPLE_DB_MCP_MAX_ROWS=100
SIMPLE_DB_MCP_READ_ONLY=true
```

The current health tool reports whether a database URL is configured, but it
does not expose the URL or credentials.

`execute_query` uses `SIMPLE_DB_MCP_MAX_ROWS` as a hard cap. Tool callers may
request a lower limit, but not a higher effective limit.

For multiple named connections, use a TOML file:

```toml
[[databases]]
name = "warehouse"
url = "postgresql+asyncpg://user:password@localhost:5432/warehouse"
query_timeout_seconds = 30
read_only = true
max_rows = 500

[[databases]]
name = "app"
url = "mysql+asyncmy://user:password@localhost:3306/app"
query_timeout_seconds = 30
read_only = true
max_rows = 100
```

Then point the server at it:

```bash
SIMPLE_DB_MCP_CONFIG_FILE=examples/simple-db-mcp.toml uv run simple-db-mcp
```

See [examples/simple-db-mcp.toml](examples/simple-db-mcp.toml).

With a single configured database, tool calls do not need a `database` argument.
With multiple configured databases, pass the connection name:

```json
{
  "database": "warehouse",
  "sql": "select * from orders limit 10"
}
```

## MCP Client Configuration

For stdio-based MCP clients, point the client at `uv` and run this package from
the repository directory. Use an absolute path for `--directory`:

```json
{
  "mcpServers": {
    "simple-db-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/simple-db-mcp",
        "run",
        "simple-db-mcp"
      ],
      "env": {
        "SIMPLE_DB_MCP_DATABASE_URL": "postgresql+asyncpg://user:pass@host/db",
        "SIMPLE_DB_MCP_READ_ONLY": "true",
        "SIMPLE_DB_MCP_MAX_ROWS": "100"
      }
    }
  }
}
```

For multiple databases, use `SIMPLE_DB_MCP_CONFIG_FILE` instead of
`SIMPLE_DB_MCP_DATABASE_URL`:

```json
{
  "mcpServers": {
    "simple-db-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/simple-db-mcp",
        "run",
        "simple-db-mcp"
      ],
      "env": {
        "SIMPLE_DB_MCP_CONFIG_FILE": "/path/to/simple-db-mcp.toml"
      }
    }
  }
}
```

See [examples/mcp-client.json](examples/mcp-client.json).

## Tool Reference

All database tools accept an optional `database` argument. It is only required
when multiple named connections are configured.

- `ping_database(database = null)`
- `list_schemas(database = null)`
- `list_tables(schema = null, database = null)`
- `describe_table(table, schema = null, database = null)`
- `execute_query(sql, limit = null, database = null)`
- `explain_query(sql, database = null)`

## Development

Useful local commands:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
uv build
```

The phased development plan lives in
[docs/development-plan.md](docs/development-plan.md).

## Safety Model

Database MCP servers can expose sensitive data, so the default behavior should
be conservative:

- Read-only mode enabled by default.
- Reject obvious mutation statements in `execute_query`.
- Apply a row limit even if the query omits `LIMIT`.
- Enforce query timeout settings.
- Avoid logging credentials.
- Return concise error messages to clients while keeping debug details in local
  logs.
- Avoid returning raw database URLs or driver exception messages from
  connection failures.
- Document that users should create least-privilege database accounts for this
  server.

The initial SQL safety checks do not need to be perfect SQL parsers, but the
server should rely on database permissions as the final safety boundary.
The current application check allows obvious read-only statements such as
`SELECT`, `WITH`, `SHOW`, `DESCRIBE`, and `DESC`, rejects multiple statements,
and blocks common mutation/control keywords before the query is sent.
`explain_query` applies the same read-only checks before wrapping the query in
backend-specific `EXPLAIN` syntax.

See [docs/database-users.md](docs/database-users.md) for read-only PostgreSQL
and MySQL grant examples.

## Packaging

Packaging uses Hatchling through `pyproject.toml`.

Build local distributions:

```bash
uv build
```

Release checklist and versioning notes live in
[docs/releasing.md](docs/releasing.md).

## Dependencies

Runtime:

- `fastmcp`
- `sqlalchemy`
- `asyncpg`
- `asyncmy`
- `tomli` on Python 3.10

Development:

- `pytest`
- `pytest-asyncio`
- `ruff`
- `mypy`

## License

TBD.
