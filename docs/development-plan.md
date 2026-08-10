# Development Plan

## Status

Phase 7 is implemented. The project now has a Python package skeleton, a
FastMCP server entry point, environment-based settings, basic health/version
tools, an async SQLAlchemy connection layer, schema introspection tools,
read-only query execution, query plans, single-connection env config,
multi-connection TOML config, docs, examples, and tests.

## Phases

### Phase 1: Project Skeleton - implemented

- Create a Python package under `src/simple_db_mcp`.
- Add `pyproject.toml` with runtime and development dependencies.
- Add a FastMCP server entry point.
- Add settings loading from environment variables.
- Add formatting, linting, and test tooling.

Acceptance criteria:

- `uv run simple-db-mcp` starts an MCP server.
- Unit tests can run with `uv run pytest`.
- The server exposes at least a health or version tool.

### Phase 2: Database Connection Layer - implemented

- Add SQLAlchemy async engine creation.
- Validate PostgreSQL and MySQL connection URLs.
- Add connection lifecycle management.
- Implement `ping_database`.
- Add tests with mocked engines or lightweight integration fixtures.

Acceptance criteria:

- The server can connect to PostgreSQL and MySQL URLs.
- Failed connections return useful MCP errors without leaking credentials.

### Phase 3: Schema Introspection - implemented

- Implement `list_schemas`.
- Implement `list_tables`.
- Implement `describe_table`.
- Normalize metadata responses across PostgreSQL and MySQL.
- Add tests for metadata formatting.

Acceptance criteria:

- A client can inspect available schemas, tables, and columns without writing
  custom SQL.

### Phase 4: Read-only Query Execution - implemented

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

### Phase 5: Query Plans - implemented

- Implement `explain_query`.
- Use backend-specific `EXPLAIN` syntax where needed.
- Keep output structured but close to the database's native plan.

Acceptance criteria:

- A client can request a plan for a read-only query on both supported backends.

### Phase 6: Multi-connection Configuration - implemented

- Add optional TOML configuration.
- Support named database connections.
- Require a `database` argument for tools when multiple connections are present.
- Keep single-connection environment-variable setup simple.

Acceptance criteria:

- One server process can expose multiple named PostgreSQL and MySQL databases.

### Phase 7: Documentation and Packaging - implemented

- Document setup, configuration, MCP client examples, and safety guidance.
- Add example database users with read-only grants.
- Add release workflow notes.
- Add a small example config file.

Acceptance criteria:

- A new user can install, configure, and run the server from the README alone.
