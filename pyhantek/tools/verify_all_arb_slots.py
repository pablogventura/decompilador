#!/usr/bin/env python3
"""
Prueba **arb1–arb4** (slots 0..3, ``dds-wave`` 4..7): sube una tabla **seno** distinta por slot
(distintos ciclos en el buffer para diferenciar), captura por USB en modo osciloscopio y reporta
**min/max/pp** en CH1.

Requiere **lazo físico** AWG → CH1 (igual que ``verify_arb_sine_scope.py``).

  ./.venv/bin/python tools/verify_all_arb_slots.py
  ./.venv/bin/python tools/verify_all_arb_slots.py --bus 1 --address 13 --freq 800 --amp 3500
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.constants import WORK_TYPE_SIGNAL_GENERATOR, VID_HANTEK_2XX2
from hantek_usb.dds_scope_helpers import capture_scope_raw
from hantek_usb.osc_decode import split_interleaved_u8
from hantek_usb.protocol import (
    DDS_ARB_NUM_SAMPLES,
    OpcodesDDS,
    build_dds_download_blob,
    dds_arb_samples_int16_le,
    dds_onoff_packet,
    dds_packet,
    dds_u16_packet,
    work_type_packet,
)
from hantek_usb.transport import HantekLink

_PHASE_DEN = float(DDS_ARB_NUM_SAMPLES - 1)


def _sine_buffer(*, peak: int, cycles: float) -> list[int]:
    out: list[int] = []
    for i in range(DDS_ARB_NUM_SAMPLES):
        ph = 2.0 * math.pi * cycles * (i / _PHASE_DEN)
        v = int(peak * math.sin(ph))
        out.append(max(-32768, min(32767, v)))
    return out


def _metrics_ch1(raw: bytes) -> tuple[int, int, int]:
    ch1, ch2 = split_interleaved_u8(raw)
    u = ch1 if ch1 else list(raw)
    if not u:
        return 0, 0, 0
    lo, hi = min(u), max(u)
    return lo, hi, hi - lo


def main() -> int:
    p = argparse.ArgumentParser(description="Verifica arb1..arb4 subiendo tablas y capturando scope.")
    p.add_argument("--bus", type=int, default=None)
    p.add_argument("--address", type=int, default=None)
    p.add_argument("--pid", type=lambda x: int(x, 0), default=0x2D42)
    p.add_argument("--vid", type=lambda x: int(x, 0), default=VID_HANTEK_2XX2)
    p.add_argument("--freq", type=int, default=1000)
    p.add_argument("--amp", type=int, default=4000)
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x1000)
    p.add_argument("--dds-settle", type=float, default=0.35)
    p.add_argument("--scope-settle", type=float, default=0.22)
    p.add_argument("--peak", type=int, default=28000, help="Pico int16 en la tabla por slot")
    args = p.parse_args()

    link = HantekLink(
        vid=args.vid,
        pid=args.pid,
        bus=args.bus,
        address=args.address,
    )
    try:
        print(
            "slot  wave  cycles_buf  CH1_min  CH1_max  pp   (lazo AWG→CH1; si pp≈0 revisá cable/modo)",
            file=sys.stderr,
        )
        for slot in range(4):
            cycles = float(slot + 1)  # 1..4 ciclos en 512 pts → formas distintas
            samples = _sine_buffer(peak=args.peak, cycles=cycles)
            blob = build_dds_download_blob(
                dds_arb_samples_int16_le(samples),
                variant="long",
                arb_slot=slot,
            )
            wave = 4 + slot
            link.write(work_type_packet(WORK_TYPE_SIGNAL_GENERATOR, read=False))
            link.write(blob)
            time.sleep(0.06)
            link.write(dds_u16_packet(OpcodesDDS.WAVE_TYPE, wave & 0xFFFF, read=False))
            link.write(dds_packet(OpcodesDDS.FREQUENCY, wait=False, u32_value=args.freq))
            link.write(dds_packet(OpcodesDDS.AMP, wait=False, u32_value=args.amp))
            link.write(dds_onoff_packet(True, read=False))
            time.sleep(args.dds_settle)
            raw = capture_scope_raw(
                link,
                args.count_a,
                0,
                args.scope_settle,
            )
            lo, hi, pp = _metrics_ch1(raw)
            flag = "OK" if pp > 12 else "FLAT?"
            print(
                f"  {slot}    {wave}      {cycles:.0f}        {lo:3d}     {hi:3d}    {pp:3d}   {flag}",
                file=sys.stderr,
            )
        print("", file=sys.stderr)
        print("Si los cuatro pp son razonables y distintos entre sí, arb1..arb4 cargan y seleccionan bien.")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
