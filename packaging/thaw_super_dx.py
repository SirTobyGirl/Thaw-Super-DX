"""Entry point for the packaged executable: same as `python -m thaw_sandbox` (no command = the window)."""
import sys

from thaw_sandbox.cli import main

if __name__ == "__main__":
    sys.exit(main())
