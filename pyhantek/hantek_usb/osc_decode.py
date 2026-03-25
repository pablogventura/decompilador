"""
Decodificación básica de bloques de captura de osciloscopio.

No intenta reemplazar HTSoftDll: resume la captura bulk y expone muestras crudas.

Pistas firmware (FUN_08032140 @ 08032140): si el buffer de muestras no está listo,
se responden 12 B con un patrón fijo antes de FUN_080342e0; las muestras reales son
bytes sueltos desde DAT_08032e78 + offset, hasta 0x40 B por petición 0x16.

**Dos canales (2xx2):** en hardware real, el buffer suele venir como **CH1, CH2, CH1, CH2…**
(un byte por canal y por instante). Tratar todo el flujo como una sola curva u8
distorsiona métricas y gráficos. Por defecto esta API asume ese entrelazado
(ver ``split_interleaved_u8``); para un solo canal o depuración, desactivá el
modo entrelazado en CLI / export.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Dict, List, Optional

# Respuesta "no listo" en rama FUN_08032140 cuando FUN_0801115e devuelve -1 (buffer vacío).
FIRMWARE_NOT_READY_12: bytes = bytes(
    [
        0x00,
        0x00,
        0xFF,
        0xFF,
        0x00,
        0x00,
        0xFF,
        0xFF,
        0x00,
        0x00,
        0xFF,
        0xFF,
    ]
)


def firmware_buffer_not_ready(block: bytes) -> bool:
    """True si los primeros 12 B coinciden con la rama de error del firmware (captura no lista)."""
    return len(block) >= 12 and block[:12] == FIRMWARE_NOT_READY_12


def flatten_chunks(chunks: List[bytes]) -> bytes:
    return b"".join(chunks)


def trim_to_expected(data: bytes, expected_bytes: int | None) -> bytes:
    if expected_bytes is None:
        return data
    n = max(0, int(expected_bytes))
    if n == 0:
        return data
    return data[:n]


def split_interleaved_u8(payload: bytes) -> tuple[list[int], list[int]]:
    """
    Buffer **u8** en modo dos canales: **CH1, CH2, CH1, CH2…** (un byte por canal
    e instante). Comportamiento **validado** en 2xx2 al comparar con la vista en vivo.

    Devuelve (CH1, CH2) como listas tomando índices pares / impares del buffer.
    Si la longitud es impar, el último byte solo entra en CH1.
    """
    if not payload:
        return [], []
    a = list(payload[0::2])
    b = list(payload[1::2])
    return a, b


def decode_capture(chunks: List[bytes], expected_bytes: int | None = None) -> Dict[str, object]:
    raw = flatten_chunks(chunks)
    used = trim_to_expected(raw, expected_bytes)
    u8 = list(used)
    i8 = [v - 256 if v > 127 else v for v in u8]
    first = chunks[0] if chunks else b""
    out: Dict[str, object] = {
        "blocks": len(chunks),
        "bytes_total": len(raw),
        "bytes_used": len(used),
        "expected_bytes": expected_bytes,
        "u8_min": min(u8) if u8 else None,
        "u8_max": max(u8) if u8 else None,
        "i8_min": min(i8) if i8 else None,
        "i8_max": max(i8) if i8 else None,
        "preview_u8": u8[:32],
        "firmware_not_ready_first_chunk": bool(first) and firmware_buffer_not_ready(first),
    }
    return out


def format_capture_summary(
    chunks: List[bytes],
    expected_bytes: int | None = None,
    *,
    interleaved: bool = True,
) -> str:
    d = decode_capture(chunks, expected_bytes=expected_bytes)
    lines: List[str] = []
    lines.append(
        f"Captura scope: bloques={d['blocks']} bytes_total={d['bytes_total']} bytes_usados={d['bytes_used']}"
    )
    if d.get("expected_bytes") is not None:
        lines.append(f"  bytes esperados (firmware): {d['expected_bytes']}")
    lines.append(
        f"  rango u8 (stream completo): {d['u8_min']}..{d['u8_max']} | rango i8: {d['i8_min']}..{d['i8_max']}"
    )
    if interleaved:
        used = trim_to_expected(flatten_chunks(chunks), expected_bytes)
        ch1, ch2 = split_interleaved_u8(used)
        if ch1 or ch2:
            lines.append(
                f"  modo 2 canales (pares=CH1, impares=CH2): "
                f"CH1 n={len(ch1)} [{min(ch1) if ch1 else '-'}..{max(ch1) if ch1 else '-'}]  "
                f"CH2 n={len(ch2)} [{min(ch2) if ch2 else '-'}..{max(ch2) if ch2 else '-'}]"
            )
    if d.get("firmware_not_ready_first_chunk"):
        lines.append(
            "  primer bloque: patrón firmware «buffer no listo» (12 B) — reintenta captura o espera RUN."
        )
    lines.append(f"  preview_u8[0:32]: {d['preview_u8']}")
    lines.append(
        "  Nota: ADC crudo sin V; tiempo real depende de time/div. "
        "Sin --no-interleaved: CSV y --analyze usan CH1/CH2 separados."
    )
    return "\n".join(lines)


def analyze_adc_payload(raw: bytes) -> Dict[str, object]:
    """
    Métricas heurísticas sobre muestras u8 ADC (sin calibración a voltios).
    Útil para detectar saturación, señal plana o poco uso del rango.
    """
    u = list(raw)
    n = len(u)
    if n == 0:
        return {"error": "vacío", "n": 0}

    lo = min(u)
    hi = max(u)
    span = hi - lo
    mean = statistics.mean(u)

    sat_lo = sum(1 for x in u if x <= 5)
    sat_hi = sum(1 for x in u if x >= 250)
    sat_frac = (sat_lo + sat_hi) / n

    # Muestras en zona "útil" típica (evita rieles)
    mid_band = sum(1 for x in u if 40 <= x <= 215) / n

    # Variación local (derivada discreta)
    diffs = [u[i + 1] - u[i] for i in range(n - 1)]
    absd = [abs(d) for d in diffs]
    dmean = statistics.mean(absd) if absd else 0.0
    dmax = max(absd) if absd else 0.0
    spikiness = dmax / (dmean + 1e-9)

    # RMS en torno a la media (AC aproximado)
    xc = [x - mean for x in u]
    rms_ac = math.sqrt(sum(x * x for x in xc) / n)

    # Puntuación 0..100: penaliza saturación y señal plana
    if span <= 1:
        quality = 0.0
    else:
        quality = min(100.0, (span / 255.0) * 60.0 + mid_band * 40.0)
        quality *= max(0.0, 1.0 - min(1.0, sat_frac * 3.0))

    return {
        "n": n,
        "u8_min": lo,
        "u8_max": hi,
        "pp": float(span),
        "mean": mean,
        "sat_frac": sat_frac,
        "sat_lo": sat_lo,
        "sat_hi": sat_hi,
        "mid_band_frac": mid_band,
        "rms_ac": rms_ac,
        "mean_abs_diff": dmean,
        "spikiness": spikiness,
        "quality_0_100": round(quality, 1),
    }


def export_scope_csv(
    path: str | Path,
    payload: bytes,
    *,
    dt_seconds: float = 1.0,
    interleaved: bool = True,
) -> int:
    """
    Escribe CSV para gráficos (LibreOffice, gnuplot).

    Con ``interleaved=True`` (default): columnas ``index,time_s,ch1_u8,ch2_u8`` —
    un instante por fila, dos canales (validado en 2xx2).

    Con ``interleaved=False``: una sola columna ``adc_u8`` (stream crudo, p. ej. un canal).

    gnuplot (dos canales): ``plot 'x.csv' using 2:3 title 'CH1', '' using 2:4 title 'CH2'``
    """
    p = Path(path).expanduser()
    dt = float(dt_seconds)
    if interleaved:
        ch1, ch2 = split_interleaved_u8(payload)
        n = max(len(ch1), len(ch2))
        lines: List[str] = [
            "# Hantek OSC — CH1=bytes pares, CH2=bytes impares (modo dos canales)",
            "# index,time_s,ch1_u8,ch2_u8",
            f"# dt_seconds={dt}",
            "index,time_s,ch1_u8,ch2_u8",
        ]
        for i in range(n):
            t = i * dt
            c1 = ch1[i] if i < len(ch1) else ""
            c2 = ch2[i] if i < len(ch2) else ""
            lines.append(f"{i},{t:.12g},{c1},{c2}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return n

    lines_single: List[str] = [
        "# Hantek OSC — stream único (sin separar canales); ADC 8 bit crudo",
        "# index,time_s,adc_u8",
        f"# dt_seconds={dt}",
        "index,time_s,adc_u8",
    ]
    u = list(payload)
    for i, val in enumerate(u):
        t = i * dt
        lines_single.append(f"{i},{t:.12g},{val}")
    p.write_text("\n".join(lines_single) + "\n", encoding="utf-8")
    return len(u)


def _format_analyze_report_single(raw: bytes, *, label: str | None = None) -> str:
    d = analyze_adc_payload(raw)
    if "error" in d:
        return f"Análisis ADC: {d.get('error')}"
    title = "Análisis ADC (heurístico, sin V/div)"
    if label:
        title = f"Análisis {label} (heurístico, sin V/div)"
    lines: List[str] = []
    lines.append(f"{title}:")
    lines.append(
        f"  n={d['n']}  min={d['u8_min']}  max={d['u8_max']}  pp={d['pp']:.1f}  "
        f"media={d['mean']:.1f}  rms_ac≈{d['rms_ac']:.2f}"
    )
    lines.append(
        f"  saturación≈{100.0 * float(d['sat_frac']):.1f}% (≤5: {d['sat_lo']}, ≥250: {d['sat_hi']}) "
        f"| banda media 40..215: {100.0 * float(d['mid_band_frac']):.1f}%"
    )
    lines.append(
        f"  |Δ| medio={float(d['mean_abs_diff']):.3f}  spikiness={float(d['spikiness']):.2f}  "
        f"calidad≈{d['quality_0_100']}/100"
    )
    if float(d["sat_frac"]) > 0.15 or d["pp"] >= 250:
        lines.append(
            "  → Probable recorte o señal muy grande: baja amplitud DDS, atenúa o sube V/div (ch-volt)."
        )
    if float(d["pp"]) < 20:
        lines.append("  → Señal muy pequeña en ADC: sube ganancia o amplitud de fuente.")
    return "\n".join(lines)


def format_analyze_report(raw: bytes, *, interleaved: bool = True) -> str:
    if not interleaved:
        return _format_analyze_report_single(raw)
    ch1, ch2 = split_interleaved_u8(raw)
    if not ch1 and not ch2:
        return _format_analyze_report_single(raw)
    parts: List[str] = [
        "Dos canales (CH1 = bytes pares, CH2 = bytes impares). "
        "Stream monolítico: usá --no-interleaved en get-*-data."
    ]
    if ch1:
        parts.append(_format_analyze_report_single(bytes(ch1), label="CH1"))
    if ch2:
        parts.append(_format_analyze_report_single(bytes(ch2), label="CH2"))
    return "\n\n".join(parts)

