#!/usr/bin/env python3
"""
Humo de osciloscopio con **señal externa en CH1** (p. ej. generador de banco).

Configura modo scope, disparo **Auto**, fuente **CH1**, RUN, captura ``0x16`` y resume
métricas + frecuencia **heurística** (ver ``hantek_usb.scope_signal_metrics``). Con ``--scope-autoset``, el JSON incluye ``settings_autoset_diff`` (cambios en ``fields_u8``).

Códigos de salida:

- **0** — señal “viva” (sin clipping según umbrales, cruces > mínimo, y ``--expect-hz`` OK si aplica).
- **1** — fallo USB / read-settings inválido / argumentos.
- **2** — señal plana, saturada o sin cruces suficientes.
- **3** — ``--expect-hz`` fuera de tolerancia.

Ejemplos::

  cd pyhantek && .venv/bin/python tools/external_ch1_smoke.py
  .venv/bin/python tools/external_ch1_smoke.py --expect-hz 1000 --expect-tol 0.25 --json
  .venv/bin/python tools/external_ch1_smoke.py --scope-autoset --json -o /tmp/ch1.json

Ver también: ``scope_autoset_soft.py --no-dds``, ``dds_osc_coherence.py`` (lazo interno AWG).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb import constants
from hantek_usb import parse_resp
from hantek_usb.dds_scope_helpers import (
    capture_scope_raw,
    compute_scope_channel_metrics,
    tx_wait_ack,
)
from hantek_usb.osc_decode import split_interleaved_u8
from hantek_usb.protocol import (
    Opcodes04440,
    fun_04440,
    read_all_settings,
    scope_run_stop_stm32,
    work_type_packet,
)
from hantek_usb.scope_signal_metrics import (
    diff_read_settings_summaries,
    estimate_frequency_hz_for_ch1_samples,
    read_settings_fields_summary,
)
from hantek_usb.transport import HantekLink


def _read_settings_dec(link: HantekLink) -> Dict[str, Any]:
    link.write(read_all_settings())
    rsp = link.read64()
    return parse_resp.decode_read_all_set_firmware25(rsp)


def _scope_baseline(
    link: HantekLink,
    *,
    time_div: int,
    slow: bool,
) -> None:
    pre = 1.2 if slow else 0.35
    post = 0.6 if slow else 0.12
    sl = 0.25 if slow else 0.15
    link.write(work_type_packet(constants.WORK_TYPE_OSCILLOSCOPE, read=False))
    time.sleep(pre)
    _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TIME_DIV, time_div & 0xFFFF, 2, True),
        retries=2,
        sleep_s=sl,
    )
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TRIGGER_SOURCE, 0, 2, True),
        retries=2,
        sleep_s=sl,
    )
    _ = tx_wait_ack(
        link,
        fun_04440(Opcodes04440.TRIGGER_SWEEP, 0, 2, True),
        retries=2,
        sleep_s=sl,
    )
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.15 if slow else 0.08)
    time.sleep(post)


def _run(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    out: Dict[str, Any] = {"ok": False, "errors": []}
    link = HantekLink(
        vid=args.vid,
        pid=args.pid,
        bus=args.bus,
        address=args.address,
        timeout_ms=args.timeout_ms,
    )
    try:
        _scope_baseline(link, time_div=args.time_div, slow=args.slow)
        dec_before = _read_settings_dec(link)
        if not dec_before.get("valid_layout"):
            out["errors"].append("read-settings inicial no decodificable (¿modo scope?)")
            return 1, out
        ram98_b3 = int(dec_before["fields"]["ram98_byte3"]["u8"])
        out["settings_before"] = read_settings_fields_summary(dec_before)

        if args.scope_autoset:
            link.write(fun_04440(Opcodes04440.SCOPE_AUTOSET, 0, 1, False))
            time.sleep(max(args.autoset_wait_s, 0.1))
            dec_after_as = _read_settings_dec(link)
            sum_before = out["settings_before"]
            sum_after = read_settings_fields_summary(dec_after_as)
            out["settings_after_autoset"] = sum_after
            out["settings_autoset_diff"] = diff_read_settings_summaries(sum_before, sum_after)
            if dec_after_as.get("valid_layout"):
                ram98_b3 = int(dec_after_as["fields"]["ram98_byte3"]["u8"])

        raw = capture_scope_raw(
            link,
            args.count_a,
            args.count_b,
            args.scope_settle_s,
            smart_sleep_ms=args.smart_sleep_ms,
        )
        ch1, _ch2 = split_interleaved_u8(raw)
        m = compute_scope_channel_metrics(
            raw,
            wave=-1,
            rep=0,
            clip_hi=args.clip_hi,
            clip_lo=args.clip_lo,
            interleaved=True,
            metrics_channel=1,
        )
        hz_est, spd = estimate_frequency_hz_for_ch1_samples(
            ch1,
            ram98_byte3=ram98_b3,
            horizontal_divisions=args.horizontal_divs,
        )

        out["metrics"] = {
            "bytes": m.bytes_used,
            "ch1_u8_min": m.u8_min,
            "ch1_u8_max": m.u8_max,
            "pp": m.pp,
            "mean": m.mean,
            "mean_crossings": m.mean_crossings,
            "clipped": m.clipped,
            "freq_hz_est": hz_est,
            "seconds_per_div_est": spd,
            "ram98_byte3": ram98_b3,
        }

        # Fallos de señal
        if m.clipped:
            out["errors"].append("clipping_ADC")
        if m.pp < float(args.min_pp):
            out["errors"].append("señal_muy_plana_pp")
        if m.mean_crossings < int(args.min_crossings):
            out["errors"].append("pocos_cruces_por_media")

        if out["errors"]:
            out["ok"] = False
            return 2, out

        if args.expect_hz is not None:
            if hz_est is None:
                out["errors"].append("sin_frecuencia_estimada")
                return 2, out
            tol = float(args.expect_tol)
            lo = args.expect_hz * (1.0 - tol)
            hi = args.expect_hz * (1.0 + tol)
            if not (lo <= hz_est <= hi):
                out["errors"].append(
                    f"expect_hz fuera de rango: est={hz_est:.4g} Hz, esperado {args.expect_hz} ±{tol*100:.0f}%"
                )
                return 3, out

        out["ok"] = True
        return 0, out
    except Exception as e:
        out["errors"].append(f"exception: {type(e).__name__}: {e}")
        return 1, out
    finally:
        try:
            link.close()
        except Exception:
            pass


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Humo CH1 con señal externa: métricas + frecuencia heurística.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--vid", type=lambda x: int(x, 0), default=constants.VID_HANTEK_2XX2)
    p.add_argument("--pid", type=lambda x: int(x, 0), default=constants.DEFAULT_PID_HANTEK)
    p.add_argument("--bus", type=int, default=None)
    p.add_argument("--address", type=int, default=None)
    p.add_argument("--timeout-ms", type=int, default=5000)
    p.add_argument("--time-div", type=lambda x: int(x, 0), default=16, help="Índice TIME_DIV inicial (default 16 ≈ 1 ms/div)")
    p.add_argument("--slow", action="store_true", help="Esperas más largas (USB lento)")
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument("--scope-settle-s", type=float, default=0.12)
    p.add_argument("--smart-sleep-ms", type=int, default=15)
    p.add_argument("--clip-hi", type=int, default=250)
    p.add_argument("--clip-lo", type=int, default=5)
    p.add_argument("--min-pp", type=float, default=4.0, help="Mínimo pico-pico (u8 centrado en media) para no marcar plano")
    p.add_argument("--min-crossings", type=int, default=2, help="Mínimo de cruces por la media en CH1")
    p.add_argument(
        "--horizontal-divs",
        type=float,
        default=10.0,
        help="Divisiones horizontales asumidas para estimar Hz (heurística)",
    )
    p.add_argument("--expect-hz", type=float, default=None, metavar="HZ")
    p.add_argument("--expect-tol", type=float, default=0.20, help="Tolerancia relativa para --expect-hz (0.2 = ±20%%)")
    p.add_argument("--scope-autoset", action="store_true", help="Enviar opcode 0x13 antes de capturar")
    p.add_argument("--autoset-wait-s", type=float, default=1.5)
    p.add_argument("--json", action="store_true")
    p.add_argument("-o", "--output", type=str, default=None, help="Escribir JSON a archivo")

    args = p.parse_args(argv)
    code, payload = _run(args)
    if args.json or args.output:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.output:
            open(args.output, "w", encoding="utf-8").write(text + "\n")
        if args.json:
            print(text)
    else:
        m = payload.get("metrics") or {}
        print(
            f"CH1  bytes={m.get('bytes')}  min..max={m.get('ch1_u8_min')}..{m.get('ch1_u8_max')}  "
            f"pp={m.get('pp', 0):.1f}  crossings={m.get('mean_crossings')}  "
            f"clipped={m.get('clipped')}  f_est={m.get('freq_hz_est')} Hz  "
            f"ram98_b3={m.get('ram98_byte3')}"
        )
        if payload.get("errors"):
            for e in payload["errors"]:
                print(f"ERROR: {e}", file=sys.stderr)
        elif code == 0:
            print("OK")
        diff = payload.get("settings_autoset_diff")
        if diff is not None:
            print(f"Autoset: {len(diff)} campo(s) distinto(s) en read-settings")
            for row in diff[:12]:
                o, n = row["old"], row["new"]
                so = "?" if o < 0 else f"0x{o:02x}"
                sn = "?" if n < 0 else f"0x{n:02x}"
                print(f"  {row['field']}: {so} → {sn}")
            if len(diff) > 12:
                print(f"  … ({len(diff) - 12} más)")

    return code


if __name__ == "__main__":
    raise SystemExit(main())
