#!/usr/bin/env python3
"""Una línea hex del payload ReadAllSet (bytes 4..24 = 21 B) para diff antes/después."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.dds_scope_helpers import tx_wait_ack
from hantek_usb.protocol import read_all_settings
from hantek_usb.transport import HantekLink


def main() -> int:
    link = HantekLink()
    try:
        rsp = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.2)
    finally:
        link.close()
    if len(rsp) < 25:
        print(f"corto: {rsp.hex()}", file=sys.stderr)
        return 1
    print(rsp[4:25].hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
