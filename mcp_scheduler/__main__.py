"""Allow running with ``python -m mcp_scheduler``."""

from mcp_scheduler.server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
