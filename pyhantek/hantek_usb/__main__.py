"""Permite: python -m hantek_usb (equivalente al CLI)."""

from __future__ import annotations

import sys

from hantek_usb.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
