"""`python3 -m stackshot ...` and `uv run stackshot ...`: the command line of the package (stackshot/cli.py)."""
import sys

from stackshot.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
