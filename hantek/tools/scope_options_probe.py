#!/usr/bin/env python3
"""
Barrido de parámetros del osciloscopio (opcodes ``FUN_04440``) con **señal DDS fija**.

Mantiene el generador en una onda/frecuencia/amplitud conocidas, aplica un comando de
visualización o disparo por paso, captura ``0x16`` y muestra métricas en **CH1** (o CH2).

Sirve para correlacionar **valor USB** → **efecto en pp / cruces por la media / clipping**,
sin pretender calibrar V/div ni s/div en unidades físicas (eso depende del front-end).

Ejemplo:
  cd hantek && .venv/bin/python tools/scope_options_probe.py --sweep time-div \\
    --values 2,4,8,12,16 --wave 2 --freq 50 --amp 1200
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.dds_scope_helpers import (
    ScopeChannelMetrics,
    capture_scope_raw,
    configure_dds,
    compute_scope_channel_metrics,
    tx_wait_ack,
)
from hantek_usb.protocol import Opcodes04440, ch_opcode, fun_04440, read_all_settings, scope_run_stop_stm32, work_type_packet
from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE
from hantek_usb.transport import HantekLink

SWEEP_HELP = """
time-div       Opcode 0x0E (TIME_DIV), valor uint16 LE, 2 bytes de payload.
ch1-volt       CH1 V/div: opcode canal×6+4, payload 1 byte (índice vertical).
trigger-sweep  Opcode 0x12 (TRIGGER_SWEEP), uint16 LE.
trigger-source Opcode 0x10 (TRIGGER_SOURCE), uint16 LE (0=CH1 típico).
yt-format      Opcode 0x0D (YT_FORMAT), uint16 LE.
""".strip()


def _parse_values(s: str) -> List[int]:
    out: List[int] = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok, 0))
    if not out:
        raise argparse.ArgumentTypeError("Lista vacía.")
    return out


def _apply_sweep_step(
    link: HantekLink,
    sweep: str,
    value: int,
    *,
    after_op_s: float,
) -> None:
    v = int(value)
    if sweep == "time-div":
        pkt = fun_04440(Opcodes04440.TIME_DIV, v & 0xFFFF, 2, True)
    elif sweep == "ch1-volt":
        pkt = fun_04440(ch_opcode(0, 4), v & 0xFF, 1, True)
    elif sweep == "trigger-sweep":
        pkt = fun_04440(Opcodes04440.TRIGGER_SWEEP, v & 0xFFFF, 2, True)
    elif sweep == "trigger-source":
        pkt = fun_04440(Opcodes04440.TRIGGER_SOURCE, v & 0xFFFF, 2, True)
    elif sweep == "yt-format":
        pkt = fun_04440(Opcodes04440.YT_FORMAT, v & 0xFFFF, 2, True)
    else:
        raise ValueError(sweep)
    _ = tx_wait_ack(link, pkt, retries=2, sleep_s=0.2)
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.1)
    if after_op_s > 0:
        time.sleep(after_op_s)


def _baseline_scope(link: HantekLink, time_div: int, after_op_s: float) -> None:
    """Estado inicial reproducible antes del barrido (sin autoset: evita saltos bruscos)."""
    link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
    _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TIME_DIV, int(time_div) & 0xFFFF, 2, True),
        retries=2,
        sleep_s=0.2,
    )
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TRIGGER_SOURCE, 0, 2, True),
        retries=2,
        sleep_s=0.2,
    )
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TRIGGER_SWEEP, 0, 2, True),
        retries=2,
        sleep_s=0.2,
    )
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.12)
    if after_op_s > 0:
        time.sleep(after_op_s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Barrido de opciones de osciloscopio con DDS fijo (métricas por canal).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=SWEEP_HELP,
    )
    p.add_argument(
        "--sweep",
        choices=("time-div", "ch1-volt", "trigger-sweep", "trigger-source", "yt-format"),
        help="Qué parámetro variar (ver epílogo). Obligatorio salvo --explain.",
    )
    p.add_argument(
        "--values",
        type=_parse_values,
        help="Lista CSV de valores enteros, p.ej. 4,8,12. Obligatorio salvo --explain.",
    )
    p.add_argument(
        "--baseline-time-div",
        type=lambda x: int(x, 0),
        default=8,
        help="TIME_DIV inicial antes del barrido (uint16). No aplica al paso si --sweep time-div.",
    )
    p.add_argument("--wave", type=lambda x: int(x, 0), default=2, help="Índice DDS (2=seno)")
    p.add_argument("--freq", type=int, default=50)
    p.add_argument("--amp", type=int, default=1200)
    p.add_argument("--dds-settle-ms", type=float, default=300.0)
    p.add_argument("--scope-settle-ms", type=float, default=120.0, help="Tras cada cambio de parámetro, antes de 0x16")
    p.add_argument("--after-op-ms", type=float, default=80.0, help="Espera extra tras ack + RUN")
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument("--clip-hi", type=int, default=250)
    p.add_argument("--clip-lo", type=int, default=5)
    p.add_argument("--timeout-ms", type=int, default=8000)
    p.add_argument("--metrics-ch", type=int, choices=(1, 2), default=1)
    p.add_argument(
        "--explain",
        action="store_true",
        help="Imprime referencia rápida de opcodes (no ejecuta USB).",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.explain:
        print(SWEEP_HELP)
        print(
            "\nLos valores numéricos son índices firmware (misma escala que envía el DLL), "
            "no V/div ni s/div en SI. Si un paso falla con timeout, probá --after-op-ms mayor.\n"
        )
        return 0
    if not ns.sweep or ns.values is None:
        print("Error: hace falta --sweep y --values (o usá --explain).", file=sys.stderr)
        return 2

    after_op = max(0.0, ns.after_op_ms / 1000.0)
    dds_settle = max(0.0, ns.dds_settle_ms / 1000.0)
    scope_settle = max(0.0, ns.scope_settle_ms / 1000.0)

    rows: List[tuple[str, ScopeChannelMetrics]] = []
    link = HantekLink(timeout_ms=ns.timeout_ms)
    try:
        configure_dds(link, wave=ns.wave, freq=ns.freq, amp=ns.amp, settle_s=dds_settle)
        if ns.sweep != "time-div":
            _baseline_scope(link, time_div=ns.baseline_time_div, after_op_s=after_op)
        else:
            link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
            _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
            link.write(scope_run_stop_stm32(True))
            time.sleep(0.12)
            if after_op > 0:
                time.sleep(after_op)

        for i, val in enumerate(ns.values):
            label = f"{ns.sweep}={val}"
            try:
                _apply_sweep_step(link, ns.sweep, val, after_op_s=after_op)
                raw = capture_scope_raw(
                    link,
                    ns.count_a,
                    ns.count_b,
                    settle_s=scope_settle,
                    smart_sleep_ms=18,
                )
                m = compute_scope_channel_metrics(
                    raw,
                    wave=ns.wave,
                    rep=i + 1,
                    clip_hi=ns.clip_hi,
                    clip_lo=ns.clip_lo,
                    interleaved=True,
                    metrics_channel=ns.metrics_ch,
                )
                rows.append((label, m))
                print(
                    f"[ok] {label:28s}  pp={m.pp:6.1f}  mean={m.mean:6.1f}  "
                    f"xings={m.mean_crossings:4d}  clipped={m.clipped}"
                )
            except Exception as e:
                print(f"[fail] {label}: {e}", file=sys.stderr)
                return 1
    finally:
        link.close()

    print("")
    print(f"{'setting':30s}  {'pp':>7s}  {'min':>4s} {'max':>4s}  {'xings':>5s}  {'frac_mid':>8s}  other_ch")
    print("-" * 92)
    for label, m in rows:
        oth = (
            f"{m.other_ch_min}..{m.other_ch_max}"
            if m.other_ch_min is not None
            else "—"
        )
        print(
            f"{label:30s}  {m.pp:7.1f}  {m.u8_min:4d} {m.u8_max:4d}  "
            f"{m.mean_crossings:5d}  {m.frac_mid:8.3f}  {oth}"
        )
    print("")
    print(
        "Notas: `xings` = cruces de la señal respecto de su media (proxy de ciclos en la ventana). "
        "Sube con más períodos visibles o con forma más “osilante”; baja si la señal queda casi DC o saturada."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
