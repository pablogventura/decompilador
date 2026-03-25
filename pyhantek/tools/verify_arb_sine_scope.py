#!/usr/bin/env python3
"""
Carga **arb1** con tabla senoidal (``dds-download`` + ``dds-wave 4``), pasa a osciloscopio
y mide: (1) correlación máxima vs ``sin(2π k i/N)``; (2) **rugosidad** ``max|Δ²u|/pp`` (sensible
a escalones/interpolación frente a un seno suave).

Compara con la onda **sine interna** (``dds-wave 2``).

Requiere **lazo físico** AWG → CH1 (o señal fuerte en CH1); sin eso la métrica no tiene sentido.

  python tools/verify_arb_sine_scope.py --bus 1 --address 9
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.constants import WORK_TYPE_SIGNAL_GENERATOR
from hantek_usb.dds_scope_helpers import capture_scope_raw, configure_dds
from hantek_usb.osc_decode import split_interleaved_u8
from hantek_usb.protocol import (
    OpcodesDDS,
    build_dds_download_blob,
    dds_arb_samples_int16_le,
    dds_onoff_packet,
    dds_packet,
    dds_u16_packet,
    work_type_packet,
)
from hantek_usb.transport import HantekLink


def _samples_sine_one_period(peak: int = 32767) -> list[int]:
    out: list[int] = []
    for i in range(512):
        # i/(N-1): cierre sin salto al repetir el buffer (mismo criterio que gen_arb1_waveform)
        v = int(peak * math.sin(2.0 * math.pi * i / 511.0))
        v = max(-32768, min(32767, v))
        out.append(v)
    return out


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 4 or n != len(b):
        return 0.0
    ma = sum(a) / n
    mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va < 1e-18 or vb < 1e-18:
        return 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / math.sqrt(va * vb)


def _best_sin_correlation(u: list[int]) -> tuple[float, float]:
    """
    Máx |ρ| entre u (centrada) y sin(2π k i / N), k en (0.25 .. 48) paso 0.25.
    Devuelve (|ρ|_max, k_mejor).
    """
    n = len(u)
    if n < 32:
        return 0.0, 0.0
    xc = [float(x - sum(u) / n) for x in u]
    best_r = 0.0
    best_k = 0.0
    k = 0.25
    while k <= 48.0:
        s = [math.sin(2.0 * math.pi * k * i / n) for i in range(n)]
        r = abs(_pearson(xc, s))
        if r > best_r:
            best_r = r
            best_k = k
        k += 0.25
    return best_r, best_k


def _roughness_max_d2_over_pp(u: list[int]) -> float:
    """Mayor segunda diferencia normalizada por pico-pico (proxy de ‘no suave’ / escalones)."""
    n = len(u)
    if n < 5:
        return 0.0
    mu = sum(u) / n
    xc = [float(x - mu) for x in u]
    pp = max(xc) - min(xc) + 1e-9
    d2 = [
        abs(xc[i + 1] - 2.0 * xc[i] + xc[i - 1])
        for i in range(1, n - 1)
    ]
    return max(d2) / pp


def _run(
    *,
    bus: int | None,
    address: int | None,
    freq: int,
    amp: int,
    count_a: int,
    settle_dds: float,
    settle_scope: float,
) -> None:
    blob = build_dds_download_blob(
        dds_arb_samples_int16_le(_samples_sine_one_period()),
        variant="long",
        arb_slot=0,
    )

    link = HantekLink(bus=bus, address=address)
    try:

        def arb_then_capture(label: str, wave: int) -> tuple[float, float, float]:
            link.write(work_type_packet(WORK_TYPE_SIGNAL_GENERATOR, read=False))
            link.write(blob)
            time.sleep(0.05)
            link.write(dds_u16_packet(OpcodesDDS.WAVE_TYPE, wave & 0xFFFF, read=False))
            link.write(dds_packet(OpcodesDDS.FREQUENCY, wait=False, u32_value=freq))
            link.write(dds_packet(OpcodesDDS.AMP, wait=False, u32_value=amp))
            link.write(dds_onoff_packet(True, read=False))
            time.sleep(settle_dds)
            raw = capture_scope_raw(
                link,
                count_a=count_a,
                count_b=0,
                settle_s=settle_scope,
            )
            ch1, ch2 = split_interleaved_u8(raw)
            u = ch1 if ch1 else list(raw)
            r, k = _best_sin_correlation(u)
            rough = _roughness_max_d2_over_pp(u)
            extra = (
                f"  CH2_minmax=({min(ch2)},{max(ch2)})"
                if ch2
                else ""
            )
            print(
                f"{label}: muestras_CH1={len(u)}  |ρ|_max(sin)={r:.4f}  "
                f"k≈{k:.2f}  rug=max|Δ²|/pp={rough:.5f}{extra}",
                file=sys.stderr,
            )
            return r, k, rough

        # Onda interna (referencia)
        configure_dds(link, wave=2, freq=freq, amp=amp, settle_s=settle_dds)
        raw0 = capture_scope_raw(
            link,
            count_a=count_a,
            count_b=0,
            settle_s=settle_scope,
        )
        c1, _ = split_interleaved_u8(raw0)
        u0 = c1 if c1 else list(raw0)
        r_int, k_int = _best_sin_correlation(u0)
        rough_int = _roughness_max_d2_over_pp(u0)
        print(
            f"Referencia wave=2 (sine interno): |ρ|={r_int:.4f}  k≈{k_int:.2f}  "
            f"rug=max|Δ²|/pp={rough_int:.5f}",
            file=sys.stderr,
        )

        # Arb1 tabla seno
        r_arb, k_arb, rough_arb = arb_then_capture("arb1 tabla seno (wave=4)", 4)

        print("", file=sys.stderr)
        print(
            "Interpretación: |ρ| alto pero la pantalla puede mostrar otra cosa (pixels, persistencia); "
            "rug↑ vs referencia sugiere más ‘dientes’/segmentación en el arb.",
            file=sys.stderr,
        )
        print(f"wave2_sine  |ρ|={r_int:.4f}  rug={rough_int:.5f}")
        print(f"arb1_sine   |ρ|={r_arb:.4f}  rug={rough_arb:.5f}")
        if r_arb < r_int - 0.05:
            print("Conclusión: |ρ| arb1 claramente peor que seno interno.")
        elif r_arb < 0.85:
            print("Conclusión: captura CH1 poco sinusoidal (|ρ|<0.85).")
        elif rough_arb > rough_int * 1.15:
            print(
                "Conclusión: aunque |ρ| sea alto, la captura arb1 es **menos suave** que el seno interno "
                f"(rug {rough_arb:.5f} > {rough_int:.5f}×1.15): puede no ‘verse’ como seno en pantalla."
            )
        else:
            print(
                "Conclusión: en USB, arb1 ≈ seno interno en estas métricas; si en pantalla no lo es, "
                "revisá lazo CH1, V/div, base de tiempos o efecto visual del LCD."
            )

    finally:
        link.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Compara seno interno vs arb1 senoidal en captura scope.")
    p.add_argument("--bus", type=int, default=None)
    p.add_argument("--address", type=int, default=None)
    p.add_argument("--freq", type=int, default=1000)
    p.add_argument("--amp", type=int, default=4000)
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x1000)
    p.add_argument("--dds-settle", type=float, default=0.35)
    p.add_argument("--scope-settle", type=float, default=0.2)
    args = p.parse_args()
    try:
        _run(
            bus=args.bus,
            address=args.address,
            freq=args.freq,
            amp=args.amp,
            count_a=args.count_a,
            settle_dds=args.dds_settle,
            settle_scope=args.scope_settle,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
