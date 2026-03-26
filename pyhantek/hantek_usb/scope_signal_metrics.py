"""
Métricas sobre buffers **u8** del osciloscopio (CH1/CH2 entrelazados o un canal).

La **frecuencia estimada** usa cruces por la media y asume que la ventana temporal
del buffer equivale a ``horizontal_divisions`` × time/div en pantalla (por defecto
**10** divisiones, convención habitual en DSO). Es **heurística**: el firmware puede
usar memoria de captura distinta del grid de 10 divs; contrastar con ``--expect-hz``
solo cuando el generador esté calibrado.

Los labels de time/div provienen de ``parse_resp.TIME_DIV_LABELS`` (empírico 2D42).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from hantek_usb.parse_resp import TIME_DIV_LABELS

_TIME_DIV_RE = re.compile(
    r"^\s*([0-9]*\.?[0-9]+)\s*(ns|us|ms|s)/div\s*$",
    re.IGNORECASE,
)

_UNIT_TO_SEC = {
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
}


def seconds_per_div_from_label(label: str) -> float | None:
    """Parsea p. ej. \"5.000ns/div\" → segundos por división horizontal."""
    m = _TIME_DIV_RE.match(label.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    mult = _UNIT_TO_SEC.get(unit)
    if mult is None:
        return None
    return val * mult


def seconds_per_div_from_ram98_byte3(ram98_byte3: int) -> float | None:
    """Índice leído en ``read-settings`` (campo ``ram98_byte3``) → s/div."""
    lab = TIME_DIV_LABELS.get(int(ram98_byte3) & 0xFF)
    if lab is None:
        return None
    return seconds_per_div_from_label(lab)


def mean_crossings_u8(samples: Sequence[int]) -> int:
    """Cuenta transiciones entre muestras por encima y por debajo de la media aritmética."""
    if len(samples) < 3:
        return 0
    m = sum(samples) / len(samples)
    c = 0
    for i in range(len(samples) - 1):
        a, b = samples[i], samples[i + 1]
        if (a < m) != (b < m):
            c += 1
    return c


def estimate_frequency_hz_mean_crossing(
    mean_crossings: int,
    *,
    seconds_per_div: float,
    horizontal_divisions: float = 10.0,
) -> float | None:
    """
    F ≈ (cruces_medio / 2) / T_ventana, con T_ventana = s/div × divisiones.

    Para una senoidal simétrica respecto de la media hay ~2 cruces por periodo.
    """
    if seconds_per_div <= 0 or horizontal_divisions <= 0:
        return None
    t_window = float(seconds_per_div) * float(horizontal_divisions)
    if t_window <= 0:
        return None
    periods = mean_crossings / 2.0
    if periods < 0.5:
        return None
    return periods / t_window


def estimate_frequency_hz_for_ch1_samples(
    ch1_u8: Sequence[int],
    *,
    ram98_byte3: int,
    horizontal_divisions: float = 10.0,
) -> tuple[float | None, float | None]:
    """
    Devuelve ``(hz_estimado, seconds_per_div)`` o ``(None, None)`` si no hay tabla.
    """
    spd = seconds_per_div_from_ram98_byte3(ram98_byte3)
    if spd is None:
        return None, None
    xc = mean_crossings_u8(ch1_u8)
    hz = estimate_frequency_hz_mean_crossing(
        xc,
        seconds_per_div=spd,
        horizontal_divisions=horizontal_divisions,
    )
    return hz, spd


def read_settings_fields_summary(dec: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae un dict estable para JSON/logs desde ``decode_read_all_set_firmware25``."""
    if not dec.get("valid_layout"):
        return {"valid": False}
    fields = dec.get("fields") or {}
    out: Dict[str, Any] = {"valid": True, "fields_u8": {}}
    for name, meta in fields.items():
        if isinstance(meta, dict) and "u8" in meta:
            out["fields_u8"][name] = int(meta["u8"])
            if "time_div_label" in meta:
                out.setdefault("labels", {})["time_div"] = meta["time_div_label"]
            if "trigger_sweep_label" in meta:
                out.setdefault("labels", {})["trigger_sweep"] = meta["trigger_sweep_label"]
            if "trigger_slope_label" in meta:
                out.setdefault("labels", {})["trigger_slope"] = meta["trigger_slope_label"]
    return out

def diff_read_settings_summaries(
    summary_a: Dict[str, Any],
    summary_b: Dict[str, Any],
) -> List[Dict[str, int]]:
    """
    Compara ``fields_u8`` de dos salidas de ``read_settings_fields_summary``.

    Formato de cada ítem: ``{"field": str, "old": int, "new": int}`` (misma idea que
    ``tools/compare_scope_snapshots.py --json``). Valores ``-1`` = ausente en un lado.
    """
    fa: Dict[str, Any] = {}
    fb: Dict[str, Any] = {}
    if summary_a.get("valid"):
        fa = summary_a.get("fields_u8") or {}
    if summary_b.get("valid"):
        fb = summary_b.get("fields_u8") or {}
    if not isinstance(fa, dict):
        fa = {}
    if not isinstance(fb, dict):
        fb = {}

    diffs: List[Dict[str, int]] = []
    for k in sorted(set(fa) | set(fb)):
        va, vb = fa.get(k), fb.get(k)
        if va is None and vb is None:
            continue
        if va is None:
            diffs.append({"field": str(k), "old": -1, "new": int(vb)})
        elif vb is None:
            diffs.append({"field": str(k), "old": int(va), "new": -1})
        elif int(va) != int(vb):
            diffs.append({"field": str(k), "old": int(va), "new": int(vb)})
    return diffs

