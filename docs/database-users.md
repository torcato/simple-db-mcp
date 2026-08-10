# Read-only Database Users

Use a dedicated, least-privilege database account for this MCP server. The
application rejects obvious mutation statements in read-only mode, but database
permissions should be the final safety boundary.

Replace usernames, passwords, database names, schema names, and host rules before
running these examples.

## PostgreSQL

```sql
CREATE ROLE simple_db_mcp WITH LOGIN PASSWORD 'change-me';

GRANT CONNECT ON DATABASE app TO simple_db_mcp;

\connect app

GRANT USAGE ON SCHEMA public TO simple_db_mcp;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO simple_db_mcp;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO simple_db_mcp;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO simple_db_mcp;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON SEQUENCES TO simple_db_mcp;
```

Connection URL:

```text
postgresql+asyncpg://simple_db_mcp:change-me@localhost:5432/app
```

For additional schemas, repeat the `GRANT USAGE`, `GRANT SELECT`, and
`ALTER DEFAULT PRIVILEGES` statements for each schema.

## MySQL

```sql
CREATE USER 'simple_db_mcp'@'%' IDENTIFIED BY 'change-me';

GRANT SELECT, SHOW VIEW ON app.* TO 'simple_db_mcp'@'%';

FLUSH PRIVILEGES;
```

Connection URL:

```text
mysql+asyncmy://simple_db_mcp:change-me@localhost:3306/app
```

Prefer a narrower host rule than `'%'` when the server location is known.
