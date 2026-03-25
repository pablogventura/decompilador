#!/usr/bin/env python3
"""
Una lectura **read-settings** + metadatos en **JSON** (diff antes/después desde el panel: Force trigger, menús, etc.).

  python tools/snapshot_scope_state.py -o captures/mi_estado.json

Para comparar dos momentos: ``python tools/compare_scope_snapshots.py a.json b.json``.

Requiere equipo en USB; modo scope recomendado antes de medir (``set-mode osc``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE
from hantek_usb.parse_resp import decode_read_all_set_firmware25
from hantek_usb.protocol import read_all_settings, work_type_packet
from hantek_usb.transport import HantekLink


def _fields_compact(dec: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, meta in dec.get("fields", {}).items():
        if isinstance(meta, dict) and "u8" in meta:
            out[k] = int(meta["u8"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Snapshot read-settings → JSON")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Ruta .json salida")
    ap.add_argument("--bus", type=int, default=None)
    ap.add_argument("--address", type=int, default=None)
    ap.add_argument(
        "--no-work-type",
        action="store_true",
        help="No enviar work-type osciloscopio antes de leer",
    )
    ap.add_argument("--note", default="", help="Texto libre (ej. antes Force trigger)")
    ns = ap.parse_args(argv)

    link = HantekLink(bus=ns.bus, address=ns.address)
    try:
        if not ns.no_work_type:
            link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
            time.sleep(0.05)
        link.write(read_all_settings())
        rsp = link.read64()
    finally:
        link.close()

    if len(rsp) < 25:
        print(f"Respuesta corta: {len(rsp)} B", file=sys.stderr)
        return 1

    dec = decode_read_all_set_firmware25(rsp[:25])
    obj = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "note": ns.note,
        "usb": {"bus": ns.bus, "address": ns.address},
        "response_64_hex": rsp[:64].hex(),
        "settings_25_hex": rsp[:25].hex(),
        "payload_21_hex": rsp[4:25].hex(),
        "firmware25_valid": bool(dec.get("valid_layout")),
        "fields_u8": _fields_compact(dec) if dec.get("valid_layout") else {},
    }
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK → {ns.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
