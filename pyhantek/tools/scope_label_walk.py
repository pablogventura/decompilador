#!/usr/bin/env python3
"""
Etiquetado manual mirando la pantalla: V/div (ch-volt), formato YT, flanco de disparo.

  cd pyhantek
  .venv/bin/python tools/scope_label_walk.py --kind ch-volt
  .venv/bin/python tools/scope_label_walk.py --kind ch-volt --channel 1
  .venv/bin/python tools/scope_label_walk.py --kind yt --values 0,1,2,3
  .venv/bin/python tools/scope_label_walk.py --kind slope --values 0,1,2

Tras cada envío se hace ReadAllSet (0x15): el payload 21 B puede servir para correlación
futura (se imprime resumen de bytes nombrados en parse_resp).
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
from hantek_usb.parse_resp import decode_read_all_set_firmware25, format_read_all_set_firmware_decode
from hantek_usb.protocol import Opcodes04440, ch_opcode, fun_04440, read_all_settings, scope_run_stop_stm32, work_type_packet
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


def _apply(
    link: HantekLink,
    kind: str,
    channel: int,
    idx: int,
    *,
    toggle_run: bool,
    after_set_ms: float,
) -> None:
    if kind == "ch-volt":
        op = ch_opcode(int(channel) & 0xFF, 4)
        pkt = fun_04440(op, int(idx) & 0xFF, 1, False)
    elif kind == "yt":
        pkt = fun_04440(Opcodes04440.YT_FORMAT, int(idx) & 0xFFFF, 2, False)
    elif kind == "slope":
        pkt = fun_04440(Opcodes04440.TRIGGER_SLOPE, int(idx) & 0xFFFF, 2, False)
    else:
        raise ValueError(kind)
    link.write(pkt)
    if toggle_run:
        link.write(scope_run_stop_stm32(False))
        time.sleep(0.05)
    link.write(scope_run_stop_stm32(True))
    if after_set_ms > 0:
        time.sleep(after_set_ms / 1000.0)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Barrido interactivo: ch-volt / YT / slope.")
    p.add_argument(
        "--kind",
        choices=("ch-volt", "yt", "slope"),
        required=True,
        help="ch-volt=V/div; yt=set-yt-format; slope=set-trig-slope",
    )
    p.add_argument("--channel", type=int, default=0, help="Solo ch-volt: índice de canal (0=CH1).")
    p.add_argument(
        "--values",
        type=_parse_values,
        default=None,
        help="CSV de índices. Default: ch-volt 0..11; yt 0,1,2,3; slope 0,1,2.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON de salida (default según --kind).",
    )
    p.add_argument("--timeout-ms", type=int, default=8000)
    p.add_argument("--after-set-ms", type=float, default=150.0)
    p.add_argument(
        "--toggle-run",
        action="store_true",
        help="STOP→RUN tras cada paso (refresco UI).",
    )
    p.add_argument(
        "--dump-read-all",
        action="store_true",
        help="Tras cada paso, volcar decode ReadAllSet (21 B) para correlación.",
    )
    return p


def _default_values(kind: str) -> List[int]:
    if kind == "ch-volt":
        return list(range(12))
    if kind == "yt":
        return [0, 1, 2, 3]
    return [0, 1, 2]


def _default_out(kind: str) -> Path:
    return Path(
        {
            "ch-volt": "ch_volt_map_empirico.json",
            "yt": "yt_format_labels.json",
            "slope": "trig_slope_labels.json",
        }[kind]
    )


def main(argv: List[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    kind: str = ns.kind
    values: List[int] = ns.values if ns.values is not None else _default_values(kind)
    out_path: Path = ns.out if ns.out is not None else _default_out(kind)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    link = HantekLink(timeout_ms=ns.timeout_ms)
    try:
        link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
        _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)

        print(f"Modo «{kind}». Enter vacío = sin etiqueta; Ctrl+C para cortar.")
        if kind == "ch-volt":
            print(f"  Canal USB índice {ns.channel} (0=CH1). Mirá V/div en ese canal.")
        elif kind == "yt":
            print("  Mirá modo YT / XY / roll (según tu modelo).")
        else:
            print("  Mirá texto de flanco: rising / falling / both…")
        print("")

        for idx in values:
            _apply(
                link,
                kind,
                ns.channel,
                idx,
                toggle_run=ns.toggle_run,
                after_set_ms=ns.after_set_ms,
            )
            rsp = tx_wait_ack(link, read_all_settings(), retries=2, sleep_s=0.2)
            dec = decode_read_all_set_firmware25(rsp)
            ram98_b3 = None
            if dec.get("valid_layout"):
                f = dec.get("fields", {})
                r3 = f.get("ram98_byte3")
                if isinstance(r3, dict) and isinstance(r3.get("u8"), int):
                    ram98_b3 = r3["u8"]

            print(f"idx={idx!r}  read_all ram98_byte3={ram98_b3 if ram98_b3 is not None else '??'}")
            if ns.dump_read_all and dec.get("valid_layout"):
                block = format_read_all_set_firmware_decode(rsp)
                if block:
                    print(block)
            label = input("  etiqueta (texto en pantalla): ").strip()
            note = input("  nota opcional: ").strip()

            row: Dict[str, Any] = {
                "kind": kind,
                "idx_sent": int(idx),
                "ram98_byte3": ram98_b3,
                "label": label,
                "note": note,
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            if kind == "ch-volt":
                row["channel"] = int(ns.channel)
            rows.append(row)

            out_obj = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "kind": kind,
                "values": values,
                "rows": rows,
            }
            out_path.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  guardado -> {out_path}")
            print("")
    finally:
        link.close()

    print(f"Hecho. {len(rows)} filas en {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
