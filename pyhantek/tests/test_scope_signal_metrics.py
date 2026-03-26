"""Tests sin hardware para ``hantek_usb.scope_signal_metrics``."""

from __future__ import annotations

import math

import pytest

from hantek_usb.scope_signal_metrics import (
    estimate_frequency_hz_mean_crossing,
    mean_crossings_u8,
    seconds_per_div_from_label,
    seconds_per_div_from_ram98_byte3,
)


def test_seconds_per_div_from_label() -> None:
    assert seconds_per_div_from_label("5.000ns/div") == pytest.approx(5e-9)
    assert seconds_per_div_from_label("1.000ms/div") == pytest.approx(1e-3)
    assert seconds_per_div_from_label("2.000s/div") == pytest.approx(2.0)
    assert seconds_per_div_from_label("bogus") is None


def test_seconds_per_div_from_ram98_byte3_known_idx() -> None:
    # idx 16 en TIME_DIV_LABELS = 1.000ms/div
    spd = seconds_per_div_from_ram98_byte3(16)
    assert spd is not None
    assert spd == pytest.approx(1e-3)


def test_mean_crossings_sine_like() -> None:
    # ~2 periodos de seno 0..255, centrada ~127
    xs = [int(127 + 120 * math.sin(i * 0.2)) for i in range(80)]
    assert mean_crossings_u8(xs) >= 4


def test_mean_crossings_dc() -> None:
    assert mean_crossings_u8([50] * 20) == 0


def test_estimate_frequency_hz_mean_crossing() -> None:
    # 10 ms/div * 10 div = 0.1 s ventana; 20 cruces -> 10 periodos -> 100 Hz
    hz = estimate_frequency_hz_mean_crossing(
        20,
        seconds_per_div=10e-3,
        horizontal_divisions=10.0,
    )
    assert hz == pytest.approx(100.0)


def test_estimate_frequency_low_crossings() -> None:
    assert (
        estimate_frequency_hz_mean_crossing(
            0,
            seconds_per_div=1e-3,
            horizontal_divisions=10.0,
        )
        is None
    )


def test_diff_read_settings_summaries() -> None:
    from hantek_usb.scope_signal_metrics import diff_read_settings_summaries

    a = {"valid": True, "fields_u8": {"ram98_byte3": 10, "x": 1}}
    b = {"valid": True, "fields_u8": {"ram98_byte3": 12, "x": 1, "y": 3}}
    d = diff_read_settings_summaries(a, b)
    fields = {r["field"]: (r["old"], r["new"]) for r in d}
    assert fields["ram98_byte3"] == (10, 12)
    assert fields["y"] == (-1, 3)
    assert "x" not in fields
