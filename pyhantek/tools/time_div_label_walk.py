#!/usr/bin/env python3
"""
Recorre índices TIME_DIV y permite etiquetarlos manualmente mirando la pantalla.

Uso típico:
  cd hantek
  .venv/bin/python tools/time_div_label_walk.py --values 0,1,2,3,4,5,6,7

En cada paso:
  1) envía opcode TIME_DIV (0x0E) con el índice indicado,
  2) lee ReadAllSet (0x15) para observar `ram98_byte3`,
  3) pide una etiqueta libre (ej. "50ns/div", "200ns/div", "modo raro"...),
  4) guarda resultados en JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE
from hantek_usb.dds_scope_helpers import tx_wait_ack
from hantek_usb.parse_resp import decode_read_all_set_firmware25
from hantek_usb.protocol import Opcodes04440, fun_04440, read_all_settings, scope_run_stop_stm32, work_type_packet
from hantek_usb.transport import HantekLink


def _parse_values(s: str) -> List[int]:
    out: List[int] = []
    for tok in s.split(","):
        t = tok.strip()
        if not t:
            continue
        out.append(int(t, 0))
    if not out:
        raise argparse.ArgumentTypeError("Lista vacía.")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Barrido interactivo TIME_DIV con etiquetado manual.",
    )
    p.add_argument(
        "--values",
        type=_parse_values,
        default=[0, 1, 2, 3, 4, 5, 6, 7],
        help="CSV de índices TIME_DIV (ej: 0,1,2,3,4,5,6,7).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("time_div_labels.json"),
        help="Archivo JSON de salida.",
    )
    p.add_argument("--timeout-ms", type=int, default=8000)
    p.add_argument("--after-set-ms", type=float, default=120.0)
    p.add_argument(
        "--no-auto-run",
        action="store_true",
        help="No forzar RUN tras cada cambio de TIME_DIV.",
    )
    p.add_argument(
        "--toggle-run",
        action="store_true",
        help="Hace STOP->RUN en cada paso para forzar refresco visible.",
    )
    return p


def _extract_ram98_byte3(rsp: bytes) -> int | None:
    d = decode_read_all_set_firmware25(rsp)
    if not d.get("valid_layout"):
        return None
    fields: Dict[str, Any] = d.get("fields", {})
    item = fields.get("ram98_byte3")
    if not isinstance(item, dict):
        return None
    v = item.get("u8")
    if isinstance(v, int):
        return v
    return None


def main(argv: List[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    out_path: Path = ns.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    link = HantekLink(timeout_ms=ns.timeout_ms)
    try:
        link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
        _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)

        print("Inicio barrido TIME_DIV. Enter vacío = sin etiqueta; Ctrl+C para cortar.")
        print("")

        for idx in ns.values:
            pkt = fun_04440(Opcodes04440.TIME_DIV, int(idx) & 0xFFFF, 2, False)
            link.write(pkt)
            if ns.toggle_run:
                link.write(scope_run_stop_stm32(False))
                time.sleep(0.05)
            if not ns.no_auto_run:
                link.write(scope_run_stop_stm32(True))
            if ns.after_set_ms > 0:
                time.sleep(ns.after_set_ms / 1000.0)

            rsp = tx_wait_ack(link, read_all_settings(), retries=2, sleep_s=0.2)
            b3 = _extract_ram98_byte3(rsp)
            print(f"idx={idx:>3d}  write=ok  ram98_byte3={b3 if b3 is not None else '??'}")
            label = input("  etiqueta (ej 50ns/div): ").strip()
            note = input("  nota opcional: ").strip()

            rows.append(
                {
                    "idx_sent": int(idx),
                    "ack_byte3": None,
                    "ram98_byte3": b3,
                    "label": label,
                    "note": note,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                }
            )
            out_obj = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "values": ns.values,
                "rows": rows,
            }
            out_path.write_text(
                json.dumps(out_obj, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  guardado -> {out_path}")
            print("")
    finally:
        link.close()

    print(f"Hecho. {len(rows)} filas en {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
