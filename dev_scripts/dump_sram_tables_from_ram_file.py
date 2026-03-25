#!/usr/bin/env python3
"""
Interpreta un volcado binario de SRAM que empiece en 0x20000000 (p. ej. desde ST-Link)
y muestra las entradas de las tablas usadas por la pool del firmware Hantek.

Offsets fijos respecto a 0x20000000:
  - 0x01BFC / 0x01B74 : uint32[] A / B
  - 0x01CA8 / 0x01C84 : bytes[] A / B

Uso:
  python3 dev_scripts/dump_sram_tables_from_ram_file.py captura_sram.bin
  python3 dev_scripts/dump_sram_tables_from_ram_file.py captura_sram.bin --count 8
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ram_bin", type=Path, help="Volcado binario SRAM desde 0x20000000")
    ap.add_argument("--count", type=int, default=8, help="Entradas por tabla uint32")
    args = ap.parse_args()
    data = args.ram_bin.read_bytes()
    if len(data) < 0x1D00:
        print(f"aviso: solo {len(data)} bytes; hacen falta al menos ~0x1d00", file=sys.stderr)

    tables = [
        (0x1BFC, "uint32[] @0x20001BFC (rama A / fee4)", "I"),
        (0x1B74, "uint32[] @0x20001B74 (rama B / fee8)", "I"),
        (0x1CA8, "bytes[] @0x20001CA8 (fed8)", "B"),
        (0x1C84, "bytes[] @0x20001C84 (fedc)", "B"),
    ]

    for off, label, mode in tables:
        print(f"\n=== {label} (off 0x{off:x}) ===")
        if off >= len(data):
            print("  (fuera del archivo)")
            continue
        if mode == "I":
            for i in range(args.count):
                p = off + i * 4
                if p + 4 > len(data):
                    break
                w = struct.unpack_from("<I", data, p)[0]
                print(f"  [{i}] 0x{w:08x}  ({w})")
        else:
            row = data[off : off + args.count]
            for i, b in enumerate(row):
                print(f"  [{i}] 0x{b:02x}  ({b})")


if __name__ == "__main__":
    main()
