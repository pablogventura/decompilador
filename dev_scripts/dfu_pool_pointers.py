#!/usr/bin/env python3
"""
Extrae el primer payload DfuSe (misma lógica que dev_scripts/decompile_firmware.sh)
y lista punteros ROM → RAM en la constant pool usada por FUN_0800fd64 / FUN_0800fe80.

Uso:
  python3 dev_scripts/dfu_pool_pointers.py
  python3 dev_scripts/dfu_pool_pointers.py /ruta/al/archivo.dfu
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def extract_dfu_payload(dfu: Path) -> tuple[int, bytes, int]:
    """Devuelve (base_addr, payload, offset_del_payload_en_el_archivo)."""
    b = dfu.read_bytes()
    if len(b) < 11 or b[:5] != b"DfuSe":
        raise SystemExit("DFU inválido o no DfuSe")
    o = 11
    if len(b) < o + 274:
        raise SystemExit("DFU truncado (target)")
    o += 274
    if len(b) < o + 8:
        raise SystemExit("DFU truncado (element)")
    addr, esize = struct.unpack_from("<II", b, o)
    o += 8
    if len(b) < o + esize:
        raise SystemExit("DFU truncado (payload)")
    return addr, b[o : o + esize], o


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Punteros ROM→RAM en pool del firmware DfuSe")
    ap.add_argument(
        "dfu",
        nargs="?",
        default=str(root / "firmware" / "HantekHTX2021090901.dfu"),
        type=Path,
        help="Archivo .dfu (por defecto firmware/HantekHTX2021090901.dfu)",
    )
    args = ap.parse_args()
    dfu: Path = args.dfu
    if not dfu.is_file():
        print(f"error: no existe {dfu}", file=sys.stderr)
        sys.exit(1)

    base, payload, payload_off = extract_dfu_payload(dfu)
    addrs = [
        (0x0800FECC, "DAT_0800fecc (estado / índice time÷ en +6)"),
        (0x0800FED8, "DAT_0800fed8 → tabla bytes (rama *fecc==2)"),
        (0x0800FEDC, "DAT_0800fedc → tabla bytes (otra rama)"),
        (0x0800FEE4, "DAT_0800fee4 → base uint32[] en RAM (rama *fecc==2)"),
        (0x0800FEE8, "DAT_0800fee8 → base uint32[] en RAM (otra rama)"),
    ]

    print(f"DFU:     {dfu}")
    print(f"Base:    {base:#010x}")
    print(f"Payload: {len(payload)} bytes, empieza en offset archivo {payload_off:#x} ({payload_off})")
    print()
    print(f"{'VMA':>12}  {'off.bin':>10}  {'off.dfu':>10}  {'word32':>12}  etiqueta")
    print("-" * 88)
    for vma, label in addrs:
        vma_s = f"0x{vma:08x}"
        if vma < base or vma + 4 > base + len(payload):
            print(f"{vma_s}  (fuera del payload para base {base:#010x})  {label}")
            continue
        off_bin = vma - base
        off_dfu = payload_off + off_bin
        w = struct.unpack_from("<I", payload, off_bin)[0]
        w_s = f"0x{w:08x}"
        print(f"{vma_s}  {off_bin:#10x}  {off_dfu:#10x}  {w_s:>12}  {label}")


if __name__ == "__main__":
    main()
