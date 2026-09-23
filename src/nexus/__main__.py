"""Nexus CLI entrypoint for `python -m nexus`."""

import sys


def main() -> None:
    """Entry point for executing nexus as a module."""
    try:
        from nexus.cli.main import main as cli_main

        cli_main()
    except ImportError:
        print("Nexus CLI is not yet initialized.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
