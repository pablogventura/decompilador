"""Tests sin hardware: tramas y parseo heurístico."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from hantek_usb.capture import estimate_extra_blocks, likely_not_ready
from hantek_usb.dmm_decode import decode_dmm_packet_14, decode_dmm_response
from hantek_usb import dmm_firmware_map
from hantek_usb.fpga_script import expand_steps
from hantek_usb.dds_decode import format_dds_response, parse_dds_response
from hantek_usb.parse_resp import format_parsed_block, parse_settings_read_all_set
from hantek_usb.protocol import (
    DDS_ARB_NUM_SAMPLES,
    DDS_ARB_SAMPLE_BLOCK_BYTES,
    DDS_DOWNLOAD_HEADER_LEN_LONG,
    DDS_DOWNLOAD_HEADER_LEN_SHORT,
    DDS_DOWNLOAD_SIZE_LONG,
    DDS_DOWNLOAD_SIZE_SHORT,
    build_dds_download_blob,
    dds_download_header_short,
    dds_download_long_chunked_blob,
    dds_long_chunked_blob_to_samples,
    dll_float_to_int16,
    float_samples_to_dds_int16,
    dds_arb_samples_int16_le,
    dds_offset_packet,
    scope_query_3_1,
    scope_query_3_1_custom,
    source_data_request_packet,
    zero_cali_short_packet,
)
from hantek_usb.osc_decode import decode_capture, export_scope_csv, split_interleaved_u8


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


def test_dds_download_blob_sizes() -> None:
    samples = bytes(DDS_ARB_SAMPLE_BLOCK_BYTES)
    s = build_dds_download_blob(samples, variant="short")
    assert len(s) == DDS_DOWNLOAD_SIZE_SHORT
    assert s[:DDS_DOWNLOAD_HEADER_LEN_SHORT] == dds_download_header_short(0)
    assert s[DDS_DOWNLOAD_HEADER_LEN_SHORT:] == samples

    assert build_dds_download_blob(samples, variant="short", arb_slot=2)[5] == 3

    l = build_dds_download_blob(samples, variant="long")
    assert len(l) == DDS_DOWNLOAD_SIZE_LONG
    # Rama larga DLL: 18 bloques × 64 B truncados a 0x46C; bloque 0 cabecera [1][0x40]…
    assert l[0] == 0x01 and l[1] == 0x40 and l[2] == 0x02 and l[4] == 0x07 and l[5] == 0x01
    assert l[0x40] == 0x02 and l[0x40 + 1] == 0x40  # bloque 1
    assert l[17 * 0x40] == 0x12 and l[17 * 0x40 + 1] == 0x2C  # último bloque i=17

    custom = bytes(range(DDS_DOWNLOAD_HEADER_LEN_SHORT))
    s2 = build_dds_download_blob(samples, variant="short", header=custom)
    assert s2[:DDS_DOWNLOAD_HEADER_LEN_SHORT] == custom

    long_lin_hdr = bytes(DDS_DOWNLOAD_HEADER_LEN_LONG)
    l_lin = build_dds_download_blob(samples, variant="long", header=long_lin_hdr)
    assert len(l_lin) == DDS_DOWNLOAD_SIZE_LONG
    assert l_lin[:DDS_DOWNLOAD_HEADER_LEN_LONG] == long_lin_hdr
    assert l_lin[DDS_DOWNLOAD_HEADER_LEN_LONG:] == samples

    sq = dds_download_long_chunked_blob([3000 if i < 256 else -3000 for i in range(512)], arb_slot=0)
    assert len(sq) == DDS_DOWNLOAD_SIZE_LONG
    assert struct.unpack_from("<h", sq, 6)[0] == 3000


def test_dds_long_chunked_roundtrip_and_truncation() -> None:
    """0x46C truncado: bloque 17 solo 19×int16 → muestras 493..511 en el wire."""
    ramp = [i - 256 for i in range(DDS_ARB_NUM_SAMPLES)]
    blob = dds_download_long_chunked_blob(ramp, arb_slot=1)
    assert len(blob) == DDS_DOWNLOAD_SIZE_LONG
    assert blob[5] == 0x02  # arb2
    back = dds_long_chunked_blob_to_samples(blob)
    assert back == ramp
    # Último bloque: offset 17×64; solo 38 B de payload (19 shorts) hasta fin del wire
    last_off = 17 * 0x40
    assert struct.unpack_from("<h", blob, last_off + 6)[0] == ramp[493]
    assert struct.unpack_from("<h", blob, last_off + 6 + 2 * 18)[0] == ramp[511]
    assert len(blob[last_off + 6 :]) == 38


def test_dll_float_to_int16_like_decomp() -> None:
    assert dll_float_to_int16(0.0) == 0
    assert dll_float_to_int16(-1.7) == -1
    assert dll_float_to_int16(1.7) == 1
    assert dll_float_to_int16(32767.0) == 32767
    assert dll_float_to_int16(-32767.0) == -32767
    # (short) trunc fuera de rango → saturación por signo del float
    assert dll_float_to_int16(40000.0) == -25536  # (short)40000 en C
    # -32768 como short tiene abs 32768 > 0x7FFF → ±0x7FFF según float
    assert dll_float_to_int16(-32768.0) == -0x7FFF
    assert dll_float_to_int16(32768.0) == 0x7FFF
    fs = [math.sin(2 * math.pi * i / 512) * 2800.0 for i in range(512)]
    ints = float_samples_to_dds_int16(fs)
    assert len(ints) == 512
    assert all(-32768 <= x <= 32767 for x in ints)


def test_dds_arb_samples_int16_le_len() -> None:
    flat = dds_arb_samples_int16_le([0] * 512)
    assert len(flat) == DDS_ARB_SAMPLE_BLOCK_BYTES
    assert flat[:4] == b"\x00\x00\x00\x00"


def test_source_data_request_packet_layout() -> None:
    p = source_data_request_packet(0x400, 0x20)
    assert len(p) == 0x0A
    assert p[:5] == bytes([0x55, 0x0A, 0x00, 0x01, 0x16])
    assert p[5] == 0x00 and p[6] == 0x04
    assert p[7] == 0x20 and p[8] == 0x00


def test_dds_offset_packet_layout_signed() -> None:
    p_pos = dds_offset_packet(1000, read=True)
    assert len(p_pos) == 10
    assert p_pos[:5] == bytes([0x00, 0x0A, 0x02, 0x01, 0x03])
    assert p_pos[5] == 0xE8 and p_pos[6] == 0x03
    assert p_pos[7] == 0x00

    p_neg = dds_offset_packet(-1000, read=False)
    assert p_neg[:5] == bytes([0x00, 0x0A, 0x02, 0x00, 0x03])
    assert p_neg[5] == 0xE8 and p_neg[6] == 0x03
    assert p_neg[7] == 0x01


def test_dds_offset_packet_range_error() -> None:
    import pytest

    with pytest.raises(ValueError):
        dds_offset_packet(70000, read=True)


def test_split_interleaved_u8() -> None:
    a, b = split_interleaved_u8(bytes([10, 20, 30, 40]))
    assert a == [10, 30]
    assert b == [20, 40]
    a2, b2 = split_interleaved_u8(bytes([1, 2, 3]))
    assert a2 == [1, 3]
    assert b2 == [2]


def test_export_scope_csv_interleaved(tmp_path: Path) -> None:
    p = tmp_path / "w.csv"
    n = export_scope_csv(p, bytes([10, 20, 30]), dt_seconds=0.5, interleaved=True)
    assert n == 2
    t = p.read_text(encoding="utf-8")
    assert "ch1_u8,ch2_u8" in t
    assert "0,0,10,20" in t
    assert "1,0.5,30," in t


def test_export_scope_csv_raw_stream(tmp_path: Path) -> None:
    p = tmp_path / "w.csv"
    n = export_scope_csv(p, bytes([10, 20, 30]), dt_seconds=0.5, interleaved=False)
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
    assert "firmware25" in d
    assert not d["firmware25"]["valid_layout"]


def test_read_all_set_firmware_decode_sample() -> None:
    from hantek_usb.parse_resp import decode_read_all_set_firmware25, format_parsed_block

    sample = bytes.fromhex("5519001501160001098f010000000532010003960000000090")
    dec = decode_read_all_set_firmware25(sample)
    assert dec["valid_layout"]
    assert dec["fields"]["ram94_u16_0x06_lo"]["u8"] == 0x01
    assert dec["fields"]["ram98_byte3"]["u8"] == 0x03
    s = format_parsed_block("settings", sample)
    assert "FUN_08032140" in s
    assert "ram9c_byte0" in s


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


def test_decode_dmm_packet_14_acv_near_zero() -> None:
    """AC(V) ~0 V, 2D42; [6]=0x03 patrón 02 08 09 03 (captura USB real)."""
    h = bytes.fromhex("550b010602000302080903050155")
    d = decode_dmm_packet_14(h)
    assert d is not None
    assert d["modo_byte_3"] == 6
    assert abs(d["valor"] - 0.0) < 1e-9
    assert d.get("ambiguo") is False


def test_decode_dmm_packet_14_capacitance_zero() -> None:
    """Capacidad sin capacitor: [6]=0x03, [7:10]=0 (2D42)."""
    h = bytes.fromhex("550b010700000300000000000355")
    d = decode_dmm_packet_14(h)
    assert d is not None
    assert d["modo_byte_3"] == 7
    assert abs(d["valor"] - 0.0) < 1e-9
    assert d.get("unidad_guess") == "F"
    assert "capacidad" in (d.get("formula") or "").lower()


def test_decode_dmm_packet_14_capacitance_1uf_nominal() -> None:
    """~1 µF en banco: nF = 0*1000+9*100+3*10+1 = 931 → 931e-9 F (2D42)."""
    h = bytes.fromhex("550b010700000300090301010355")
    d = decode_dmm_packet_14(h)
    assert d is not None
    assert d["modo_byte_3"] == 7
    assert abs(d["valor"] - 931e-9) < 1e-18
    assert d.get("unidad_guess") == "F"


def test_decode_dmm_packet_14_diode_ol() -> None:
    """Diodo puntas al aire / OL: mismo patrón FF 00 4C FF que otros modos (2D42)."""
    h = bytes.fromhex("550b010a000003ff004cff050155")
    d = decode_dmm_packet_14(h)
    assert d is not None
    assert d["modo_byte_3"] == 10
    assert d["valor"] is None
    assert d.get("sobrecarga_o_abierto") is True
    assert d.get("circuito_abierto") is True
    assert "diodo" in (d.get("nota") or "").lower()


def test_decode_dmm_packet_14_diode_forward() -> None:
    """Diodo ~0,69 V; [6]=0x03, [7:10]=00 06 09 02 → 0,692 V (LCD ~0,697 V, 2D42)."""
    h = bytes.fromhex("550b010a00000300060902050155")
    d = decode_dmm_packet_14(h)
    assert d is not None
    assert d["modo_byte_3"] == 10
    assert abs(d["valor"] - 0.692) < 1e-9
    assert d.get("ambiguo") is False


def test_decode_dmm_packet_14_acv_mains() -> None:
    """AC(V) tensión red ~227 V; [6]=0x01 dígitos 02 02 07 07 → 227,7 V (2D42)."""
    h = bytes.fromhex("550b010602000102020707050155")
    d = decode_dmm_packet_14(h)
    assert d is not None
    assert d["modo_byte_3"] == 6
    assert abs(d["valor"] - 227.7) < 1e-6
    assert d.get("ambiguo") is False


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

    # 2.50 V, [6]=03 (validado en 2D42 con fuente laboratorio)
    z25 = bytes.fromhex("550b010501000302050003050155")
    assert decode_dmm_packet_14(z25) is not None
    assert abs(decode_dmm_packet_14(z25)["valor"] - 2.5) < 1e-6

    # 1.00 V, [6]=03 (validado en 2D42 con fuente laboratorio)
    z10 = bytes.fromhex("550b010501000301000000050155")
    assert decode_dmm_packet_14(z10) is not None
    assert abs(decode_dmm_packet_14(z10)["valor"] - 1.0) < 1e-6

    # 12.34 V, [6]=02
    hi = bytes.fromhex("550b010501000201020304050155")
    assert abs(decode_dmm_packet_14(hi)["valor"] - 12.34) < 1e-6

    # 12.35 V, [6]=02 (2D42 + fuente laboratorio, 2026-03-25)
    hi35 = bytes.fromhex("550b010501000201020305050155")
    assert abs(decode_dmm_packet_14(hi35)["valor"] - 12.35) < 1e-6

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


def test_cli_doctor_subcommand_registered() -> None:
    from hantek_usb.cli import build_parser

    p = build_parser()
    ns = p.parse_args(["doctor"])
    assert ns.command == "doctor"
    assert callable(getattr(ns, "_fn", None))


def test_cli_ch_invert_subcommand_registered() -> None:
    from hantek_usb.cli import build_parser

    p = build_parser()
    ns = p.parse_args(["ch-invert", "0"])
    assert ns.command == "ch-invert"
    assert ns.channel == 0
    assert ns.xor_mask == 0x02
    assert ns.raw_byte is None
    assert callable(getattr(ns, "_fn", None))
    ns2 = p.parse_args(["ch-invert", "0", "--raw-byte", "0x9d", "--xor-mask", "0x12"])
    assert ns2.raw_byte == 0x9D
    assert ns2.xor_mask == 0x12


def test_cli_dds_default_write_mode_for_fre_amp() -> None:
    from hantek_usb.cli import build_parser

    p = build_parser()
    ns_fre = p.parse_args(["dds-fre", "1234"])
    ns_amp = p.parse_args(["dds-amp", "1000"])
    ns_off = p.parse_args(["dds-offset", "500"])

    assert ns_fre.write_only is True
    assert ns_amp.write_only is True
    assert ns_off.write_only is False


def test_fun_04440_firmware_only_0x18_write_shape() -> None:
    from hantek_usb.protocol import (
        CH1_INVERT_TOGGLE_XOR_DEFAULT,
        Opcodes04440,
        fun_04440,
        ram9c_byte9_apply_xor,
        scope_ram9c_byte9_packet,
    )

    assert Opcodes04440.SCOPE_FIRMWARE_ONLY_0x18 == 0x18
    assert CH1_INVERT_TOGGLE_XOR_DEFAULT == 0x02
    pkt = fun_04440(0x18, 0x1234, payload_bytes=2, wait_response=False)
    assert pkt == bytes([0x00, 0x0A, 0x00, 0x00, 0x18, 0x34, 0x12, 0x00, 0x00, 0x00])
    assert ram9c_byte9_apply_xor(0x97) == 0x95
    assert ram9c_byte9_apply_xor(0x95) == 0x97
    assert ram9c_byte9_apply_xor(0x9D, 0x12) == 0x8F
    assert scope_ram9c_byte9_packet(0x64) == bytes(
        [0x00, 0x0A, 0x00, 0x00, 0x18, 0x64, 0, 0, 0, 0]
    )


def test_dds_download_long_blob_arb_slot_headers() -> None:
    """Cada slot 0..3 (arb1..arb4) debe ir en byte [5] de cada trozo 64 B (firmware/DLL long)."""
    from hantek_usb.protocol import (
        DDS_DOWNLOAD_SIZE_LONG,
        build_dds_download_blob,
        dds_arb_samples_int16_le,
    )

    zeros = dds_arb_samples_int16_le([0] * 512)
    for slot in range(4):
        blob = build_dds_download_blob(zeros, variant="long", arb_slot=slot)
        assert len(blob) == DDS_DOWNLOAD_SIZE_LONG
        for chunk_i in range(18):
            off = chunk_i * 0x40
            assert blob[off + 4] == 0x07
            assert blob[off + 5] == slot + 1


def test_compare_read_settings_script_smoke() -> None:
    import subprocess
    import sys

    import pytest

    root = Path(__file__).resolve().parent.parent
    a = root / "captures" / "estado_read_settings_20260325T223927Z_ch1_no_invertido.txt"
    b = root / "captures" / "estado_read_settings_20260325T224011Z_ch1_invertido.txt"
    if not a.is_file() or not b.is_file():
        pytest.skip("capturas compare_read_settings no en repo")
    script = root / "tools" / "compare_read_settings.py"
    r = subprocess.run(
        [sys.executable, str(script), str(a), str(b)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "ram9c_byte9_plus_d" in r.stdout


def test_compare_scope_snapshots_script_smoke(tmp_path: Path) -> None:
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    script = root / "tools" / "compare_scope_snapshots.py"
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(
        json.dumps(
            {
                "fields_u8": {"ram98_byte0": 0, "ram9c_byte6": 0},
                "payload_21_hex": "ab" * 21,
                "note": "uno",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    b.write_text(
        json.dumps(
            {
                "fields_u8": {"ram98_byte0": 1, "ram9c_byte6": 0},
                "payload_21_hex": "cd" * 21,
                "note": "dos",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(script), str(a), str(b)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "ram98_byte0" in r.stdout
    assert "0x00 → 0x01" in r.stdout
