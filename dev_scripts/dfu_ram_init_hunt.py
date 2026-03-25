#!/usr/bin/env python3
"""
Busca en el payload DfuSe (misma extracción que dev_scripts/decompile_firmware.sh):
  - Todas las apariciones en ROM de los punteros SRAM usados en la pool
    (palabras 32-bit little-endian).
  - Opcionalmente desensambla el trampolín del vector Reset (0x08040550).

No encuentra por sí solo la región LMA de .data (haría falta el mapa del linker
o seguir el runtime hasta __copy_*). Sirve para ver si esos punteros se repiten
en código o solo están en la constant pool.

Uso:
  python3 dev_scripts/dfu_ram_init_hunt.py
  python3 dev_scripts/dfu_ram_init_hunt.py /ruta/firmware.dfu
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

# Opcional: desensamblado
try:
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

    _HAVE_CAPSTONE = True
except ImportError:
    _HAVE_CAPSTONE = False


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


def find_all(data: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    i = 0
    while True:
        j = data.find(needle, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def disasm_thumb(code: bytes, vma: int, max_insns: int = 12) -> None:
    if not _HAVE_CAPSTONE:
        print("  (instala el paquete `capstone` para ver desensamblado)")
        return
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    n = 0
    for ins in md.disasm(code, vma):
        print(f"    {ins.address:#010x}  {ins.bytes.hex():12}  {ins.mnemonic:8} {ins.op_str}")
        n += 1
        if n >= max_insns:
            break


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Busca punteros RAM y trampolín Reset en DFU")
    ap.add_argument(
        "dfu",
        nargs="?",
        default=str(root / "firmware" / "HantekHTX2021090901.dfu"),
        type=Path,
        help="Archivo .dfu",
    )
    args = ap.parse_args()
    dfu: Path = args.dfu
    if not dfu.is_file():
        print(f"error: no existe {dfu}", file=sys.stderr)
        sys.exit(1)

    base, payload, payload_off = extract_dfu_payload(dfu)
    ptrs: list[tuple[int, str]] = [
        (0x2000CA4C, "estado (DAT_0800fecc / pool)"),
        (0x20001CA8, "tabla bytes rama A (DAT_0800fed8)"),
        (0x20001C84, "tabla bytes rama B (DAT_0800fedc)"),
        (0x20001BFC, "tabla uint32 rama A (DAT_0800fee4)"),
        (0x20001B74, "tabla uint32 rama B (DAT_0800fee8)"),
    ]

    print(f"DFU:     {dfu}")
    print(f"Base:    {base:#010x}")
    print(f"Payload: {len(payload)} bytes, offset archivo {payload_off:#x}")
    print()
    print("=== Apariciones de punteros SRAM (32-bit LE) en la imagen flash ===")
    print(f"{'puntero':>14}  {'n':>4}  {'VMA(s) en ROM':<50}")
    print("-" * 88)
    for ptr, label in ptrs:
        needle = struct.pack("<I", ptr)
        offs = find_all(payload, needle)
        vmas = [f"{base + o:#010x}" for o in offs]
        if not vmas:
            vma_str = "(ninguna)"
        elif len(vmas) <= 8:
            vma_str = ", ".join(vmas)
        else:
            vma_str = ", ".join(vmas[:8]) + f" … (+{len(vmas) - 8} más)"
        print(f"0x{ptr:08x}  {len(offs):4d}  {vma_str}")
        print(f"              etiqueta: {label}")
    print()
    print(
        "Interpretación: los punteros a las **tablas** time/div (0x20001BFC, 0x20001B74,"
    )
    print(
        "0x20001CA8, 0x20001C84) suelen aparecer **una vez** cada uno (solo en la pool)."
    )
    print(
        "El puntero de **estado** 0x2000CA4C se referencia en muchos sitios (struct global)."
    )
    print(
        "Los **valores** de las tablas en SRAM no están como segundo bloque literal junto"
    )
    print(
        "a esos punteros; hay que rastrear .data / stores o medir en ejecución (SWD, etc.)."
    )
    print()

    # Trampolín Reset: vector apunta a 0x08040551 → entrada Thumb en 0x08040550
    # Solo 8 bytes son código; a continuación viene el literal pool (no desensamblar).
    reset_vma = 0x08040550
    off_bin = reset_vma - base
    if 0 <= off_bin < len(payload) - 8:
        print(f"=== Trampolín en {reset_vma:#010x} (off.bin {off_bin:#x}) ===")
        chunk = payload[off_bin : off_bin + 8]
        tail = payload[off_bin + 8 : off_bin + 16]
        print(f"    código (8 B): {chunk.hex()}")
        print(f"    pool (8 B):   {tail.hex()}")
        disasm_thumb(chunk, reset_vma, max_insns=8)
    else:
        print("=== Reset fuera del payload (no se muestra trampolín) ===")

    print()
    print("Capstone:", "sí" if _HAVE_CAPSTONE else "no instalado")


if __name__ == "__main__":
    main()
