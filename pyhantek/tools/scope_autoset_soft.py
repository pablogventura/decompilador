#!/usr/bin/env python3
"""
Autoset por software (PC): ajusta índices de **V/div** y opcionalmente **TIME_DIV** sin usar
``SCOPE_AUTOSET`` (0x13). Usa capturas ``0x16`` y métricas en un canal (CH1/CH2).

Heurística (índices firmware, no SI):
  - Primera captura **sin** cambiar V/div (coherente con DDS → ``capture_scope_raw``).
  - Si hay **clipping** → sube índice V/div (menos ganancia).
  - Si **pp** es alto (sin clipping) → sube índice V/div (más margen).
  - Si **pp** es bajo → baja índice V/div, salvo ``--invert-volt-heuristic``.
  - Opcional: cruces por la media fuera de rango → ``TIME_DIV`` ±1.

Requiere señal estable (p. ej. DDS interno o generador externo). No replica el algoritmo del fabricante.

Ejemplo:
  cd hantek && .venv/bin/python tools/scope_autoset_soft.py --wave 2 --freq 50 --amp 1200
  .venv/bin/python tools/scope_autoset_soft.py --no-dds --volt-min 2 --volt-max 11 --iterations 15
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE
from hantek_usb.dds_scope_helpers import (
    ScopeChannelMetrics,
    capture_scope_raw,
    configure_dds,
    compute_scope_channel_metrics,
    tx_wait_ack,
)
from hantek_usb.protocol import Opcodes04440, ch_opcode, fun_04440, read_all_settings, scope_run_stop_stm32, work_type_packet
from hantek_usb.transport import HantekLink


def _apply_volt_idx(link: HantekLink, channel: int, idx: int) -> None:
    _ = tx_wait_ack(
        link,
        fun_04440(ch_opcode(channel, 4), int(idx) & 0xFF, 1, True),
        retries=2,
        sleep_s=0.2,
    )


def _apply_time_div(link: HantekLink, td: int) -> None:
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TIME_DIV, int(td) & 0xFFFF, 2, True),
        retries=2,
        sleep_s=0.2,
    )


def _apply_scope_defaults_once(
    link: HantekLink,
    *,
    time_div: int,
    trigger_source: int,
    trigger_sweep: int,
) -> None:
    """
    Tras la primera captura (mismo camino que coherencia: DDS → ``capture_scope_raw``),
    opcionalmente fija TIME_DIV y disparo para las siguientes iteraciones.
    """
    link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
    _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
    _apply_time_div(link, time_div)
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TRIGGER_SOURCE, int(trigger_source) & 0xFFFF, 2, True),
        retries=2,
        sleep_s=0.15,
    )
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TRIGGER_SWEEP, int(trigger_sweep) & 0xFFFF, 2, True),
        retries=2,
        sleep_s=0.15,
    )
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.12)


def _capture_metrics(
    link: HantekLink,
    *,
    count_a: int,
    count_b: int,
    scope_settle_s: float,
    smart_sleep_ms: int,
    wave: int,
    rep: int,
    clip_hi: int,
    clip_lo: int,
    metrics_channel: int,
) -> ScopeChannelMetrics:
    raw = capture_scope_raw(
        link,
        count_a,
        count_b,
        scope_settle_s,
        smart_sleep_ms=smart_sleep_ms,
    )
    return compute_scope_channel_metrics(
        raw,
        wave=wave,
        rep=rep,
        clip_hi=clip_hi,
        clip_lo=clip_lo,
        interleaved=True,
        metrics_channel=metrics_channel,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autoset por software (V/div + opcional TIME_DIV).")
    p.add_argument("--no-dds", action="store_true", help="No configurar generador interno (señal externa).")
    p.add_argument("--wave", type=lambda x: int(x, 0), default=2)
    p.add_argument("--freq", type=int, default=50)
    p.add_argument("--amp", type=int, default=1200)
    p.add_argument("--dds-settle-ms", type=float, default=350.0)

    p.add_argument("--metrics-ch", type=int, choices=(1, 2), default=1, help="Canal donde medir y ajustar V/div.")
    p.add_argument(
        "--volt-channel",
        type=int,
        choices=(0, 1),
        default=None,
        help="Índice de canal para opcode V/div (0=CH1, 1=CH2). Por defecto = metrics-ch-1.",
    )
    p.add_argument("--volt-min", type=int, default=0, help="Índice V/div mínimo.")
    p.add_argument("--volt-max", type=int, default=11, help="Índice V/div máximo.")
    p.add_argument(
        "--volt-start",
        type=int,
        default=None,
        help="Índice V/div inicial al ajustar (default: 7 si entra en volt-min..max, si no la media).",
    )
    p.add_argument(
        "--apply-volt-before-first-capture",
        action="store_true",
        help="Aplica V/div antes de la primera captura (comportamiento antiguo; suele empeorar con DDS).",
    )
    p.add_argument(
        "--invert-volt-heuristic",
        action="store_true",
        help="Invierte el sentido de subir/bajar índice V/div si en tu equipo se comporta al revés.",
    )

    p.add_argument("--time-div-start", type=lambda x: int(x, 0), default=8)
    p.add_argument("--time-div-min", type=lambda x: int(x, 0), default=2)
    p.add_argument("--time-div-max", type=lambda x: int(x, 0), default=24)
    p.add_argument(
        "--adjust-time-div",
        action="store_true",
        help="Si los cruces por la media están fuera de rango, prueba TIME_DIV ±1.",
    )
    p.add_argument("--crossings-min", type=int, default=2, help="Mínimo de cruces por la media deseado.")
    p.add_argument("--crossings-max", type=int, default=80, help="Máximo razonable de cruces (ruido).")

    p.add_argument("--target-pp-min", type=float, default=55.0, help="PP ADC mínimo deseable (sin clipping).")
    p.add_argument("--target-pp-max", type=float, default=210.0, help="PP ADC máximo deseable (margen a rieles).")
    p.add_argument("--clip-hi", type=int, default=250)
    p.add_argument("--clip-lo", type=int, default=5)

    p.add_argument("--iterations", type=int, default=14, help="Máximo de pasos de ajuste de V/div.")
    p.add_argument("--scope-settle-ms", type=float, default=130.0)
    p.add_argument("--after-step-ms", type=float, default=90.0, help="Tras cambiar V/div o TIME_DIV, antes de capturar.")
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument("--timeout-ms", type=int, default=9000)
    p.add_argument("--smart-sleep-ms", type=int, default=18)
    p.add_argument("--trigger-source", type=lambda x: int(x, 0), default=0)
    p.add_argument("--trigger-sweep", type=lambda x: int(x, 0), default=0)
    p.add_argument("-q", "--quiet", action="store_true", help="Menos líneas de progreso.")
    return p


def main(argv: List[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    volt_ch = ns.volt_channel if ns.volt_channel is not None else (ns.metrics_ch - 1)
    if not (ns.volt_min <= ns.volt_max):
        print("Error: --volt-min debe ser <= --volt-max", file=sys.stderr)
        return 2
    if ns.iterations < 2:
        print("Error: --iterations debe ser >= 2 (primera captura + ajustes).", file=sys.stderr)
        return 2

    def _default_volt_start() -> int:
        if ns.volt_start is not None:
            return max(ns.volt_min, min(ns.volt_max, ns.volt_start))
        if ns.volt_min <= 7 <= ns.volt_max:
            return 7
        return (ns.volt_min + ns.volt_max) // 2

    scope_settle = max(0.0, ns.scope_settle_ms / 1000.0)
    after_step = max(0.0, ns.after_step_ms / 1000.0)
    dds_settle = max(0.0, ns.dds_settle_ms / 1000.0)

    td = int(ns.time_div_start)
    td = max(ns.time_div_min, min(ns.time_div_max, td))
    volt_idx = _default_volt_start()

    link = HantekLink(timeout_ms=ns.timeout_ms)
    try:
        if not ns.no_dds:
            configure_dds(link, wave=ns.wave, freq=ns.freq, amp=ns.amp, settle_s=dds_settle)

        wave_tag = ns.wave if not ns.no_dds else 0

        def _one_step(it: int, label_volt: str) -> ScopeChannelMetrics:
            if ns.apply_volt_before_first_capture or it > 1:
                _apply_volt_idx(link, volt_ch, volt_idx)
                link.write(scope_run_stop_stm32(True))
                time.sleep(0.1)
                if after_step > 0:
                    time.sleep(after_step)
            m = _capture_metrics(
                link,
                count_a=ns.count_a,
                count_b=ns.count_b,
                scope_settle_s=scope_settle,
                smart_sleep_ms=ns.smart_sleep_ms,
                wave=wave_tag,
                rep=it,
                clip_hi=ns.clip_hi,
                clip_lo=ns.clip_lo,
                metrics_channel=ns.metrics_ch,
            )
            if not ns.quiet:
                print(
                    f"[{it:2d}] volt={label_volt:12s}  td={td:4d}  "
                    f"pp={m.pp:6.1f}  min={m.u8_min:3d} max={m.u8_max:3d}  "
                    f"xings={m.mean_crossings:4d}  clipped={m.clipped}"
                )
            return m

        # Primera captura: igual que ``dds_osc_coherence`` (DDS → ``capture_scope_raw`` sin tocar V/div).
        m = _one_step(1, "(heredado)" if not ns.apply_volt_before_first_capture else f"idx={volt_idx}")

        def _pp_ok(mm: ScopeChannelMetrics) -> bool:
            return (not mm.clipped) and (ns.target_pp_min <= mm.pp <= ns.target_pp_max)

        def _x_ok(mm: ScopeChannelMetrics) -> bool:
            return (not ns.adjust_time_div) or (
                ns.crossings_min <= mm.mean_crossings <= ns.crossings_max
            )

        if _pp_ok(m) and _x_ok(m):
            print("")
            print(
                f"OK (sin tocar V/div): TIME_DIV=n/a  pp={m.pp:.1f}  xings={m.mean_crossings}  (captura inicial)"
            )
            return 0

        if m.pp < 8.0 and not m.clipped:
            print("", file=sys.stderr)
            print(
                "La captura inicial es casi plana (pp<8). Conectá la salida DDS al canal del scope, "
                "comprobá con `tools/dds_osc_coherence.py` y reintentá.",
                file=sys.stderr,
            )
            return 1

        if not ns.apply_volt_before_first_capture:
            _apply_scope_defaults_once(
                link,
                time_div=td,
                trigger_source=ns.trigger_source,
                trigger_sweep=ns.trigger_sweep,
            )
            if after_step > 0:
                time.sleep(after_step)

        for it in range(2, ns.iterations + 1):
            m = _one_step(it, f"idx={volt_idx}")
            rail_hit = m.clipped or m.u8_max >= ns.clip_hi or m.u8_min <= ns.clip_lo

            inv = ns.invert_volt_heuristic

            if rail_hit:
                if volt_idx < ns.volt_max:
                    volt_idx += 1
                    continue
                print("", file=sys.stderr)
                print(
                    "Advertencia: clipping y volt_idx ya en máximo; probá bajar DDS o señal externa.",
                    file=sys.stderr,
                )
                break

            if m.pp > ns.target_pp_max:
                if volt_idx < ns.volt_max:
                    volt_idx += 1
                    continue
                break

            if m.pp < ns.target_pp_min:
                if volt_idx > ns.volt_min:
                    volt_idx += 1 if inv else -1
                    continue
                print("", file=sys.stderr)
                print(
                    "Advertencia: pp bajo y volt_idx en mínimo; subí amplitud o revisá sonda/canal.",
                    file=sys.stderr,
                )
                break

            if ns.adjust_time_div:
                if m.mean_crossings < ns.crossings_min and td > ns.time_div_min:
                    td -= 1
                    _apply_time_div(link, td)
                    link.write(scope_run_stop_stm32(True))
                    time.sleep(0.12 + after_step)
                    continue
                if m.mean_crossings > ns.crossings_max and td < ns.time_div_max:
                    td += 1
                    _apply_time_div(link, td)
                    link.write(scope_run_stop_stm32(True))
                    time.sleep(0.12 + after_step)
                    continue

            print("")
            print(
                f"OK: volt_idx={volt_idx}  TIME_DIV={td}  pp={m.pp:.1f}  "
                f"xings={m.mean_crossings}  (iteración {it})"
            )
            return 0

        print("", file=sys.stderr)
        print(
            f"No convergió en {ns.iterations} capturas. Último volt_idx={volt_idx}  TIME_DIV={td}",
            file=sys.stderr,
        )
        return 1
    finally:
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
