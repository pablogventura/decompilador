#!/usr/bin/env python3
"""
Compara dos respuestas **read-settings** (25 B cabecera ``55 19 … 15`` + 21 B útiles)
y lista campos que difieren (nombres alineados con ``parse_resp.read_all_set_firmware_field_names``).

Entradas: hex en línea de comandos, o ruta a un ``.txt`` de captura (como los de
``captures/estado_read_settings_*.txt``).

Ejemplos::

  python tools/compare_read_settings.py \\
    captures/estado_A.txt captures/estado_B.txt

  python tools/compare_read_settings.py \\
    "5519001501....97" "5519001501....95"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.parse_resp import (
    decode_read_all_set_firmware25,
    read_all_set_firmware_field_names,
)


def _hex_from_messy_line(line: str) -> bytes:
    line = line.split(":", 1)[-1].strip()
    hexonly = re.sub(r"[^0-9a-fA-F]", "", line)
    if len(hexonly) % 2:
        raise ValueError(f"hex impar: {line[:60]}…")
    return bytes.fromhex(hexonly)


def _extract_from_capture_text(text: str) -> bytes:
    for pat in (
        r"Payload\s+21\s+B\s*@[^\n]*:\s*([0-9a-fA-F\s]+)",
        r"Respuesta\s+IN\s*\(64\s*B\)\s*:\s*([0-9a-fA-F\s]+)",
        r"\bHex:\s*([0-9a-fA-F\s]+)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            b = _hex_from_messy_line(m.group(1))
            return normalize_read_settings_block(b)
    m = re.search(r"(55\s*19\s*00\s*15(?:\s+[0-9a-fA-F]{2}){20,})", text, re.I)
    if m:
        return normalize_read_settings_block(_hex_from_messy_line(m.group(1)))
    raise ValueError("No encontré bloque read-settings en el archivo")


def normalize_read_settings_block(b: bytes) -> bytes:
    """Devuelve exactamente 25 B con cabecera ``55 19 * 15``."""
    if len(b) >= 25 and b[0] == 0x55 and b[1] == 0x19 and b[3] == 0x15:
        return b[:25]
    if len(b) >= 64:
        cand = b[:25]
        if cand[0] == 0x55 and cand[1] == 0x19 and cand[3] == 0x15:
            return cand
    if len(b) == 21:
        return bytes([0x55, 0x19, 0x00, 0x15]) + b
    raise ValueError(
        f"Bloque inválido ({len(b)} B): hace falta 25 B 55-19-*-15, 64 B IN, o 21 B payload"
    )


def load_arg(arg: str) -> bytes:
    p = Path(arg)
    if p.is_file():
        return _extract_from_capture_text(p.read_text(encoding="utf-8", errors="replace"))
    return normalize_read_settings_block(bytes.fromhex(arg.replace(" ", "")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Diff read-settings (firmware 21 B con nombres).")
    ap.add_argument("a", help="Archivo captura o hex 25/64/21 B")
    ap.add_argument("b", help="Archivo captura o hex")
    ap.add_argument(
        "--quiet-payload",
        action="store_true",
        help="Solo imprimir índices que cambian sin nombres de campo",
    )
    ns = ap.parse_args(argv)
    try:
        ba, bb = load_arg(ns.a), load_arg(ns.b)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    da = decode_read_all_set_firmware25(ba)
    db = decode_read_all_set_firmware25(bb)
    if not da.get("valid_layout") or not db.get("valid_layout"):
        print("Error: algún bloque no decodifica como 55 19 * 15", file=sys.stderr)
        return 1

    names = read_all_set_firmware_field_names()
    pa, pb = ba[4:25], bb[4:25]
    diffs: list[tuple[int, str, int, int]] = []
    for i, name in enumerate(names):
        if i >= len(pa) or i >= len(pb):
            break
        if pa[i] != pb[i]:
            diffs.append((i, name, pa[i], pb[i]))

    print(f"A payload[0:21] = {pa.hex(' ')}")
    print(f"B payload[0:21] = {pb.hex(' ')}")
    print(f"Bytes distintos: {len(diffs)} / 21")
    if not diffs:
        return 0
    for i, name, ua, ub in diffs:
        if ns.quiet_payload:
            print(f"  [{i:2d}] 0x{ua:02x} → 0x{ub:02x}")
        else:
            print(f"  [{i:2d}] {name}: 0x{ua:02x} → 0x{ub:02x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
