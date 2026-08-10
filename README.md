# simple-db-mcp

A small Python MCP server for querying relational databases from MCP-compatible
clients. The server will be built with [FastMCP](https://github.com/PrefectHQ/fastmcp)
and will initially support PostgreSQL and MySQL.

## Status

Phase 1 is implemented. The project now has a Python package skeleton, a
FastMCP server entry point, environment-based settings, basic health/version
tools, and initial tests.

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

## Planned MCP Tools

The database-focused version should expose a small, predictable tool surface:

| Tool | Purpose |
| --- | --- |
| `ping_database` | Verify that the configured database connection works. |
| `list_schemas` | List available schemas or databases, depending on backend. |
| `list_tables` | List tables and views for a schema. |
| `describe_table` | Return columns, types, nullability, defaults, and key metadata. |
| `execute_query` | Run a read-only SQL query and return rows with a configurable limit. |
| `explain_query` | Return the database query plan for a read-only query. |

Later versions can add optional write tools behind explicit configuration.

Current Phase 1 tools:

| Tool | Purpose |
| --- | --- |
| `health` | Return server health and non-sensitive configuration. |
| `version` | Return the server name and package version. |

## Database Support

The project should use SQLAlchemy as the database abstraction layer while keeping
backend-specific behavior isolated where needed.

Planned drivers:

- PostgreSQL: `asyncpg`
- MySQL: `asyncmy`

Example connection URLs:

```text
postgresql+asyncpg://user:password@localhost:5432/app
mysql+asyncmy://user:password@localhost:3306/app
```

## Configuration

The MVP can start with environment variables:

```bash
SIMPLE_DB_MCP_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/app
SIMPLE_DB_MCP_QUERY_TIMEOUT_SECONDS=30
SIMPLE_DB_MCP_MAX_ROWS=100
SIMPLE_DB_MCP_READ_ONLY=true
```

The current health tool reports whether a database URL is configured, but it
does not expose the URL or credentials.

Planned follow-up configuration can support multiple named connections:

```toml
[[databases]]
name = "warehouse"
url = "postgresql+asyncpg://user:password@localhost:5432/warehouse"
read_only = true
max_rows = 500

[[databases]]
name = "app"
url = "mysql+asyncmy://user:password@localhost:3306/app"
read_only = true
max_rows = 100
```

## Expected Usage

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
uv run simple-db-mcp
```

Run through the FastMCP CLI:

```bash
uv run fastmcp run src/simple_db_mcp/server.py --project .
```

For HTTP deployments, the server can later expose FastMCP's streamable HTTP
transport:

```bash
uv run simple-db-mcp --transport http --host 127.0.0.1 --port 8000
```

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
- Document that users should create least-privilege database accounts for this
  server.

The initial SQL safety checks do not need to be perfect SQL parsers, but the
server should rely on database permissions as the final safety boundary.

## Development Plan

### Phase 1: Project Skeleton

- Create a Python package under `src/simple_db_mcp`.
- Add `pyproject.toml` with runtime and development dependencies.
- Add a FastMCP server entry point.
- Add settings loading from environment variables.
- Add formatting, linting, and test tooling.

Acceptance criteria:

- `uv run simple-db-mcp` starts an MCP server.
- Unit tests can run with `uv run pytest`.
- The server exposes at least a health or version tool.

### Phase 2: Database Connection Layer

- Add SQLAlchemy async engine creation.
- Validate PostgreSQL and MySQL connection URLs.
- Add connection lifecycle management.
- Implement `ping_database`.
- Add tests with mocked engines or lightweight integration fixtures.

Acceptance criteria:

- The server can connect to PostgreSQL and MySQL URLs.
- Failed connections return useful MCP errors without leaking credentials.

### Phase 3: Schema Introspection

- Implement `list_schemas`.
- Implement `list_tables`.
- Implement `describe_table`.
- Normalize metadata responses across PostgreSQL and MySQL.
- Add tests for metadata formatting.

Acceptance criteria:

- A client can inspect available schemas, tables, and columns without writing
  custom SQL.

### Phase 4: Read-only Query Execution

- Implement `execute_query`.
- Enforce timeout and max-row settings.
- Add read-only statement checks.
- Normalize result rows into JSON-serializable values.
- Add clear errors for unsupported or unsafe queries.

Acceptance criteria:

- A client can run read-only queries against PostgreSQL and MySQL.
- Query results are capped and serializable.
- Mutation attempts are rejected in application logic and should also fail with
  read-only database credentials.

### Phase 5: Query Plans

- Implement `explain_query`.
- Use backend-specific `EXPLAIN` syntax where needed.
- Keep output structured but close to the database's native plan.

Acceptance criteria:

- A client can request a plan for a read-only query on both supported backends.

### Phase 6: Multi-connection Configuration

- Add optional TOML configuration.
- Support named database connections.
- Require a `database` argument for tools when multiple connections are present.
- Keep single-connection environment-variable setup simple.

Acceptance criteria:

- One server process can expose multiple named PostgreSQL and MySQL databases.

### Phase 7: Documentation and Packaging

- Document setup, configuration, MCP client examples, and safety guidance.
- Add example database users with read-only grants.
- Add release workflow notes.
- Add a small example config file.

Acceptance criteria:

- A new user can install, configure, and run the server from the README alone.

## Dependencies

Runtime:

- `fastmcp`
- `sqlalchemy`
- `asyncpg`
- `asyncmy`

Development:

- `pytest`
- `pytest-asyncio`
- `ruff`
- `mypy`

## License

TBD.
