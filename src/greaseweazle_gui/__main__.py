"""Command-line entry point for the desktop application."""

from __future__ import annotations

import sys

from .application import GreaseweazleApplication


def main() -> int:
    """Run the GTK application."""
    return GreaseweazleApplication().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
