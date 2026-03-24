#!/usr/bin/env python3
"""
Lectura de osciloscopio con secuencia conservadora (pausas largas) y pistas del firmware:

- Tras encender el equipo: espera opcional (--power-on-wait).
- Modo osciloscopio, read-settings, base de tiempos y disparo en CH1, RUN, pausa, captura 0x16
  (un OUT por trozo, como FUN_08032140).
- Opcional: DDS interno (--dds) para señal conocida en CH1.

Ejemplo:
  .venv/bin/python tools/scope_read_enhanced.py --slow --analyze
  .venv/bin/python tools/scope_read_enhanced.py --slow --dds --wave 2 --freq 50 --dds-amp 800 --analyze
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.capture import smart_source_data_capture
from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE, WORK_TYPE_SIGNAL_GENERATOR
from hantek_usb.osc_decode import (
    flatten_chunks,
    format_analyze_report,
    format_capture_summary,
    trim_to_expected,
)
from hantek_usb.protocol import (
    Opcodes04440,
    OpcodesDDS,
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


def _tx_wait_ack(link: HantekLink, pkt: bytes) -> bytes:
    link.write(pkt)
    return link.read64()


def main() -> int:
    p = argparse.ArgumentParser(description="Captura scope con secuencia lenta y análisis.")
    p.add_argument("--slow", action="store_true", help="Esperas largas (equipo reactivo lento)")
    p.add_argument("--power-on-wait-s", type=float, default=0.0, help="Espera inicial si acabas de encender")
    p.add_argument("--timeout-ms", type=int, default=9000)
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument("--analyze", action="store_true", help="Métricas heurísticas sobre el payload")
    p.add_argument("--time-div", type=int, default=8, help="Valor ushort p.dsoHTSetTimeDiv (heurística)")
    p.add_argument("--pre-scope-s", type=float, default=None, help="Pausa tras modo OSC (default según --slow)")
    p.add_argument("--after-run-s", type=float, default=None, help="Pausa tras RUN antes de 0x16")
    p.add_argument("--dds", action="store_true", help="Configurar DDS y salida ON antes del scope")
    p.add_argument("--wave", type=lambda x: int(x, 0), default=2)
    p.add_argument("--freq", type=int, default=50)
    p.add_argument("--dds-amp", type=int, default=800)
    ns = p.parse_args()

    pre = ns.pre_scope_s if ns.pre_scope_s is not None else (1.2 if ns.slow else 0.35)
    post = ns.after_run_s if ns.after_run_s is not None else (0.6 if ns.slow else 0.12)

    if ns.power_on_wait_s > 0:
        time.sleep(ns.power_on_wait_s)

    link = HantekLink(timeout_ms=ns.timeout_ms)
    try:
        if ns.dds:
            link.write(work_type_packet(WORK_TYPE_SIGNAL_GENERATOR, read=False))
            link.write(dds_u16_packet(OpcodesDDS.WAVE_TYPE, ns.wave & 0xFFFF, read=False))
            link.write(dds_packet(OpcodesDDS.FREQUENCY, wait=False, u32_value=ns.freq))
            link.write(dds_packet(OpcodesDDS.AMP, wait=False, u32_value=ns.dds_amp))
            link.write(dds_onoff_packet(True, read=False))
            time.sleep(0.5 if ns.slow else 0.2)

        link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
        time.sleep(pre)

        _ = _tx_wait_ack(link, read_all_settings())
        _ = _tx_wait_ack(link, fun_04440(Opcodes04440.TIME_DIV, ns.time_div & 0xFFFF, 2, True))
        time.sleep(0.2 if ns.slow else 0.08)
        _ = _tx_wait_ack(link, fun_04440(Opcodes04440.TRIGGER_SOURCE, 0, 2, True))
        time.sleep(0.2 if ns.slow else 0.08)
        _ = _tx_wait_ack(link, fun_04440(Opcodes04440.TRIGGER_SWEEP, 0, 2, True))
        time.sleep(0.2 if ns.slow else 0.08)
        link.write(scope_run_stop_stm32(True))
        time.sleep(0.15 if ns.slow else 0.08)
        time.sleep(post)

        chunks = smart_source_data_capture(
            link,
            ns.count_a,
            ns.count_b,
            blocks_fixed=64,
            smart=True,
            retry_max=40,
            sleep_ms=20 if ns.slow else 15,
            max_total_blocks=256,
            verbose=False,
            emit=_emit_noop,
            hex_fmt=lambda b: b.hex(),
        )
        expected = (ns.count_a & 0xFFFF) + (ns.count_b & 0xFFFF)
        raw = trim_to_expected(flatten_chunks(chunks), expected)
        print(format_capture_summary(chunks, expected_bytes=expected))
        if ns.analyze:
            print(format_analyze_report(raw))
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
