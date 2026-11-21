"""Entry point used when freezing nxscript with PyInstaller."""

from nxscript.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
