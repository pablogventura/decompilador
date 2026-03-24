#!/usr/bin/env python3
"""
Barrido de ch-volt / ch-probe / amplitud DDS para encontrar captura sin clipping.

Uso típico (equipo lento):
  .venv/bin/python tools/dds_osc_sweep.py --slow-profile --wave 2 --volts 0:11 --probes 0,1 --amps 400,800,1200
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass
from typing import List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.capture import smart_source_data_capture
from hantek_usb.constants import DDS_WAVE_TYPE_LABELS, WORK_TYPE_OSCILLOSCOPE, WORK_TYPE_SIGNAL_GENERATOR
from hantek_usb.osc_decode import flatten_chunks, trim_to_expected
from hantek_usb.protocol import (
    Opcodes04440,
    OpcodesDDS,
    ch_opcode,
    dds_onoff_packet,
    dds_packet,
    dds_u16_packet,
    fun_04440,
    read_all_settings,
    scope_run_stop_stm32,
    work_type_packet,
)
from hantek_usb.transport import HantekLink


def _emit_noop(_s: str) -> None:
    return


def _tx_wait_ack(link: HantekLink, pkt: bytes, *, retries: int = 2, sleep_s: float = 0.25) -> bytes:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            link.write(pkt)
            return link.read64()
        except Exception as e:
            last = e
            if sleep_s > 0:
                time.sleep(sleep_s)
    assert last is not None
    raise last


def _parse_csv_ints(s: str) -> List[int]:
    out: List[int] = []
    for tok in s.split(","):
        tok = tok.strip()
        if tok:
            out.append(int(tok, 0))
    return out


def _parse_volt_arg(s: str) -> List[int]:
    s = s.strip()
    if ":" in s:
        a, b = s.split(":", 1)
        lo = int(a.strip(), 0)
        hi = int(b.strip(), 0)
        if hi < lo:
            lo, hi = hi, lo
        return list(range(lo, hi + 1))
    return _parse_csv_ints(s)


@dataclass
class SweepRow:
    volt: int
    probe: int
    amp: int
    u8_min: int
    u8_max: int
    pp: float
    mean: float
    clipped: bool
    ok_signal: bool
    rail_margin: int


def _rail_margin(lo: int, hi: int) -> int:
    """Distancia mínima a 0 o 255 (mayor = menos pegado a riel)."""
    return min(lo, 255 - hi)


def _capture_raw(
    link: HantekLink,
    count_a: int,
    count_b: int,
    scope_settle_s: float,
    timeout_ms: int,
) -> bytes:
    link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
    _ = _tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.12)
    if scope_settle_s > 0:
        time.sleep(scope_settle_s)
    chunks = smart_source_data_capture(
        link,
        count_a,
        count_b,
        blocks_fixed=64,
        smart=True,
        retry_max=30,
        sleep_ms=15,
        max_total_blocks=256,
        verbose=False,
        emit=_emit_noop,
        hex_fmt=lambda b: b.hex(),
    )
    expected = (count_a & 0xFFFF) + (count_b & 0xFFFF)
    return trim_to_expected(flatten_chunks(chunks), expected)


def _run_combo(
    *,
    wave: int,
    freq: int,
    amp: int,
    volt: int,
    probe: int,
    dds_settle_s: float,
    ch_settle_s: float,
    scope_settle_s: float,
    count_a: int,
    count_b: int,
    clip_hi: int,
    clip_lo: int,
    min_pp: float,
    timeout_ms: int,
) -> SweepRow:
    link = HantekLink(timeout_ms=timeout_ms)
    try:
        link.write(work_type_packet(WORK_TYPE_SIGNAL_GENERATOR, read=False))
        link.write(dds_u16_packet(OpcodesDDS.WAVE_TYPE, wave & 0xFFFF, read=False))
        link.write(dds_packet(OpcodesDDS.FREQUENCY, wait=False, u32_value=freq))
        link.write(dds_packet(OpcodesDDS.AMP, wait=False, u32_value=amp))
        link.write(dds_onoff_packet(True, read=False))
        if dds_settle_s > 0:
            time.sleep(dds_settle_s)

        link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
        if ch_settle_s > 0:
            time.sleep(ch_settle_s)

        _ = _tx_wait_ack(link, fun_04440(ch_opcode(0, 2), probe & 0xFF, 1, True), retries=2, sleep_s=0.2)
        if ch_settle_s > 0:
            time.sleep(ch_settle_s)
        _ = _tx_wait_ack(link, fun_04440(ch_opcode(0, 4), volt & 0xFF, 1, True), retries=2, sleep_s=0.2)
        if ch_settle_s > 0:
            time.sleep(ch_settle_s)

        raw = _capture_raw(link, count_a, count_b, scope_settle_s, timeout_ms)
        u = list(raw)
        mean = statistics.mean(u)
        xc = [x - mean for x in u]
        pp = float(max(xc) - min(xc))
        lo = min(u)
        hi = max(u)
        clipped = lo <= clip_lo or hi >= clip_hi
        ok_signal = (not clipped) and (pp >= min_pp)
        rm = _rail_margin(lo, hi)
        return SweepRow(
            volt=volt,
            probe=probe,
            amp=amp,
            u8_min=lo,
            u8_max=hi,
            pp=pp,
            mean=mean,
            clipped=clipped,
            ok_signal=ok_signal,
            rail_margin=rm,
        )
    finally:
        link.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Barrido ch-volt / ch-probe / amp DDS (anti-clipping).")
    p.add_argument("--wave", type=lambda x: int(x, 0), default=2, help="Índice DDS (default 2=seno)")
    p.add_argument("--freq", type=int, default=50, help="Hz")
    p.add_argument(
        "--volts",
        type=str,
        default="0:11",
        help="Lista CSV o rango inclusivo p.ej. 0:11 o 0,2,4,6",
    )
    p.add_argument("--probes", type=str, default="0,1", help="CSV de índices de sonda CH1")
    p.add_argument("--amps", type=str, default="400,800,1200,2000", help="CSV amplitudes DDS")
    p.add_argument("--dds-settle-ms", type=float, default=250.0)
    p.add_argument("--ch-settle-ms", type=float, default=350.0, help="Pausa tras modo OSC y tras ch-probe/ch-volt")
    p.add_argument("--scope-settle-ms", type=float, default=120.0)
    p.add_argument("--slow-profile", action="store_true", help="Esperas más largas")
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument("--clip-hi", type=int, default=250)
    p.add_argument("--clip-lo", type=int, default=5)
    p.add_argument("--min-pp", type=float, default=35.0, help="pp mínimo para considerar señal útil (no plana)")
    p.add_argument("--timeout-ms", type=int, default=8000)
    p.add_argument("--max-print", type=int, default=25, help="Máx. filas OK a listar")
    p.add_argument(
        "--also-rank-margin",
        action="store_true",
        help="Si no hay candidatos OK, lista las mejores por margen a rieles (min(min,255-max)).",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.slow_profile:
        ns.dds_settle_ms = max(ns.dds_settle_ms, 700.0)
        ns.ch_settle_ms = max(ns.ch_settle_ms, 500.0)
        ns.scope_settle_ms = max(ns.scope_settle_ms, 350.0)

    volts = _parse_volt_arg(ns.volts)
    probes = _parse_csv_ints(ns.probes)
    amps = _parse_csv_ints(ns.amps)
    if not volts or not probes or not amps:
        print("Error: --volts, --probes y --amps deben ser no vacíos.", file=sys.stderr)
        return 1

    wave_name = DDS_WAVE_TYPE_LABELS.get(ns.wave, str(ns.wave))
    print(
        f"Barrido: wave={wave_name} freq={ns.freq}Hz | volts={volts[0]}..{volts[-1]} "
        f"({len(volts)}) probes={probes} amps={amps}",
        file=sys.stderr,
    )
    print(
        f"clips: min<={ns.clip_lo} o max>={ns.clip_hi} | min_pp={ns.min_pp}",
        file=sys.stderr,
    )

    ok_rows: List[SweepRow] = []
    all_rows: List[SweepRow] = []
    total = len(volts) * len(probes) * len(amps)
    n = 0
    for amp in amps:
        for v in volts:
            for p in probes:
                n += 1
                try:
                    row = _run_combo(
                        wave=ns.wave,
                        freq=ns.freq,
                        amp=amp,
                        volt=v,
                        probe=p,
                        dds_settle_s=ns.dds_settle_ms / 1000.0,
                        ch_settle_s=ns.ch_settle_ms / 1000.0,
                        scope_settle_s=ns.scope_settle_ms / 1000.0,
                        count_a=ns.count_a,
                        count_b=ns.count_b,
                        clip_hi=ns.clip_hi,
                        clip_lo=ns.clip_lo,
                        min_pp=ns.min_pp,
                        timeout_ms=ns.timeout_ms,
                    )
                    status = "OK" if row.ok_signal else ("CLIP" if row.clipped else "LOW")
                    print(
                        f"[{n}/{total}] amp={amp} volt={v} probe={p} "
                        f"min={row.u8_min} max={row.u8_max} pp={row.pp:.1f} -> {status}",
                        file=sys.stderr,
                    )
                    if row.ok_signal:
                        ok_rows.append(row)
                    all_rows.append(row)
                except Exception as e:
                    print(f"[{n}/{total}] amp={amp} volt={v} probe={p} ERROR: {e}", file=sys.stderr)

    print("", file=sys.stderr)
    if not ok_rows:
        print(
            "Ninguna combinación pasó (sin clip + pp>=min_pp). "
            "Prueba: bajar --amps, ampliar --volts (más V/div en pantalla), "
            "o relajar --clip-hi/--clip-lo/--min-pp."
        )
        if ns.also_rank_margin and all_rows:
            ranked = sorted(all_rows, key=lambda r: (-r.rail_margin, -r.pp, r.amp, r.volt, r.probe))
            print("")
            print("Mejor margen a rieles (min(min, 255-max)) — útil si todo CLIP duro:")
            print("amp  volt  probe  min  max  margin  pp")
            print("------------------------------------------")
            for row in ranked[: min(15, len(ranked))]:
                print(
                    f"{row.amp:4d} {row.volt:4d} {row.probe:5d}  {row.u8_min:3d}  {row.u8_max:3d}  "
                    f"{row.rail_margin:6d}  {row.pp:5.1f}"
                )
        return 2

    ok_rows.sort(key=lambda r: (-r.pp, r.amp, r.volt, r.probe))
    print(f"Mejores candidatos (hasta {ns.max_print}), ordenados por pp descendente:")
    print("amp  volt  probe  min  max   pp     mean")
    print("--------------------------------------------")
    for row in ok_rows[: ns.max_print]:
        print(f"{row.amp:4d} {row.volt:4d} {row.probe:5d}  {row.u8_min:3d}  {row.u8_max:3d}  {row.pp:6.1f}  {row.mean:6.1f}")
    print("")
    best = ok_rows[0]
    print(
        "Sugerencia CLI (aprox.): "
        f"set-mode osc && ch-probe 0 {best.probe} && ch-volt 0 {best.volt}  "
        f"&& set-mode dds && dds-wave {ns.wave} --write-only && dds-amp {best.amp} --write-only && dds-onoff --on"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
