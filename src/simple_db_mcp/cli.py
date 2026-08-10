from __future__ import annotations

import argparse
from collections.abc import Sequence

from simple_db_mcp import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simple-db-mcp",
        description="Run the simple database MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http", "sse"),
        default="stdio",
        help="FastMCP transport to use.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP or SSE transports.",
    )
    parser.add_argument(
        "--port",
        default=8000,
        type=int,
        help="Port for HTTP or SSE transports.",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="Path for the streamable HTTP transport.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"simple-db-mcp {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from simple_db_mcp.server import create_server

    mcp = create_server()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    if args.transport == "http":
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            path=args.path,
        )
        return 0

    mcp.run(transport="sse", host=args.host, port=args.port)
    return 0
