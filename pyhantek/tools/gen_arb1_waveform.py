#!/usr/bin/env python3
"""
Genera un blob ``dds-download`` (**--blob-variant short|long**) para **arb1** con una forma nueva.

Presets:

- **chirp** (default): barrido de frecuencia en un buffer de 512 puntos.
- **sine**: un seno (por defecto **1 ciclo** en el buffer; ajustable con ``--cycles``).
- **square**: cuadrada 50 % en un período (512 muestras: alto / bajo).
- **square_sharp**: misma idea pero **flancos cortos** (8 muestras lineales por subida/bajada) para
  mesetas largas y bordes más “duros” tras el filtro de salida.

La salida arb es **512 puntos** por buffer: entre muestras el AWG suele **mantener el nivel** (ZOH), así que la forma tiene **tramos horizontales** (escalera). Con **pico alto** en la tabla se ven más marcados; si además **`dds-amp`** está alto, la **cresta** puede **recortarse** y verse plana (saturación analógica). Para **seno** / **chirp**, la fase usa **i/(N−1)** para **no** introducir un **salto vertical** al repetir el buffer (wrap 511→0).

**Antes de `dds-download`:** el equipo debe estar en **modo generador** (`python -m hantek_usb.cli set-mode dds`). Luego: subir el `.bin`, `dds-wave 4`…`7`, `dds-fre`, `dds-amp`, `dds-onoff --on`. Si no, la salida puede verse **rota** o **cortada** (mismo orden que `tools/verify_arb_sine_scope.py`). Si pasás **osciloscopio ↔ AWG** en el mismo equipo y la forma **empeora**, **volvé a cargar** el `.bin` y esa secuencia (ver `HALLAZGOS_DMM_DDS_2026-03.md`).

  python tools/gen_arb1_waveform.py --preset chirp -o /tmp/arb1_chirp406.bin
  python tools/gen_arb1_waveform.py --preset sine -o /tmp/arb1_sine406.bin
  python tools/gen_arb1_waveform.py --preset square -o /tmp/arb1_square406.bin
  python tools/gen_arb1_waveform.py --preset sine --no-dll-float-pipeline -o /tmp/arb1_sine_int16.bin
  python -m hantek_usb.cli dds-download --short -f /tmp/arb1_sine406.bin
  python -m hantek_usb.cli dds-wave 4 --write-only
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.protocol import (
    DDS_ARB_NUM_SAMPLES,
    DDS_DOWNLOAD_SIZE_LONG,
    DDS_DOWNLOAD_SIZE_SHORT,
    build_dds_download_blob,
    dds_arb_samples_int16_le,
    float_samples_to_dds_int16,
)

# Fase en ``i/(N-1)`` (no ``i/N``): el AWG repite el buffer 0..511→0; con ``i/N`` el último
# punto no coincide con el primero y aparece un salto vertical cada período (foto “cortada”).
_N_ARB = DDS_ARB_NUM_SAMPLES
_PHASE_DEN = float(_N_ARB - 1)  # 511


def _samples_sine(*, peak: int, cycles: float) -> list[int]:
    """``cycles`` períodos en el buffer; fase ``2π·cycles·i/(N-1)`` para cierre sin discontinuidad."""
    out: list[int] = []
    for i in range(_N_ARB):
        phase = 2.0 * math.pi * cycles * (i / _PHASE_DEN)
        v = int(peak * math.sin(phase))
        v = max(-32768, min(32767, v))
        out.append(v)
    return out


def _samples_sine_dll_float(*, peak: float, cycles: float) -> list[int]:
    """Seno como ``ddsSDKDownload``: float → int16 con ``__ftol`` + saturación DLL."""
    fs = [
        float(peak) * math.sin(2.0 * math.pi * cycles * (i / _PHASE_DEN))
        for i in range(_N_ARB)
    ]
    return float_samples_to_dds_int16(fs)


def _samples_square_50(*, peak: int) -> list[int]:
    """Un período: mitad alto, mitad bajo (ideal para ver si el arb cambia la forma)."""
    hi = max(-32768, min(32767, peak))
    lo = max(-32768, min(32767, -peak))
    return [hi if i < 256 else lo for i in range(512)]


def _samples_square_sharp(*, peak: int, edge_samples: int = 8) -> list[int]:
    """
    Cuadrada ~50 %: mesetas 248 + 248 muestras, subida/bajada lineal en ``edge_samples`` (default 8).
    Total 248 + edge + 248 + edge = 512.
    """
    e = max(2, min(32, int(edge_samples)))
    plate = (512 - 2 * e) // 2
    hi = max(-32768, min(32767, peak))
    lo = max(-32768, min(32767, -peak))
    out: list[int] = []
    for i in range(512):
        if i < plate:
            out.append(lo)
        elif i < plate + e:
            t = (i - plate) / max(1, e - 1)
            out.append(int(lo + (hi - lo) * t))
        elif i < plate + e + plate:
            out.append(hi)
        elif i < plate + e + plate + e:
            t = (i - (plate + e + plate)) / max(1, e - 1)
            out.append(int(hi + (lo - hi) * t))
        else:
            out.append(lo)
    assert len(out) == 512
    return [max(-32768, min(32767, v)) for v in out]


def _samples_chirp_linear(*, peak: int, f0_cycles: float, f1_cycles: float) -> list[int]:
    """Fase φ(i)=2π·(f0·t + (f1-f0)·t²/2) con t=i/(N-1) → barrido; cierre suave en bordes del buffer."""
    out: list[int] = []
    for i in range(_N_ARB):
        t = i / _PHASE_DEN
        phase = 2.0 * math.pi * (f0_cycles * t + (f1_cycles - f0_cycles) * t * t / 2.0)
        v = int(peak * math.sin(phase))
        v = max(-32768, min(32767, v))
        out.append(v)
    return out


def _samples_chirp_linear_dll_float(
    *, peak: float, f0_cycles: float, f1_cycles: float
) -> list[int]:
    fs = []
    for i in range(_N_ARB):
        t = i / _PHASE_DEN
        phase = 2.0 * math.pi * (f0_cycles * t + (f1_cycles - f0_cycles) * t * t / 2.0)
        fs.append(float(peak) * math.sin(phase))
    return float_samples_to_dds_int16(fs)


def main() -> int:
    p = argparse.ArgumentParser(description="Genera 0x406 B para arb1 (chirp, seno o cuadrada).")
    p.add_argument(
        "--preset",
        choices=("chirp", "sine", "square", "square_sharp"),
        default="chirp",
        help="chirp | sine | square | square_sharp (default: chirp)",
    )
    p.add_argument(
        "--edge-samples",
        type=int,
        default=8,
        metavar="N",
        help="Solo square_sharp: muestras por flanco (rampa lineal, default 8)",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ruta del fichero de salida (default: arb1_chirp406.bin o arb1_sine406.bin según preset)",
    )
    p.add_argument(
        "--peak",
        type=int,
        default=32767,
        help=(
            "Pico int16 en la tabla (default 32767). Valores bajos se ven ‘achatados’ en el "
            "gráfico del AWG; valores ~32767 llenan la vista pero con ZOH (512 pts) se notan "
            "tramos horizontales y, si dds-amp es alto, la cresta puede recortarse: probá "
            "28000–30000 o bajá dds-amp."
        ),
    )
    p.add_argument(
        "--cycles",
        type=float,
        default=1.0,
        help="Solo preset sine: períodos en el buffer de 512 puntos (default 1)",
    )
    p.add_argument(
        "--f0",
        type=float,
        default=2.0,
        metavar="CYCLES",
        help="Solo preset chirp: ciclos ~ al inicio del buffer (default 2)",
    )
    p.add_argument(
        "--f1",
        type=float,
        default=28.0,
        metavar="CYCLES",
        help="Solo preset chirp: ciclos ~ al final del buffer (default 28)",
    )
    p.add_argument(
        "--blob-variant",
        choices=("short", "long"),
        default="long",
        help=(
            "short=0x406 (rama corta DLL); long=0x46C en bloques 64 B (rama larga si DAT…==0). "
            "Si arb1 no refleja la tabla, probá long (default)."
        ),
    )
    p.add_argument(
        "--no-dll-float-pipeline",
        action="store_true",
        help=(
            "Solo sine/chirp: usar int(peak*sin) en vez de float→int16 como "
            "`ddsSDKDownload` (`__ftol` + saturación). Por defecto se usa el pipeline DLL."
        ),
    )
    args = p.parse_args()

    _defaults = {
        "chirp": "arb1_chirp406.bin",
        "sine": "arb1_sine406.bin",
        "square": "arb1_square406.bin",
        "square_sharp": "arb1_square_sharp406.bin",
    }
    out_path = args.output if args.output is not None else _defaults[args.preset]

    use_dll = not args.no_dll_float_pipeline
    if args.preset == "sine":
        samples = (
            _samples_sine_dll_float(peak=float(args.peak), cycles=args.cycles)
            if use_dll
            else _samples_sine(peak=args.peak, cycles=args.cycles)
        )
    elif args.preset == "square":
        samples = _samples_square_50(peak=args.peak)
    elif args.preset == "square_sharp":
        samples = _samples_square_sharp(peak=args.peak, edge_samples=args.edge_samples)
    else:
        samples = (
            _samples_chirp_linear_dll_float(
                peak=float(args.peak), f0_cycles=args.f0, f1_cycles=args.f1
            )
            if use_dll
            else _samples_chirp_linear(peak=args.peak, f0_cycles=args.f0, f1_cycles=args.f1)
        )
    blob = build_dds_download_blob(
        dds_arb_samples_int16_le(samples),
        variant=args.blob_variant,
        arb_slot=0,
    )
    path = os.path.abspath(out_path)
    with open(path, "wb") as f:
        f.write(blob)
    exp = DDS_DOWNLOAD_SIZE_LONG if args.blob_variant == "long" else DDS_DOWNLOAD_SIZE_SHORT
    print(
        f"Preset {args.preset!r} variant={args.blob_variant!r} → {len(blob)} B (esperado {exp}) → {path}",
        file=sys.stderr,
    )
    print(f"Primeros 6 B: {blob[:6].hex()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
