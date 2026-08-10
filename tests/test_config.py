import pytest

from simple_db_mcp.config import DatabaseSettings, Settings


def test_settings_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.database_url is None
    assert settings.database_configured is False
    assert settings.configured_databases == ()
    assert settings.query_timeout_seconds == 30
    assert settings.max_rows == 100
    assert settings.read_only is True


def test_settings_from_env() -> None:
    settings = Settings.from_env(
        {
            "SIMPLE_DB_MCP_DATABASE_URL": (
                "postgresql+asyncpg://user:password@localhost:5432/app"
            ),
            "SIMPLE_DB_MCP_QUERY_TIMEOUT_SECONDS": "15",
            "SIMPLE_DB_MCP_MAX_ROWS": "250",
            "SIMPLE_DB_MCP_READ_ONLY": "false",
        }
    )

    assert settings.database_configured is True
    assert settings.configured_databases == (
        DatabaseSettings(
            name="default",
            url="postgresql+asyncpg://user:password@localhost:5432/app",
            query_timeout_seconds=15,
            max_rows=250,
            read_only=False,
        ),
    )
    assert settings.query_timeout_seconds == 15
    assert settings.max_rows == 250
    assert settings.read_only is False


def test_public_summary_does_not_include_database_url() -> None:
    settings = Settings.from_env(
        {
            "SIMPLE_DB_MCP_DATABASE_URL": (
                "mysql+asyncmy://user:password@localhost:3306/app"
            ),
        }
    )

    assert settings.public_summary() == {
        "database_configured": True,
        "database_count": 1,
        "database_names": ["default"],
        "requires_database_name": False,
        "query_timeout_seconds": 30,
        "max_rows": 100,
        "read_only": True,
    }


def test_settings_rejects_invalid_integer() -> None:
    with pytest.raises(ValueError, match="SIMPLE_DB_MCP_MAX_ROWS"):
        Settings.from_env({"SIMPLE_DB_MCP_MAX_ROWS": "nope"})


def test_settings_rejects_invalid_boolean() -> None:
    with pytest.raises(ValueError, match="SIMPLE_DB_MCP_READ_ONLY"):
        Settings.from_env({"SIMPLE_DB_MCP_READ_ONLY": "maybe"})


def test_settings_loads_named_databases_from_toml(tmp_path) -> None:
    config_file = tmp_path / "simple-db-mcp.toml"
    config_file.write_text(
        """
        [[databases]]
        name = "warehouse"
        url = "postgresql+asyncpg://user:password@localhost:5432/warehouse"
        query_timeout_seconds = 15
        max_rows = 500
        read_only = true

        [[databases]]
        name = "app"
        url = "mysql+asyncmy://user:password@localhost:3306/app"
        max_rows = 50
        read_only = false
        """,
        encoding="utf-8",
    )

    settings = Settings.from_toml(config_file)

    assert settings.database_configured is True
    assert settings.configured_databases == (
        DatabaseSettings(
            name="warehouse",
            url="postgresql+asyncpg://user:password@localhost:5432/warehouse",
            query_timeout_seconds=15,
            max_rows=500,
            read_only=True,
        ),
        DatabaseSettings(
            name="app",
            url="mysql+asyncmy://user:password@localhost:3306/app",
            query_timeout_seconds=30,
            max_rows=50,
            read_only=False,
        ),
    )
    assert settings.public_summary() == {
        "database_configured": True,
        "database_count": 2,
        "database_names": ["warehouse", "app"],
        "requires_database_name": True,
        "databases": [
            {
                "name": "warehouse",
                "query_timeout_seconds": 15,
                "max_rows": 500,
                "read_only": True,
            },
            {
                "name": "app",
                "query_timeout_seconds": 30,
                "max_rows": 50,
                "read_only": False,
            },
        ],
    }


def test_settings_loads_config_file_from_env(tmp_path) -> None:
    config_file = tmp_path / "simple-db-mcp.toml"
    config_file.write_text(
        """
        [[databases]]
        name = "app"
        url = "mysql+asyncmy://user:password@localhost:3306/app"
        """,
        encoding="utf-8",
    )

    settings = Settings.from_env(
        {
            "SIMPLE_DB_MCP_CONFIG_FILE": str(config_file),
        }
    )

    assert [database.name for database in settings.configured_databases] == ["app"]


def test_settings_rejects_duplicate_database_names(tmp_path) -> None:
    config_file = tmp_path / "simple-db-mcp.toml"
    config_file.write_text(
        """
        [[databases]]
        name = "app"
        url = "mysql+asyncmy://user:password@localhost:3306/app"

        [[databases]]
        name = "APP"
        url = "postgresql+asyncpg://user:password@localhost:5432/app"
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        Settings.from_toml(config_file)


def test_settings_rejects_invalid_toml_database_entry(tmp_path) -> None:
    config_file = tmp_path / "simple-db-mcp.toml"
    config_file.write_text(
        """
        [[databases]]
        name = "app"
        max_rows = 0
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="url"):
        Settings.from_toml(config_file)
