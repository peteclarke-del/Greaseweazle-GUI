"""Private entry point for the bundled Greaseweazle host tools."""

import sys

from greaseweazle.cli import main


if __name__ == "__main__":
    sys.argv[0] = "gw"
    raise SystemExit(main())
