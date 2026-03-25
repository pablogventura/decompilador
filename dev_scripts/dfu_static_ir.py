#!/usr/bin/env python3
"""
Ingeniería inversa *estática* (sin hardware): ayudas para localizar el origen de
las tablas en SRAM referenciadas desde la pool (0x20001BFC, 0x20001B74, …).

Qué **no** hace el binario de forma obvia (revisado sobre el DFU Hantek):
  - No aparecen instrucciones `movw` con inmediatos 0x1BFC / 0x1B74 / …
  - No hay bucles `ldr [r0], #4` / `str [r1], #4` típicos de memcpy en el
    desensamblado Capstone global (el compilador puede usar otra secuencia).
  - Los punteros a tablas solo están en la constant pool ROM (ver
    dev_scripts/dfu_ram_init_hunt.py).

Qué **sí** puedes hacer sin chip:

1) **Ghidra / Binary Ninja / IDA** (recomendado)
   - Carga el payload con imagen base **0x08005000** (igual que Ghidra headless).
   - En **0x0800FEE4**…**0x0800FEE8** / **FED8** / **FEDC**: son palabras ROM cuyo
     valor es un **puntero SRAM** (no la tabla). Marca como `uint32`.
   - **Xrefs** a esas direcciones ROM: verás solo **cargas** para leer la tabla.
   - Para **escrituras**: crea/marca región RAM **0x20000000** y ve a
     **0x20001BFC** (y el tamaño que quieras, p. ej. 32 bytes). Busca
     **References** con tipo **WRITE** (o “Find references to address”).
     Si el proyecto no tenía RAM poblada al importar, puede no haber xrefs;
     entonces sigue el **flujo** desde funciones que **llaman** a
     `FUN_0800fe80` / `FUN_0800fd64` (p. ej. en init aparece `bl` a ~0x0800FE80).
   - Opcional: **decompilar** las funciones que preceden a la primera llamada a
     esas rutinas y buscar bucles que escriban en `[reg + off]`.

2) **Este script**
   - `--histogram`: cuenta cuántas veces aparece cada literal 32-bit en
     **0x20000000–0x201FFFFF** en la imagen flash (útil para ver qué punteros
     SRAM se reutilizan).
   - `--candidates`: ventanas de 7×uint32 alineadas que **no** parecen punteros
     a ROM/RAM (heurística débil; muchos falsos positivos por strings).

Uso:
  python3 dev_scripts/dfu_static_ir.py
  python3 dev_scripts/dfu_static_ir.py --histogram --top 25
  python3 dev_scripts/dfu_static_ir.py --candidates --max 20
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections import Counter
from pathlib import Path


def extract_dfu_payload(dfu: Path) -> tuple[int, bytes, int]:
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


def ram_literal_histogram(payload: bytes, lo: int, hi: int) -> Counter[int]:
    c: Counter[int] = Counter()
    for i in range(0, len(payload) - 3, 4):
        w = struct.unpack_from("<I", payload, i)[0]
        if lo <= w <= hi:
            c[w] += 1
    return c


def window_candidates(payload: bytes, base: int, nwords: int = 7) -> list[tuple[int, int, list[int]]]:
    """Ventanas alineadas de nwords uint32 sin punteros obvios a ROM/RAM."""
    words = [struct.unpack_from("<I", payload, i)[0] for i in range(0, len(payload) - 3, 4)]

    def plausible(w: int) -> bool:
        if 0x08000000 <= w <= 0x083FFFFF:
            return False
        if 0x20000000 <= w <= 0x20FFFFFF:
            return False
        if w in (0, 0xFFFFFFFF):
            return False
        return True

    out: list[tuple[int, int, list[int]]] = []
    for i in range(0, len(words) - nwords):
        ws = words[i : i + nwords]
        if not all(plausible(w) for w in ws):
            continue
        if not all(w < 0x10000000 for w in ws):
            continue
        if len(set(ws)) < 3:
            continue
        # Penalizar ventanas que son claramente texto (muchos bytes imprimibles)
        raw = b"".join(struct.pack("<I", w) for w in ws)
        printable = sum(1 for b in raw if 0x20 <= b <= 0x7E)
        if printable > len(raw) * 0.55:
            continue
        score = sum(1 for w in ws if w < 0x10000)
        vma = base + i * 4
        out.append((score, vma, ws))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="IR estática: histograma RAM y candidatos")
    ap.add_argument(
        "dfu",
        nargs="?",
        default=str(root / "firmware" / "HantekHTX2021090901.dfu"),
        type=Path,
        help="Archivo .dfu",
    )
    ap.add_argument("--histogram", action="store_true", help="Contar literales SRAM en flash")
    ap.add_argument("--top", type=int, default=30, help="N entradas en histograma")
    ap.add_argument("--candidates", action="store_true", help="Ventanas heurísticas 7×uint32")
    ap.add_argument("--max", type=int, default=15, help="Máx. candidatos a listar")
    args = ap.parse_args()
    dfu: Path = args.dfu
    if not dfu.is_file():
        print(f"error: no existe {dfu}", file=sys.stderr)
        sys.exit(1)

    base, payload, payload_off = extract_dfu_payload(dfu)
    print(f"DFU: {dfu}")
    print(f"Base: {base:#010x}  payload: {len(payload)} B  offset archivo: {payload_off:#x}\n")

    if not args.histogram and not args.candidates:
        args.histogram = True
        args.candidates = True

    if args.histogram:
        lo, hi = 0x20000000, 0x201FFFFF
        hist = ram_literal_histogram(payload, lo, hi)
        print(f"=== Literales 32-bit en [{lo:#x}, {hi:#x}] (cuántas veces en la imagen flash) ===")
        for w, cnt in hist.most_common(args.top):
            print(f"  0x{w:08x}  ×{cnt}")
        print()

    if args.candidates:
        cand = window_candidates(payload, base, 7)
        print("=== Candidatos heurísticos (7×uint32, sin punteros 08…/20… obvios) ===")
        print("(Revisión manual con Ghidra/xxd; muchos no son la tabla time/div.)\n")
        for score, vma, ws in cand[: args.max]:
            ws_hex = ", ".join(f"0x{w:08x}" for w in ws)
            print(f"  score={score}  VMA {vma:#010x}  off.bin {vma - base:#x}")
            print(f"    {ws_hex}")
        print()


if __name__ == "__main__":
    main()
