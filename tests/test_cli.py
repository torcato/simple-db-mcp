from simple_db_mcp import __version__
from simple_db_mcp.cli import build_parser


def test_parser_defaults_to_stdio() -> None:
    args = build_parser().parse_args([])

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.path == "/mcp"


def test_parser_reports_version(capsys) -> None:
    parser = build_parser()

    try:
        parser.parse_args(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    assert f"simple-db-mcp {__version__}" in capsys.readouterr().out
