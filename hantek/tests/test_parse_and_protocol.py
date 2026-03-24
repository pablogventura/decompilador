"""Tests sin hardware: tramas y parseo heurístico."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from hantek_usb.capture import estimate_extra_blocks, likely_not_ready
from hantek_usb.dmm_decode import decode_dmm_packet_14, decode_dmm_response
from hantek_usb import dmm_firmware_map
from hantek_usb.fpga_script import expand_steps
from hantek_usb.dds_decode import format_dds_response, parse_dds_response
from hantek_usb.parse_resp import format_parsed_block, parse_settings_read_all_set
from hantek_usb.protocol import (
    scope_query_3_1,
    scope_query_3_1_custom,
    source_data_request_packet,
    zero_cali_short_packet,
)
from hantek_usb.osc_decode import decode_capture, export_scope_csv


def test_scope_query_3_1_len() -> None:
    assert len(scope_query_3_1(0x01)) == 10
    assert scope_query_3_1(0x01)[4] == 0x01


def test_scope_query_3_1_custom_write_magic() -> None:
    p = scope_query_3_1_custom(0x03, read=False, word_at_6=0x7789)
    assert len(p) == 10
    assert p[3] == 0
    assert p[4] == 0x03
    assert p[6] == 0x89 and p[7] == 0x77


def test_zero_cali_short_len() -> None:
    assert len(zero_cali_short_packet()) == 10


def test_scope_run_stop_stm32_layout() -> None:
    from hantek_usb.protocol import scope_run_stop_stm32

    assert scope_run_stop_stm32(False).hex() == "000a0200080000000000"
    assert scope_run_stop_stm32(True).hex() == "000a0200080100000000"


def test_source_data_request_packet_layout() -> None:
    p = source_data_request_packet(0x400, 0x20)
    assert len(p) == 0x0A
    assert p[:5] == bytes([0x55, 0x0A, 0x00, 0x01, 0x16])
    assert p[5] == 0x00 and p[6] == 0x04
    assert p[7] == 0x20 and p[8] == 0x00


def test_export_scope_csv(tmp_path: Path) -> None:
    p = tmp_path / "w.csv"
    n = export_scope_csv(p, bytes([10, 20, 30]), dt_seconds=0.5)
    assert n == 3
    t = p.read_text(encoding="utf-8")
    assert "index,time_s,adc_u8" in t
    assert "0,0,10" in t
    assert "1,0.5,20" in t
    assert "2,1,30" in t


def test_likely_not_ready() -> None:
    assert likely_not_ready(b"\x00" * 64) is True
    assert likely_not_ready(b"\x01" + b"\x00" * 63) is False


def test_estimate_extra_blocks() -> None:
    assert estimate_extra_blocks(0) is None
    assert estimate_extra_blocks(64) == 0
    assert estimate_extra_blocks(65) == 1
    assert estimate_extra_blocks(0x400) == 15


def test_parse_settings_min() -> None:
    d = parse_settings_read_all_set(bytes(range(25)))
    assert d["length"] == 25
    assert "first_21_hex" in d


def test_format_parsed_stm() -> None:
    buf = bytes([0x55, 0x19, 0x03, 0x01]) + b"STM123\x00" + b"\x00" * 20
    s = format_parsed_block("stm", buf)
    assert "STM123" in s
    assert "dsoGetSTMID" in s


def test_decode_run_stop_ack() -> None:
    from hantek_usb.parse_resp import format_decode_only

    s = format_decode_only(bytes.fromhex("5505000c01"))
    assert "0x0C" in s or "run/stop" in s.lower() or "run" in s


def test_fpga_script_expand_hex(tmp_path: Path) -> None:
    js = {"steps": [{"hex": "00ff"}, {"hex": "aabb"}]}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(js), encoding="utf-8")
    blobs = expand_steps(json.loads(p.read_text(encoding="utf-8")))
    assert blobs == [b"\x00\xff", b"\xaa\xbb"]


def _synthetic_dmm_buf_dc_v_3v3() -> bytes:
    b = bytearray(64)
    b[0:3] = bytes([0x55, 0x0B, 0x05])  # cabecera + índice 5 = DC(V) (hipótesis)
    struct.pack_into("<f", b, 3, 3.3)
    return bytes(b)


def test_decode_dmm_response_float() -> None:
    buf = _synthetic_dmm_buf_dc_v_3v3()
    d = decode_dmm_response(buf)
    assert "valor_float_le" in d
    assert d["valor_float_le"]["offset"] == 3
    assert abs(d["valor_float_le"]["valor"] - 3.3) < 1e-5
    assert "DC(V)" in d.get("tipo_si_byte_2", "")


def test_format_parsed_block_dmm() -> None:
    buf = _synthetic_dmm_buf_dc_v_3v3()
    s = format_parsed_block("dmm", buf)
    assert "Float LE" in s
    assert "3.3" in s or "3.299" in s
    assert "DMM:" in s


def test_decode_dmm_packet_14_capturas() -> None:
    # HA sweep: 4.99 V, [6]=02
    a = bytes.fromhex("550b010501000200040909050155")
    d = decode_dmm_packet_14(a)
    assert d is not None and d["valor"] is not None
    assert abs(d["valor"] - 4.99) < 0.001
    assert d["ambiguo"] is False
    assert d["modo_byte_3"] == 0x05

    # 5.00 V (mismo patrón que antes se confundía con 0)
    b = bytes.fromhex("550b010501000200050000050155")
    d2 = decode_dmm_packet_14(b)
    assert d2 is not None and abs(d2["valor"] - 5.0) < 1e-6
    assert d2["modo_byte_3"] == 0x05

    # 0 V, [6]=03
    z = bytes.fromhex("550b010501010300000000050155")
    assert decode_dmm_packet_14(z) is not None
    assert decode_dmm_packet_14(z)["valor"] == 0.0

    # 12.34 V, [6]=02
    hi = bytes.fromhex("550b010501000201020304050155")
    assert abs(decode_dmm_packet_14(hi)["valor"] - 12.34) < 1e-6

    full = decode_dmm_response(b)
    assert "valor_float_le" not in full
    assert "valor_int32_le_micro" not in full
    assert abs(full["paquete_14"]["valor"] - 5.0) < 1e-6


def test_dds_decode_parse_sample() -> None:
    buf = bytes.fromhex("55070201881300000055")
    d = parse_dds_response(buf)
    assert d["length"] == 10
    assert d.get("u32_le_at_4") == 5000
    s = format_dds_response(buf, sent_subcode=0x01, sent_u32=440)
    assert "TX u32=440" in s and "fiable" in s.lower()


def test_decode_dmm_packet_14_continuidad() -> None:
    # Puntas al aire, pantalla OL
    ol = bytes.fromhex("550b0109000001ff004cff050255")
    d = decode_dmm_packet_14(ol)
    assert d is not None
    assert d.get("circuito_abierto") is True
    assert d.get("omit_float_heuristic") is True
    assert d["modo_byte_3"] == 0x09
    assert d["rango_byte_11"] == 0x05
    assert d["flags_byte_12"] == 0x02

    # Corto, pantalla 000.5 Ω
    short = bytes.fromhex("550b010900000100000005050255")
    d2 = decode_dmm_packet_14(short)
    assert d2 is not None
    assert abs(d2["valor_ohm"] - 0.5) < 1e-6
    assert "valor_float_le" not in decode_dmm_response(short)


def test_dmm_mode_comes_from_byte3_not_byte11() -> None:
    # byte[3] indica modo; byte[11] son flags y puede no coincidir.
    frame = bytes.fromhex("550b010900000100000005050255")
    d = decode_dmm_packet_14(frame)
    assert d is not None
    assert d["modo_byte_3"] == 0x09
    assert d["rango_byte_11"] == 0x05
    assert "COUNT" in d["modo_nombre_3"]


def test_dmm_firmware_fun_08031698_table() -> None:
    """FUN_08031698: permutación interno e0 → USB [3]."""
    expected = {1: 1, 2: 0, 3: 3, 4: 2, 5: 7, 6: 8, 7: 9, 8: 10, 9: 4, 10: 5, 11: 6}
    for e0, usb in expected.items():
        assert dmm_firmware_map.internal_e0_to_usb_mode_byte(e0) == usb
        assert dmm_firmware_map.usb_mode_byte_to_internal_e0(usb) == e0


def test_dmm_selector_equals_usb_byte3_identity() -> None:
    """FUN_0803170c ∘ FUN_08031698: selector 0..10 → byte[3] = selector (este firmware)."""
    for s in range(11):
        assert dmm_firmware_map.SELECTOR_TO_USB_BYTE3[s] == s


def test_decode_dmm_packet_14_ol_count_subformat03() -> None:
    """OL en modo COUNT con [6]=03 (no pasa por rama Ω [6]=01)."""
    h = "550b0109000003ff004cff050255"
    d = decode_dmm_packet_14(bytes.fromhex(h))
    assert d is not None
    assert d.get("sobrecarga_o_abierto") is True
    assert d.get("circuito_abierto") is False
    assert "valor_float_le" not in decode_dmm_response(bytes.fromhex(h))


def test_osc_decode_summary_shape() -> None:
    chunks = [bytes(range(64)), bytes(range(64))]
    d = decode_capture(chunks, expected_bytes=100)
    assert d["blocks"] == 2
    assert d["bytes_total"] == 128
    assert d["bytes_used"] == 100
    assert d.get("firmware_not_ready_first_chunk") is False


def test_firmware_not_ready_pattern() -> None:
    from hantek_usb.osc_decode import FIRMWARE_NOT_READY_12, firmware_buffer_not_ready

    assert len(FIRMWARE_NOT_READY_12) == 12
    assert firmware_buffer_not_ready(FIRMWARE_NOT_READY_12 + b"\x00" * 52)
    assert not firmware_buffer_not_ready(b"\x00" * 12)


def test_analyze_adc_basic() -> None:
    from hantek_usb.osc_decode import analyze_adc_payload

    d = analyze_adc_payload(bytes([128] * 200))
    assert d["pp"] == 0.0
    assert d["quality_0_100"] == 0.0

    ramp = bytes(range(256)) * 4
    d2 = analyze_adc_payload(ramp)
    assert d2["pp"] == 255.0
    assert d2["n"] == 1024
