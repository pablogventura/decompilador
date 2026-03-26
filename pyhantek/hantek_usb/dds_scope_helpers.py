"""
Utilidades compartidas: DDS fijo + captura 0x16 + métricas por canal (entrelazado).

Usado por ``tools/dds_osc_coherence.py``, ``tools/scope_options_probe.py``, ``tools/scope_autoset_soft.py`` y ``tools/external_ch1_smoke.py``. Cruces por la media: ``hantek_usb.scope_signal_metrics``.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Callable

from hantek_usb.capture import smart_source_data_capture
from hantek_usb.constants import DDS_WAVE_TYPE_LABELS, WORK_TYPE_OSCILLOSCOPE, WORK_TYPE_SIGNAL_GENERATOR
from hantek_usb.osc_decode import flatten_chunks, split_interleaved_u8, trim_to_expected
from hantek_usb.protocol import (
    OpcodesDDS,
    dds_onoff_packet,
    dds_packet,
    dds_u16_packet,
    read_all_settings,
    scope_run_stop_stm32,
    work_type_packet,
)
from hantek_usb.scope_signal_metrics import mean_crossings_u8
from hantek_usb.transport import HantekLink


@dataclass
class ScopeChannelMetrics:
    """Métricas sobre un canal (o buffer raw si ``interleaved=False``)."""

    wave: int
    wave_name: str
    rep: int
    bytes_used: int
    u8_min: int
    u8_max: int
    pp: float
    mean: float
    spikiness: float
    frac_mid: float
    clipped: bool
    other_ch_min: int | None = None
    other_ch_max: int | None = None
    interleaved: bool = True
    # Cruces por encima de la media (proxy de “ciclos” visibles en la ventana)
    mean_crossings: int = 0


def tx_wait_ack(
    link: HantekLink,
    pkt: bytes,
    *,
    retries: int = 2,
    sleep_s: float = 0.25,
) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            link.write(pkt)
            return link.read64()
        except Exception as e:
            last = e
            if attempt < retries and sleep_s > 0:
                time.sleep(sleep_s)
    assert last is not None
    raise last


def _emit_noop(_s: str) -> None:
    return


def configure_dds(
    link: HantekLink,
    wave: int,
    freq: int,
    amp: int,
    settle_s: float,
) -> None:
    link.write(work_type_packet(WORK_TYPE_SIGNAL_GENERATOR, read=False))
    link.write(dds_u16_packet(OpcodesDDS.WAVE_TYPE, wave & 0xFFFF, read=False))
    link.write(dds_packet(OpcodesDDS.FREQUENCY, wait=False, u32_value=freq))
    link.write(dds_packet(OpcodesDDS.AMP, wait=False, u32_value=amp))
    link.write(dds_onoff_packet(True, read=False))
    if settle_s > 0:
        time.sleep(settle_s)


def capture_scope_raw(
    link: HantekLink,
    count_a: int,
    count_b: int,
    settle_s: float,
    *,
    smart_sleep_ms: int = 15,
) -> bytes:
    link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
    _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.12)
    if settle_s > 0:
        time.sleep(settle_s)

    chunks = smart_source_data_capture(
        link,
        count_a,
        count_b,
        blocks_fixed=64,
        smart=True,
        retry_max=30,
        sleep_ms=smart_sleep_ms,
        max_total_blocks=256,
        verbose=False,
        emit=_emit_noop,
        hex_fmt=lambda b: b.hex(),
    )
    expected = (count_a & 0xFFFF) + (count_b & 0xFFFF)
    return trim_to_expected(flatten_chunks(chunks), expected)


def compute_scope_channel_metrics(
    raw: bytes,
    wave: int,
    rep: int,
    clip_hi: int,
    clip_lo: int,
    *,
    interleaved: bool = True,
    metrics_channel: int = 1,
) -> ScopeChannelMetrics:
    if not raw:
        raise RuntimeError("Captura vacía.")
    other_min: int | None = None
    other_max: int | None = None
    if interleaved:
        ch1, ch2 = split_interleaved_u8(raw)
        if metrics_channel == 2:
            u = ch2
            other = ch1
        else:
            u = ch1
            other = ch2
        if other:
            other_min, other_max = min(other), max(other)
    else:
        u = list(raw)

    if not u:
        raise RuntimeError("Sin muestras en el canal elegido (buffer demasiado corto?).")
    mean = statistics.mean(u)
    xc = [x - mean for x in u]
    pp = float(max(xc) - min(xc))
    pp = max(pp, 1e-9)
    diffs = [xc[i + 1] - xc[i] for i in range(len(xc) - 1)]
    absd = [abs(d) for d in diffs] if diffs else [0.0]
    mad = statistics.mean(absd)
    maxd = max(absd)
    spikiness = maxd / (mad + 1e-9)

    lo = min(u)
    hi = max(u)
    span = hi - lo
    mid_lo = lo + 0.15 * span
    mid_hi = hi - 0.15 * span
    frac_mid = sum(1 for x in u if mid_lo <= x <= mid_hi) / len(u)

    clipped = lo <= clip_lo or hi >= clip_hi
    crossings = mean_crossings_u8(u)

    return ScopeChannelMetrics(
        wave=wave,
        wave_name=DDS_WAVE_TYPE_LABELS.get(wave, f"wave{wave}"),
        rep=rep,
        bytes_used=len(raw),
        u8_min=lo,
        u8_max=hi,
        pp=pp,
        mean=mean,
        spikiness=spikiness,
        frac_mid=frac_mid,
        clipped=clipped,
        other_ch_min=other_min,
        other_ch_max=other_max,
        interleaved=interleaved,
        mean_crossings=crossings,
    )
