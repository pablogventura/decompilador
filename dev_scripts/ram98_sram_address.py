#!/usr/bin/env python3
"""
Deriva la dirección SRAM del bloque leído en FUN_08032140 (read-settings / ram98_*).

El símbolo Ghidra ``DAT_08032698`` no es una VMA en flash con ese valor: el único
literal de 32 bits ``0x2000cc4c`` en el firmware está en el pool @ 0x08032624,
cargado por ``ldr r1, [pc, #0x168]`` en 0x080324b8 (FUN_08032140).

Relación útil con el pool time/div ya estudiado:
  0x2000ca4c + 0x200 == 0x2000cc4c

No hay otra aparición de ``0x2000cc4c`` en el binario: las escrituras al byte
``ram98_byte0`` probablemente son indirectas (base+desplazamiento) y no xref
directas a 0x2000cc4c en Ghidra.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    bin_path = root / "firmware" / "HantekHTX2021090901.bin"
    if not bin_path.is_file():
        print(f"error: no existe {bin_path}", file=sys.stderr)
        return 1
    b = bin_path.read_bytes()
    off = 0x32624
    w = struct.unpack_from("<I", b, off)[0]
    print(f"Binario: {bin_path}")
    print(f"Pool flash VMA 0x{0x08000000+off:08x}: puntero LE32 = 0x{w:08x}")
    print(f"Coincide con 0x2000ca4c + 0x200: {0x2000CA4C + 0x200:#x} == 0x{w:08x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
