"""Command-line entry point for the HK Quant Research Platform."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Print a short status banner confirming the package works.

    Args:
        argv: Command-line arguments (reserved for future subcommands).

    Returns:
        Exit code (``0`` on success).
    """
    if argv is None:
        argv = sys.argv[1:]
    # Future subcommands (data, research, backtest, ...) will be dispatched here.
    if argv:
        print(f"Unknown command(s): {' '.join(argv)}", file=sys.stderr)
        return 2

    print("HK Quant Research Platform")
    print("Status: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
