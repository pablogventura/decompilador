#!/usr/bin/env python3
"""
Compara dos JSON generados por ``snapshot_scope_state.py`` (campo ``fields_u8``
y, si difiere, el hex del payload de 21 B).

Ejemplo::

  python tools/snapshot_scope_state.py -o /tmp/a.json --note antes
  # … acción solo en el panel (p. ej. Force trigger) …
  python tools/snapshot_scope_state.py -o /tmp/b.json --note despues
  python tools/compare_scope_snapshots.py /tmp/a.json /tmp/b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"No se pudo leer JSON {p}: {e}") from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Diff dos snapshots scope (JSON).")
    ap.add_argument("a", type=Path, help="Primer .json (snapshot_scope_state)")
    ap.add_argument("b", type=Path, help="Segundo .json")
    ap.add_argument(
        "--json",
        action="store_true",
        help="Salida máquina: lista de {field, old, new}",
    )
    ns = ap.parse_args(argv)
    ja, jb = _load(ns.a), _load(ns.b)

    fa = ja.get("fields_u8") or {}
    fb = jb.get("fields_u8") or {}
    if not isinstance(fa, dict) or not isinstance(fb, dict):
        print("Error: falta fields_u8 en algún JSON", file=sys.stderr)
        return 1

    diffs: list[tuple[str, int, int]] = []
    for k in sorted(set(fa) | set(fb)):
        va, vb = fa.get(k), fb.get(k)
        if va is None and vb is None:
            continue
        if va is None:
            diffs.append((k, -1, int(vb)))
        elif vb is None:
            diffs.append((k, int(va), -1))
        elif int(va) != int(vb):
            diffs.append((k, int(va), int(vb)))

    pa = ja.get("payload_21_hex", "")
    pb = jb.get("payload_21_hex", "")
    notes = (ja.get("note", ""), jb.get("note", ""))

    if ns.json:
        out = [{"field": k, "old": o, "new": n} for k, o, n in diffs]
        print(json.dumps(out, ensure_ascii=False))
        return 0

    print(f"A: {ns.a}  note={notes[0]!r}")
    print(f"B: {ns.b}  note={notes[1]!r}")
    if pa and pb and pa != pb:
        print(f"payload_21_hex A = {pa}")
        print(f"payload_21_hex B = {pb}")
    print(f"Campos distintos: {len(diffs)}")
    for k, o, n in diffs:
        so = "?" if o < 0 else f"0x{o:02x}"
        sn = "?" if n < 0 else f"0x{n:02x}"
        extra = " (solo en un snapshot)" if o < 0 or n < 0 else ""
        print(f"  {k}: {so} → {sn}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
