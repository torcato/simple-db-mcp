import pytest

from simple_db_mcp.config import Settings


def test_settings_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.database_url is None
    assert settings.database_configured is False
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
