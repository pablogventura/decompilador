#!/usr/bin/env python3
"""
Prueba de coherencia DDS -> Osciloscopio para Hantek 2xx2.

Hace, por cada forma de onda:
1) Configura DDS (onda/frecuencia/amplitud, ON)
2) Cambia a modo osciloscopio
3) Captura muestras crudas por USB
4) Resume métricas y marca si hubo saturación ADC

Por defecto el buffer USB es **entrelazado** (CH1, CH2, …). Las métricas (pp, clipping,
``frac_mid``) se calculan sobre **un solo canal** (CH1 por defecto, ver ``--metrics-ch``),
no sobre el buffer mezclado.

Para barrer **time/div, V/div, disparo** con señal DDS fija y ver el efecto en la captura,
usá ``tools/scope_options_probe.py`` (ver README en hantek/).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import Iterable, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE, WORK_TYPE_SIGNAL_GENERATOR
from hantek_usb.dds_scope_helpers import (
    ScopeChannelMetrics,
    capture_scope_raw,
    configure_dds,
    compute_scope_channel_metrics,
    tx_wait_ack,
)
from hantek_usb.protocol import (
    Opcodes04440,
    ch_opcode,
    fun_04440,
    read_all_settings,
    scope_run_stop_stm32,
    work_type_packet,
)
from hantek_usb.transport import HantekLink


def _parse_waves(raw: str) -> List[int]:
    out: List[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok, 0))
    if not out:
        raise argparse.ArgumentTypeError("Debes pasar al menos un índice de onda.")
    return out


def _exercise_scope_options(
    link: HantekLink,
    cmd_sleep_s: float,
    *,
    skip_autoset: bool = False,
) -> None:
    """
    Envia una secuencia amplia de comandos de modo osciloscopio con pausas.
    Valores conservadores para minimizar riesgo de dejar el equipo en estado raro.

    Por defecto arranca con ``SCOPE_AUTOSET`` (0x13). Con ``skip_autoset=True`` se omite
    para probar sin re-autoajuste vertical/temporal del equipo.
    """
    if not skip_autoset:
        link.write(fun_04440(Opcodes04440.SCOPE_AUTOSET, 0, 1, False))
        if cmd_sleep_s > 0:
            time.sleep(cmd_sleep_s)

    link.write(scope_run_stop_stm32(True))
    time.sleep(0.12)
    if cmd_sleep_s > 0:
        time.sleep(cmd_sleep_s)

    ops: list[tuple[int, int, int]] = [
        (Opcodes04440.TIME_DIV, 8, 2),
        (Opcodes04440.YT_FORMAT, 0, 2),
        (Opcodes04440.TRIGGER_SOURCE, 0, 2),
        (Opcodes04440.TRIGGER_SLOPE, 0, 2),
        (Opcodes04440.TRIGGER_SWEEP, 0, 2),
        (Opcodes04440.TRIGGER_HPOS, 0x80, 3),
        (Opcodes04440.TRIGGER_VPOS, 0x40, 1),
        (ch_opcode(0, 0), 1, 1),
        (ch_opcode(0, 1), 0, 1),
        (ch_opcode(0, 2), 0, 1),
        (ch_opcode(0, 3), 0, 1),
        (ch_opcode(0, 4), 7, 1),
        (ch_opcode(0, 5), 0x80, 1),
    ]
    for opcode, value, payload_bytes in ops:
        try:
            _ = tx_wait_ack(
                link,
                fun_04440(opcode, value, payload_bytes, True),
                retries=2,
                sleep_s=max(0.2, cmd_sleep_s / 2),
            )
        except Exception as e:
            print(f"[warn] scope opcode 0x{opcode:02x} sin ack: {e}", file=sys.stderr)
        if cmd_sleep_s > 0:
            time.sleep(cmd_sleep_s)

    link.write(scope_run_stop_stm32(True))
    time.sleep(0.12)
    if cmd_sleep_s > 0:
        time.sleep(cmd_sleep_s)


def _run_once(
    *,
    wave: int,
    rep: int,
    freq: int,
    amp: int,
    dds_settle_s: float,
    scope_settle_s: float,
    count_a: int,
    count_b: int,
    clip_hi: int,
    clip_lo: int,
    exercise_scope: bool,
    scope_cmd_sleep_s: float,
    timeout_ms: int,
    interleaved: bool,
    metrics_channel: int,
    skip_autoset: bool,
) -> ScopeChannelMetrics:
    link = HantekLink(timeout_ms=timeout_ms)
    try:
        configure_dds(link, wave=wave, freq=freq, amp=amp, settle_s=dds_settle_s)
        if exercise_scope:
            link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
            if scope_cmd_sleep_s > 0:
                time.sleep(scope_cmd_sleep_s)
            _exercise_scope_options(
                link,
                cmd_sleep_s=scope_cmd_sleep_s,
                skip_autoset=skip_autoset,
            )
        raw = capture_scope_raw(link, count_a=count_a, count_b=count_b, settle_s=scope_settle_s)
        return compute_scope_channel_metrics(
            raw,
            wave=wave,
            rep=rep,
            clip_hi=clip_hi,
            clip_lo=clip_lo,
            interleaved=interleaved,
            metrics_channel=metrics_channel,
        )
    finally:
        link.close()


def _print_table(rows: Iterable[ScopeChannelMetrics]) -> None:
    print(
        "wave         rep  bytes  ch_min max   pp     mean   spiky  frac_mid  xings  "
        "ch_other(min..max)  status"
    )
    print("-----------------------------------------------------------------------------------------")
    for r in rows:
        status = "CLIPPED" if r.clipped else "OK"
        if r.interleaved and r.other_ch_min is not None:
            oth = f"{r.other_ch_min:>3d}..{r.other_ch_max:>3d}"
        else:
            oth = "—"
        print(
            f"{r.wave_name:11s} {r.rep:>3d}  {r.bytes_used:>5d}  {r.u8_min:>3d}  {r.u8_max:>3d}  "
            f"{r.pp:>6.1f}  {r.mean:>6.1f}  {r.spikiness:>6.2f}  {r.frac_mid:>8.3f}  "
            f"{r.mean_crossings:>5d}  {oth:>18s}  {status}"
        )


def _print_summary(rows: List[ScopeChannelMetrics]) -> int:
    print("")
    by_wave: dict[int, List[ScopeChannelMetrics]] = {}
    for r in rows:
        by_wave.setdefault(r.wave, []).append(r)

    had_clipped = False
    print("Resumen por onda:")
    for wave in sorted(by_wave):
        wrows = by_wave[wave]
        name = wrows[0].wave_name
        clipped_n = sum(1 for x in wrows if x.clipped)
        had_clipped = had_clipped or clipped_n > 0
        pp_avg = statistics.mean(x.pp for x in wrows)
        sp_avg = statistics.mean(x.spikiness for x in wrows)
        fm_avg = statistics.mean(x.frac_mid for x in wrows)
        print(
            f"- {name}: repeticiones={len(wrows)} clipped={clipped_n} "
            f"pp_avg={pp_avg:.1f} spiky_avg={sp_avg:.2f} frac_mid_avg={fm_avg:.3f}"
        )
    print("")
    if had_clipped:
        print("Resultado global: CLIPPED (baja amplitud DDS o ajusta V/div).")
        return 2
    print("Resultado global: OK (sin saturación detectada).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prueba DDS->OSC de coherencia (captura cruda USB + detector de clipping)."
    )
    p.add_argument("--waves", type=_parse_waves, default=[0, 1, 2, 3], help="Lista CSV de ondas, p.ej. 0,2,3")
    p.add_argument("--reps", type=int, default=2, help="Repeticiones por onda")
    p.add_argument("--freq", type=int, default=50, help="Frecuencia DDS (Hz)")
    p.add_argument("--amp", type=int, default=1200, help="Amplitud DDS (escala firmware)")
    p.add_argument("--dds-settle-ms", type=float, default=200.0, help="Espera tras configurar DDS")
    p.add_argument("--scope-settle-ms", type=float, default=80.0, help="Espera tras RUN antes de capturar")
    p.add_argument(
        "--exercise-scope-options",
        action="store_true",
        help="Ejecuta secuencia de comandos de modo osciloscopio (autoset, trigger, canal, time/div).",
    )
    p.add_argument(
        "--no-autoset",
        action="store_true",
        help="Con --exercise-scope-options: no enviar SCOPE_AUTOSET (0x13); el resto de la secuencia igual.",
    )
    p.add_argument(
        "--scope-cmd-sleep-ms",
        type=float,
        default=250.0,
        help="Pausa entre comandos de la secuencia de osciloscopio.",
    )
    p.add_argument(
        "--slow-profile",
        action="store_true",
        help="Ajusta esperas más largas para equipos que reaccionan lento.",
    )
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400, help="count_a para 0x16")
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0, help="count_b para 0x16")
    p.add_argument("--clip-hi", type=int, default=250, help="Umbral alto de clipping")
    p.add_argument("--clip-lo", type=int, default=5, help="Umbral bajo de clipping")
    p.add_argument("--timeout-ms", type=int, default=5000, help="Timeout USB por transferencia")
    p.add_argument(
        "--no-interleaved",
        action="store_true",
        help="Métricas sobre el buffer completo (un solo u8 por muestra); depuración.",
    )
    p.add_argument(
        "--metrics-ch",
        type=int,
        choices=(1, 2),
        default=1,
        help="Canal para pp/clipping (solo con buffer entrelazado; DDS suele ir a CH1).",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    waves = ns.waves if isinstance(ns.waves, list) else [ns.waves]
    if ns.reps < 1:
        print("Error: --reps debe ser >=1", file=sys.stderr)
        return 1

    if ns.slow_profile:
        ns.dds_settle_ms = max(ns.dds_settle_ms, 700.0)
        ns.scope_settle_ms = max(ns.scope_settle_ms, 450.0)
        ns.scope_cmd_sleep_ms = max(ns.scope_cmd_sleep_ms, 450.0)

    rows: List[ScopeChannelMetrics] = []
    try:
        for wave in waves:
            for rep in range(1, ns.reps + 1):
                row = _run_once(
                    wave=wave,
                    rep=rep,
                    freq=ns.freq,
                    amp=ns.amp,
                    dds_settle_s=max(0.0, ns.dds_settle_ms / 1000.0),
                    scope_settle_s=max(0.0, ns.scope_settle_ms / 1000.0),
                    count_a=ns.count_a,
                    count_b=ns.count_b,
                    clip_hi=ns.clip_hi,
                    clip_lo=ns.clip_lo,
                    exercise_scope=bool(ns.exercise_scope_options),
                    scope_cmd_sleep_s=max(0.0, ns.scope_cmd_sleep_ms / 1000.0),
                    timeout_ms=ns.timeout_ms,
                    interleaved=not ns.no_interleaved,
                    metrics_channel=ns.metrics_ch,
                    skip_autoset=bool(ns.no_autoset),
                )
                rows.append(row)
                print(
                    f"[ok] wave={row.wave_name} rep={row.rep} min={row.u8_min} "
                    f"max={row.u8_max} pp={row.pp:.1f} clipped={row.clipped}"
                )
    except KeyboardInterrupt:
        print("\nInterrumpido por usuario.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error en prueba: {e}", file=sys.stderr)
        return 1

    print("")
    _print_table(rows)
    return _print_summary(rows)


if __name__ == "__main__":
    raise SystemExit(main())
