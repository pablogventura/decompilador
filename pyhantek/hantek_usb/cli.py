"""
Interfaz de línea de órdenes — agrupa subcomandos por categoría.
Ejecutar: hantek (pipx) | python -m hantek_usb | python -m hantek_usb.cli | python hantek_cli.py desde pyhantek/
"""

from __future__ import annotations

import argparse
import binascii
import sys
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

import usb.core

from hantek_usb import constants
from hantek_usb import parse_resp
from hantek_usb.protocol import (
    DDS_ARB_SAMPLE_BLOCK_BYTES,
    DDS_DOWNLOAD_HEADER_LEN_LONG,
    DDS_DOWNLOAD_HEADER_LEN_SHORT,
    DDS_DOWNLOAD_SIZE_LONG,
    DDS_DOWNLOAD_SIZE_SHORT,
    Opcodes04440,
    OpcodesDDS,
    check_04440_ack,
    ch_opcode,
    dds_onoff_packet,
    dds_offset_packet,
    dds_packet,
    dds_set_options_packet,
    dds_trap_three_packet,
    dds_u16_packet,
    dmm_get_data_packet,
    dmm_set_type_packet,
    factory_setup_pulse,
    fun_04440,
    read_all_settings,
    scope_ram9c_byte9_packet,
    scope_run_stop_stm32,
    scope_query_3_1,
    scope_query_3_1_custom,
    work_type_packet,
    write_all_settings_packet,
    zero_cali_short_packet,
)
from hantek_usb.transport import HantekLink, HantekUsbError, iter_usb_devices


def _hex(data: bytes, dense: bool) -> str:
    if dense:
        return data.hex()
    return binascii.hexlify(data, sep=" ").decode("ascii")


def _bytes_from_hex_or_file(
    ns: argparse.Namespace,
    *,
    hex_attr: str,
    file_attr: str,
    exact: Optional[int] = None,
    min_len: int = 1,
    max_len: Optional[int] = None,
) -> bytes:
    raw_hex = getattr(ns, hex_attr, None)
    path = getattr(ns, file_attr, None)
    has_hex = raw_hex is not None and str(raw_hex).strip() != ""
    has_file = path is not None and str(path).strip() != ""
    if has_hex == has_file:
        raise SystemExit("Indica exactamente uno: datos HEX o --file RUTA.")
    if has_file:
        data = Path(path).expanduser().read_bytes()
    else:
        data = bytes.fromhex(str(raw_hex).replace(" ", ""))
    if len(data) < min_len:
        raise SystemExit(f"Se requieren al menos {min_len} byte(s); hay {len(data)}.")
    if max_len is not None and len(data) > max_len:
        raise SystemExit(f"Como máximo {max_len} byte(s); hay {len(data)}.")
    if exact is not None and len(data) != exact:
        raise SystemExit(f"Se requieren exactamente {exact} bytes; hay {len(data)}.")
    return data


def _usb_parent() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--vid", type=lambda x: int(x, 0), default=constants.VID_HANTEK_2XX2)
    p.add_argument("--pid", type=lambda x: int(x, 0), default=constants.DEFAULT_PID_HANTEK)
    p.add_argument("--bus", type=int, default=None)
    p.add_argument("--address", type=int, default=None)
    p.add_argument("--interface", "-i", type=int, default=0, metavar="N")
    p.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=constants.DEFAULT_TIMEOUT_MS,
        metavar="MS",
        help="Timeout por transferencia USB (ms)",
    )
    p.add_argument(
        "--dense-hex",
        action="store_true",
        help="Salida hex sin espacios",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Imprime tramas enviadas/recibidas",
    )
    p.add_argument(
        "--check-ack",
        action="store_true",
        help="En órdenes FUN_10004440: avisar si rsp[3]≠opcode",
    )
    return p


def _open(ns: argparse.Namespace) -> HantekLink:
    return HantekLink(
        vid=ns.vid,
        pid=ns.pid,
        bus=ns.bus,
        address=ns.address,
        interface=ns.interface,
        timeout_ms=ns.timeout,
    )


def _tx_rx10(
    link: HantekLink,
    pkt: bytes,
    ns: argparse.Namespace,
    *,
    ack04440: Optional[int] = None,
) -> bytes:
    if ns.verbose:
        print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
    link.write(pkt)
    rsp = link.read64()
    if ns.verbose:
        print("<<", _hex(rsp, ns.dense_hex), file=sys.stderr)
    if ack04440 is not None and not check_04440_ack(rsp, ack04440):
        print(
            f"Advertencia: se esperaba rsp[3]==0x{ack04440:02x} (eco FUN_10004440); "
            f"rsp[3]=0x{rsp[3]:02x}",
            file=sys.stderr,
        )
    return rsp


def _cmd_list(ns: argparse.Namespace) -> None:
    for bus, addr, vid, pid in iter_usb_devices():
        print(f"bus {bus:03d}  addr {addr:03d}  {vid:04x}:{pid:04x}")


def _cmd_endpoints(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        print(f"BULK OUT  {link.ep_out:#04x}")
        print(f"BULK IN   {link.ep_in:#04x}")
    finally:
        link.close()


def _cmd_doctor(ns: argparse.Namespace) -> None:
    """Una pasada: endpoints, read-settings parseado, consultas STM / FPGA / ARM (query-31)."""
    print(
        f"Objetivo USB: vid={ns.vid:04x} pid={ns.pid:04x} "
        f"bus={ns.bus!r} addr={ns.address!r} iface={ns.interface}"
    )
    link = _open(ns)
    try:
        print(f"BULK OUT  {link.ep_out:#04x}")
        print(f"BULK IN   {link.ep_in:#04x}")
        pkt = read_all_settings()
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        rsp = link.read64()
        print("--- read-settings (parse) ---")
        print(parse_resp.format_parsed_block("settings", rsp))
        for label, sub, kind in (
            ("STM", 0x01, "stm"),
            ("FPGA", 0x0C, "fpga"),
            ("ARM", 0x0A, "arm"),
        ):
            pkt2 = scope_query_3_1(sub)
            if ns.verbose:
                print(">>", _hex(pkt2, ns.dense_hex), file=sys.stderr)
            link.write(pkt2)
            rsp2 = link.read64()
            print(f"--- query-31 0x{sub:02x} ({label}) ---")
            print(parse_resp.format_parsed_block(kind, rsp2))
    finally:
        link.close()


def _cmd_read_settings(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = read_all_settings()
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        rsp = link.read64()
        if getattr(ns, "parse", False):
            print(parse_resp.format_parsed_block("settings", rsp))
        else:
            print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_write_settings(ns: argparse.Namespace) -> None:
    """dsoHTReadAllSet escritura: solo 10 B al USB; --tail ≤5 B en [5:9] (ver ``write_all_settings_packet``)."""
    tail = b""
    if getattr(ns, "tail", None):
        tail = bytes.fromhex(ns.tail.replace(" ", ""))
        if len(tail) > 5:
            raise SystemExit("write-settings --tail: como máximo 5 bytes (10 dígitos hex).")
    pkt = write_all_settings_packet(tail if tail else None)
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        print("ok (sin lectura R64; byte 3 = 0)")
    finally:
        link.close()


def _cmd_bulk_send(ns: argparse.Namespace) -> None:
    """Envío bulk de longitud arbitraria (trocea a 64 B en transport)."""
    data = _bytes_from_hex_or_file(
        ns,
        hex_attr="hex_payload",
        file_attr="payload_file",
        min_len=1,
    )
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", len(data), "B", _hex(data[: min(16, len(data))], ns.dense_hex), "…", file=sys.stderr)
        link.write(data)
        n = max(0, ns.reads)
        if n:
            out = link.read_n(n)
            print(_hex(out, ns.dense_hex))
        else:
            print("ok")
    finally:
        link.close()


def _cmd_write_banner(ns: argparse.Namespace) -> None:
    """dsoWriteBanner: exactamente 30 bytes."""
    data = _bytes_from_hex_or_file(
        ns,
        hex_attr="hex_payload",
        file_attr="payload_file",
        exact=30,
    )
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", _hex(data, ns.dense_hex), file=sys.stderr)
        link.write(data)
        print("ok")
    finally:
        link.close()


def _cmd_dds_download(ns: argparse.Namespace) -> None:
    """
    ddsSDKDownload: una escritura bulk de 0x406 o 0x46C B (driver trocea a 64 B).

    Firmware: por slot arb se cargan 0x400 B de muestras (512×int16 LE); el resto es
    cabecera (6 u 0x6C B según variante). Ver HALLAZGOS_DMM_DDS_2026-03.md § arb.
    """
    expect = DDS_DOWNLOAD_SIZE_SHORT if ns.variant == "short" else DDS_DOWNLOAD_SIZE_LONG
    data = _bytes_from_hex_or_file(
        ns,
        hex_attr="hex_payload",
        file_attr="payload_file",
        exact=expect,
    )
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", len(data), "B (dds-download)", file=sys.stderr)
        link.write(data)
        print("ok")
    finally:
        link.close()


def _cmd_device_sn(ns: argparse.Namespace) -> None:
    """dsoDeviceSN: trama de 10 o 37 bytes (contenido según DLL / captura USB)."""
    data = _bytes_from_hex_or_file(
        ns,
        hex_attr="hex_payload",
        file_attr="payload_file",
        min_len=10,
        max_len=37,
    )
    if len(data) not in (10, 37):
        raise SystemExit("device-sn: la trama debe ser exactamente 10 o 37 bytes.")
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", _hex(data, ns.dense_hex), file=sys.stderr)
        link.write(data)
        rsp = link.read64()
        print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_write_device_cali(ns: argparse.Namespace) -> None:
    """dsoWriteDeviceCali: cabecera 5 B + payload (longitud total la das tú en hex/--file)."""
    data = _bytes_from_hex_or_file(
        ns,
        hex_attr="hex_payload",
        file_attr="payload_file",
        min_len=5,
    )
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", len(data), "B", file=sys.stderr)
        link.write(data)
        print("ok")
    finally:
        link.close()


def _cmd_scope_query(
    ns: argparse.Namespace,
    sub: int,
    parse_kind: Optional[str] = None,
) -> None:
    link = _open(ns)
    try:
        pkt = scope_query_3_1(sub)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        rsp = link.read64()
        if getattr(ns, "parse", False) and parse_kind:
            print(parse_resp.format_parsed_block(parse_kind, rsp))
        else:
            print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_query_31(ns: argparse.Namespace) -> None:
    """Consulta genérica `00 0A 03 01` + subcódigo (byte 5), p. ej. calibración si conoces el código."""
    kind = "generic" if getattr(ns, "parse", False) else None
    _cmd_scope_query(ns, ns.subcode, kind)


def _run_source_data_capture(
    ns: argparse.Namespace,
    *,
    clear_first: bool = False,
) -> List[bytes]:
    from hantek_usb.capture import smart_source_data_capture, smart_source_data_capture_legacy

    link = _open(ns)
    try:
        if clear_first and getattr(ns, "clear_buffer_first", False):
            d = link.read64()
            if ns.verbose:
                print("<< clear-buffer-first", _hex(d, ns.dense_hex), file=sys.stderr)

        def emit(s: str) -> None:
            if ns.verbose:
                print(s, file=sys.stderr)

        try:
            return smart_source_data_capture(
                link,
                ns.count_a,
                ns.count_b,
                blocks_fixed=max(0, ns.blocks),
                smart=bool(ns.smart),
                retry_max=ns.retry_max,
                sleep_ms=ns.sleep_ms,
                max_total_blocks=ns.max_total_blocks,
                verbose=ns.verbose,
                emit=emit,
                hex_fmt=lambda b: _hex(b, ns.dense_hex),
            )
        except usb.core.USBError as e:
            if "timed out" not in str(e).lower():
                raise
            if ns.verbose:
                print(
                    "!! timeout con trama firmware 0x16; probando fallback legacy",
                    file=sys.stderr,
                )
            return smart_source_data_capture_legacy(
                link,
                int(ns.count_a) & 0xFFFF,
                blocks_fixed=max(0, ns.blocks),
                smart=bool(ns.smart),
                retry_max=ns.retry_max,
                sleep_ms=ns.sleep_ms,
                max_total_blocks=ns.max_total_blocks,
                verbose=ns.verbose,
                emit=emit,
                hex_fmt=lambda b: _hex(b, ns.dense_hex),
            )
    finally:
        link.close()


def _finalize_capture_payload(ns: argparse.Namespace, chunks: List[bytes]) -> None:
    """Guarda binario y/o CSV a partir de la captura (muestras recortadas a count_a+count_b)."""
    from hantek_usb.osc_decode import export_scope_csv, flatten_chunks, trim_to_expected

    expected = (int(ns.count_a) & 0xFFFF) + (int(ns.count_b) & 0xFFFF)
    payload = trim_to_expected(flatten_chunks(chunks), expected)
    if getattr(ns, "dump_bin", None):
        Path(ns.dump_bin).expanduser().write_bytes(payload)
        print(f"dump_bin: {len(payload)} bytes -> {ns.dump_bin}", file=sys.stderr)
    if getattr(ns, "export_csv", None):
        dt = float(getattr(ns, "csv_dt", 1.0))
        interleaved = not getattr(ns, "no_interleaved", False)
        n = export_scope_csv(ns.export_csv, payload, dt_seconds=dt, interleaved=interleaved)
        mode = "CH1+CH2" if interleaved else "stream"
        print(f"export_csv: {n} filas ({mode}) -> {ns.export_csv}", file=sys.stderr)


def _cmd_get_source_data(ns: argparse.Namespace) -> None:
    """dsoHTGetSourceData: cabecera + lecturas; --smart para reintentos / estimación de bloques."""
    chunks = _run_source_data_capture(ns, clear_first=False)
    if getattr(ns, "parse", False):
        from hantek_usb.osc_decode import format_analyze_report, format_capture_summary, trim_to_expected, flatten_chunks

        expected = (int(ns.count_a) & 0xFFFF) + (int(ns.count_b) & 0xFFFF)
        il = not getattr(ns, "no_interleaved", False)
        print(format_capture_summary(chunks, expected_bytes=expected, interleaved=il))
        if getattr(ns, "analyze", False):
            payload = trim_to_expected(flatten_chunks(chunks), expected)
            print(format_analyze_report(payload, interleaved=il))
    elif not (
        getattr(ns, "dump_bin", None)
        or getattr(ns, "export_csv", None)
    ) or getattr(ns, "verbose", False):
        for chunk in chunks:
            print(_hex(chunk, ns.dense_hex))
    _finalize_capture_payload(ns, chunks)


def _cmd_get_real_data(ns: argparse.Namespace) -> None:
    """dsoHTGetRealData: igual que captura bulk; por defecto --smart y más bloques."""
    chunks = _run_source_data_capture(ns, clear_first=True)
    if getattr(ns, "parse", False):
        from hantek_usb.osc_decode import format_analyze_report, format_capture_summary, trim_to_expected, flatten_chunks

        expected = (int(ns.count_a) & 0xFFFF) + (int(ns.count_b) & 0xFFFF)
        il = not getattr(ns, "no_interleaved", False)
        print(format_capture_summary(chunks, expected_bytes=expected, interleaved=il))
        if getattr(ns, "analyze", False):
            payload = trim_to_expected(flatten_chunks(chunks), expected)
            print(format_analyze_report(payload, interleaved=il))
    elif not (
        getattr(ns, "dump_bin", None)
        or getattr(ns, "export_csv", None)
    ) or getattr(ns, "verbose", False):
        for chunk in chunks:
            print(_hex(chunk, ns.dense_hex))
    _finalize_capture_payload(ns, chunks)


def _cmd_factory_pulse(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = factory_setup_pulse()
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.wait_read:
            time.sleep(ns.sleep_s)
            if ns.verbose:
                print(
                    f"Esperados {ns.sleep_s}s (como el DLL); leyendo read-settings…",
                    file=sys.stderr,
                )
            pkt2 = read_all_settings()
            if ns.verbose:
                print(">>", _hex(pkt2, ns.dense_hex), file=sys.stderr)
            link.write(pkt2)
            rsp = link.read64()
            if getattr(ns, "parse", False):
                print(parse_resp.format_parsed_block("settings", rsp))
            else:
                print(_hex(rsp, ns.dense_hex))
        else:
            print(
                "Enviado pulso factory (dsoFactorySetup). Usa --wait-read para dormir y leer settings.",
                file=sys.stderr,
            )
    finally:
        link.close()


def _cmd_clear_buffer(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        rsp = link.read64()
        print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_work_type(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = work_type_packet(ns.mode & 0xFF, ns.read)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.read:
            rsp = link.read64()
            print(_hex(rsp, ns.dense_hex))
        else:
            label = constants.WORK_TYPE_LABELS.get(ns.mode & 0xFF, "?")
            print(f"ok (modo {ns.mode & 0xFF} = {label})")
    finally:
        link.close()


def _cmd_set_mode(ns: argparse.Namespace) -> None:
    """Atajo: dsoWorkType solo escritura con osc|dmm|dds."""
    key = ns.which
    mapping = {
        "osc": constants.WORK_TYPE_OSCILLOSCOPE,
        "dmm": constants.WORK_TYPE_MULTIMETER,
        "dds": constants.WORK_TYPE_SIGNAL_GENERATOR,
    }
    mode_byte = mapping[key]
    sub = argparse.Namespace(**vars(ns))
    sub.mode = mode_byte
    sub.read = False
    _cmd_work_type(sub)


def _cmd_dmm_type(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = dmm_set_type_packet(ns.dmm_type)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        print("ok")
    finally:
        link.close()


def _cmd_dmm_modes(_ns: argparse.Namespace) -> None:
    from hantek_usb import dmm_decode

    for i, name in enumerate(dmm_decode.DMM_MODE_NAMES_ORDERED):
        print(f"{i:2d}  {name}")
    print(
        "\nÍndices alineados con Lan_English.lug 11040–11050 (hipótesis). "
        "Si no coinciden con el equipo, rellena hantek_usb.dmm_decode.DMM_TYPE_FROM_BYTE.",
        file=sys.stderr,
    )


def _cmd_dds_waves(_ns: argparse.Namespace) -> None:
    for i in range(8):
        name = constants.DDS_WAVE_TYPE_LABELS.get(i, "?")
        print(f"{i}  {name}")
    print(
        "\nÍndices para `dds-wave N` (ddsSDKWaveType). arb1–arb4: señales arbitrarias "
        "(configurables en el aparato / software).",
        file=sys.stderr,
    )


def _cmd_dmm_read(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        settle_ms = ns.settle_ms
        if settle_ms is None:
            settle_ms = (
                80.0
                if (ns.ensure_dmm or ns.set_type is not None)
                else 0.0
            )

        sample_delay_ms = float(getattr(ns, "sample_delay_ms", 0.0) or 0.0)

        if ns.ensure_dmm:
            w = work_type_packet(constants.WORK_TYPE_MULTIMETER, read=False)
            if ns.verbose:
                print(">> ensure dmm", _hex(w, ns.dense_hex), file=sys.stderr)
            link.write(w)
            if settle_ms > 0:
                time.sleep(settle_ms / 1000.0)

        if ns.set_type is not None:
            st = dmm_set_type_packet(ns.set_type)
            if ns.verbose:
                print(">> set-type", _hex(st, ns.dense_hex), file=sys.stderr)
            link.write(st)
            if settle_ms > 0:
                time.sleep(settle_ms / 1000.0)

        pkt = dmm_get_data_packet()
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)

        reads = max(1, ns.reads)
        chunks: List[bytes] = []
        for i in range(reads):
            link.write(pkt)
            if sample_delay_ms > 0:
                if ns.verbose:
                    print(
                        f".. sample-delay {sample_delay_ms:g} ms antes de leer IN",
                        file=sys.stderr,
                    )
                time.sleep(sample_delay_ms / 1000.0)
            chunk = link.read64()
            chunks.append(chunk)
            if ns.verbose:
                print(
                    f"<< [{i + 1}/{reads}] {len(chunk)} B",
                    _hex(chunk, ns.dense_hex),
                    file=sys.stderr,
                )

        rsp = max(chunks, key=len) if chunks else b""
        if getattr(ns, "parse", False):
            print(parse_resp.format_parsed_block("dmm", rsp))
        else:
            print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_stm_id(ns: argparse.Namespace) -> None:
    _cmd_scope_query(ns, 0x01, "stm" if getattr(ns, "parse", False) else None)


def _cmd_fpga_version(ns: argparse.Namespace) -> None:
    _cmd_scope_query(ns, 0x0C, "fpga" if getattr(ns, "parse", False) else None)


def _cmd_arm_version(ns: argparse.Namespace) -> None:
    _cmd_scope_query(ns, 0x0A, "arm" if getattr(ns, "parse", False) else None)


def _cmd_get_device_cali(ns: argparse.Namespace) -> None:
    sub = (
        ns.subcode
        if getattr(ns, "subcode", None) is not None
        else constants.SCOPE31_DEVICE_CALI_DEFAULT
    )
    kind = "generic" if getattr(ns, "parse", False) else None
    _cmd_scope_query(ns, int(sub), kind)


def _cmd_device_name(ns: argparse.Namespace) -> None:
    sub = (
        int(ns.subcode)
        if getattr(ns, "subcode", None) is not None
        else constants.SCOPE31_DEVICE_NAME_DEFAULT
    )
    pkt = scope_query_3_1_custom(
        sub,
        read=ns.read_mode,
        word_at_6=0x7789 if ns.magic7789 else None,
    )
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.read_mode:
            rsp = link.read64()
            if getattr(ns, "parse", False):
                print(parse_resp.format_parsed_block("generic", rsp))
            else:
                print(_hex(rsp, ns.dense_hex))
        else:
            print("ok (solo escritura)")
    finally:
        link.close()


def _cmd_button_test(ns: argparse.Namespace) -> None:
    sub = (
        int(ns.subcode)
        if getattr(ns, "subcode", None) is not None
        else constants.SCOPE31_BUTTON_TEST_DEFAULT
    )
    pkt = scope_query_3_1_custom(sub, read=ns.read_mode)
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.read_mode:
            rsp = link.read64()
            if getattr(ns, "parse", False):
                print(parse_resp.format_parsed_block("generic", rsp))
            else:
                print(_hex(rsp, ns.dense_hex))
        else:
            print("ok")
    finally:
        link.close()


def _cmd_zero_cali(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        if getattr(ns, "payload_file", None):
            data = Path(ns.payload_file).expanduser().read_bytes()
            if ns.verbose:
                print(f">> zero-cali long {len(data)} B (file)", file=sys.stderr)
            link.write(data)
        elif getattr(ns, "packet_hex", None):
            raw = bytes.fromhex(str(ns.packet_hex).replace(" ", ""))
            if len(raw) != 10:
                raise SystemExit("zero-cali --packet-hex: exactamente 10 bytes.")
            link.write(raw)
        else:
            pkt = zero_cali_short_packet(
                int(ns.sub_byte5) if ns.sub_byte5 is not None else None
            )
            if ns.verbose:
                print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
            link.write(pkt)
        if ns.read_back:
            rsp = link.read64()
            print(_hex(rsp, ns.dense_hex))
        else:
            print("ok")
    finally:
        link.close()


def _cmd_fpga_update(ns: argparse.Namespace) -> None:
    from hantek_usb.fpga_script import load_script, run_script_writes

    script_path = Path(ns.script).expanduser()
    script = load_script(script_path)
    if ns.base_dir:
        script = dict(script)
        script["base_dir"] = str(Path(ns.base_dir).expanduser())
    else:
        script = dict(script)
        script.setdefault("base_dir", str(script_path.parent))

    link = _open(ns)
    try:

        def log(msg: str) -> None:
            print(msg, file=sys.stderr)

        run_script_writes(link, script, verbose=ns.verbose, log=log)
        print("ok")
    finally:
        link.close()


def _cmd_device_connect_info(ns: argparse.Namespace) -> None:
    """Solo informativo: exports Windows que no aplican a pyusb."""
    print(
        "dsoHTDeviceConnect / dsoGetDevPath / medición (dsoHTGetMeasure*) / dsoGetSampleRate\n"
        "son estado en RAM del proceso con el DLL oficial; en Linux con libusb no hay equivalente.\n"
        "Este CLI abre el dispositivo con pyusb (list, endpoints, read-settings, …).",
    )


def _cmd_decode_hex(ns: argparse.Namespace) -> None:
    """Decodifica hex pegado (sin USB); ver hantek_usb/parse_resp.py."""
    raw = bytes.fromhex(ns.hex_blob.replace(" ", ""))
    if getattr(ns, "dmm", False):
        print(parse_resp.format_parsed_block("dmm", raw))
    else:
        print(parse_resp.format_decode_only(raw))


def _cmd_04440(
    ns: argparse.Namespace,
    opcode: int,
    value: int,
    payload_bytes: int,
    wait: bool,
) -> None:
    link = _open(ns)
    try:
        pkt = fun_04440(opcode, value, payload_bytes, wait)
        if wait:
            rsp = _tx_rx10(link, pkt, ns, ack04440=opcode if ns.check_ack else None)
            print(_hex(rsp, ns.dense_hex))
        else:
            if ns.verbose:
                print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
            link.write(pkt)
            print("ok (sin lectura)")
    finally:
        link.close()


def _cmd_run_stop(ns: argparse.Namespace) -> None:
    """
    Por defecto usa la trama del firmware (FUN_080326b8: 00 0A 02 00 08 [run]…).
    La trama tipo DLL fun_04440(opcode 0x0C) en FUN_08032140 no aplica [5:6] al estado
    real de marcha/paro — solo hace eco. Ver --legacy-04440.
    """
    wait = not ns.no_wait
    if getattr(ns, "legacy_04440", False):
        # En varios firmwares 2xx2 el cambio visible en UI (Play/Stop) se aplica por 0x0C en write ([3]=0).
        _cmd_04440(
            ns,
            Opcodes04440.RUN_STOP,
            1 if ns.run else 0,
            2,
            False,
        )
        return

    link = _open(ns)
    try:
        pkt = scope_run_stop_stm32(bool(ns.run))
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        # Compatibilidad UI 2D42/2xx2: reflejar Play/Stop vía opcode 0x0C en modo write.
        # Esto evita casos donde la adquisición cambia pero el botón visual no acompaña (o viceversa).
        link.write(fun_04440(Opcodes04440.RUN_STOP, 1 if ns.run else 0, 2, False))
        if wait:
            try:
                rsp = link.read64()
                print(_hex(rsp, ns.dense_hex))
            except usb.core.USBError as e:
                if "timed out" in str(e).lower():
                    print(
                        "ok (timeout IN: FUN_080326b8 no envía bloque 64 B en RUN/STOP; "
                        "el cambio de estado igual puede aplicarse)",
                        file=sys.stderr,
                    )
                else:
                    raise
        else:
            print("ok")
    finally:
        link.close()


def _cmd_trig2(ns: argparse.Namespace, opcode: int) -> None:
    # En firmware STM32 (FUN_08031a9e), los setters FUN_04440 se aplican con [3]=0 (write).
    # Con [3]=1 solo se consulta/eco (FUN_08032140), sin cambiar estado.
    _cmd_04440(ns, opcode, ns.value & 0xFFFF, 2, False)


def _cmd_trig_hpos(ns: argparse.Namespace) -> None:
    # Mismo criterio que setters 0x0E–0x12: [3]=0 para aplicar (ver _cmd_trig2).
    _cmd_04440(ns, Opcodes04440.TRIGGER_HPOS, ns.value & 0xFFFFFF, 3, False)


def _cmd_trig_vpos(ns: argparse.Namespace) -> None:
    _cmd_04440(ns, Opcodes04440.TRIGGER_VPOS, ns.value & 0xFF, 1, False)


def _cmd_ch1(ns: argparse.Namespace, sub: int) -> None:
    op = ch_opcode(ns.channel, sub)
    _cmd_04440(ns, op, ns.value & 0xFF, 1, False)


def _cmd_ch_invert(ns: argparse.Namespace) -> None:
    """
    Opcode 0x18 escribe ``ram9c_byte9_plus_d``. Por defecto: leer ``read-settings``, aplicar XOR
    (0x02 en una pareja de capturas coincidió con invert menú ↔ LCD). ``--raw-byte`` fija el byte.
    """
    if int(ns.channel) != 0:
        raise SystemExit(
            "ch-invert: solo canal 0 (CH1 en pantalla) está mapeado en 2D42. "
            "CH2 requiere otra orden o más RE."
        )
    link = _open(ns)
    try:
        old_b: int | None = None
        mask = int(ns.xor_mask) & 0xFF
        if ns.raw_byte is not None:
            new_b = int(ns.raw_byte) & 0xFF
            pkt = scope_ram9c_byte9_packet(new_b)
        else:
            link.write(read_all_settings())
            rsp = link.read64()
            dec = parse_resp.decode_read_all_set_firmware25(rsp)
            if not dec.get("valid_layout"):
                raise SystemExit("read-settings: respuesta 0x15 no decodificable (¿modo scope?).")
            old_b = dec["fields"]["ram9c_byte9_plus_d"]["u8"]
            new_b = old_b ^ mask
            pkt = scope_ram9c_byte9_packet(new_b)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if old_b is not None:
            print(
                f"ram9c_byte9_plus_d: 0x{old_b:02x} → 0x{new_b:02x} (XOR 0x{mask:02x})",
                file=sys.stderr,
            )
        print(
            "Advertencia: en 2D42 esto puede dejar el disparo/traza inestable; "
            "si pasa, scope-autoset o ajustes desde el menú. Invert solo por panel hasta RE/diff estado.",
            file=sys.stderr,
        )
        print("ok")
    finally:
        link.close()


def _cmd_scope_autoset(ns: argparse.Namespace) -> None:
    _cmd_04440(ns, Opcodes04440.SCOPE_AUTOSET, 0, 1, False)


def _cmd_scope_zero(ns: argparse.Namespace) -> None:
    _cmd_04440(ns, Opcodes04440.SCOPE_ZERO_CALI, 0, 1, False)


def _cmd_trig_force(ns: argparse.Namespace) -> None:
    """Alias histórico: equivale a scope-zero-cali (0x17). En 2D42 la UI muestra Calibrating."""
    _cmd_scope_zero(ns)


def _cmd_dds_u32(ns: argparse.Namespace, sub: int) -> None:
    link = _open(ns)
    try:
        pkt = dds_packet(sub, wait=not ns.write_only, u32_value=ns.value)
        if ns.write_only:
            if ns.verbose:
                print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
            link.write(pkt)
            print("ok")
        else:
            if ns.verbose:
                print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
            link.write(pkt)
            rsp = link.read64()
            if getattr(ns, "parse", False):
                from hantek_usb import dds_decode

                print(
                    dds_decode.format_dds_response(
                        rsp,
                        sent_subcode=sub,
                        sent_u32=ns.value,
                    )
                )
            else:
                print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_dds_offset(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = dds_offset_packet(ns.value, read=not ns.write_only)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.write_only:
            print("ok")
        else:
            rsp = link.read64()
            if getattr(ns, "parse", False):
                from hantek_usb import dds_decode

                print(
                    dds_decode.format_dds_response(
                        rsp,
                        sent_subcode=OpcodesDDS.OFFSET,
                        sent_u32=None,
                    )
                )
                mag = abs(int(ns.value))
                sign = 1 if int(ns.value) < 0 else 0
                print(
                    f"  TX offset: mag_u16={mag} sign={sign} "
                    "(firmware FUN_080326b8: [5:6]=magnitud, [7]=signo)."
                )
            else:
                print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_dds_wave(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = dds_u16_packet(OpcodesDDS.WAVE_TYPE, ns.wave & 0xFFFF, read=not ns.write_only)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.write_only:
            print("ok")
        else:
            rsp = link.read64()
            if getattr(ns, "parse", False):
                from hantek_usb import dds_decode

                print(
                    dds_decode.format_dds_response(
                        rsp,
                        sent_subcode=OpcodesDDS.WAVE_TYPE,
                        sent_u32=ns.wave & 0xFFFF,
                    )
                )
            else:
                print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_dds_onoff(ns: argparse.Namespace) -> None:
    link = _open(ns)
    try:
        pkt = dds_onoff_packet(ns.on, read=not ns.write_only)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.write_only:
            print("ok")
        else:
            rsp = link.read64()
            if getattr(ns, "parse", False):
                from hantek_usb import dds_decode

                print(
                    dds_decode.format_dds_response(
                        rsp,
                        sent_subcode=OpcodesDDS.SET_ONOFF,
                        sent_u32=None,
                    )
                )
                print(
                    f"  TX: byte5 on/off = {1 if ns.on else 0} "
                    "(no es u32; la IN suele no reflejar este subcomando)."
                )
            else:
                print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_dds_trapezoid_duty(ns: argparse.Namespace) -> None:
    """
    Trapecio extendido (firmware): opcode 0x06 con 3 bytes:
    [5]=rise, [6]=high, [7]=fall.
    """
    link = _open(ns)
    try:
        pkt = dds_trap_three_packet(
            ns.rise & 0xFF,
            ns.high & 0xFF,
            ns.fall & 0xFF,
            wait=not ns.write_only,
        )
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        if ns.write_only:
            print("ok")
        else:
            rsp = link.read64()
            if getattr(ns, "parse", False):
                from hantek_usb import dds_decode

                print(
                    dds_decode.format_dds_response(
                        rsp,
                        sent_subcode=OpcodesDDS.TRAP_DUTY,
                        sent_u32=None,
                    )
                )
                print(
                    f"  TX trap3: rise={ns.rise & 0xFF} high={ns.high & 0xFF} "
                    f"fall={ns.fall & 0xFF} (bytes [5:8])."
                )
            else:
                print(_hex(rsp, ns.dense_hex))
    finally:
        link.close()


def _cmd_dds_options(ns: argparse.Namespace) -> None:
    use_f13f = ns.variant == "f13f"
    link = _open(ns)
    try:
        pkt = dds_set_options_packet(use_f13f)
        if ns.verbose:
            print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
        link.write(pkt)
        print("ok")
    finally:
        link.close()


def _cmd_raw(ns: argparse.Namespace) -> None:
    raw = bytes.fromhex(ns.hex_bytes.replace(" ", ""))
    if len(raw) != 10:
        raise SystemExit("raw: se requieren exactamente 10 bytes (20 dígitos hex).")
    link = _open(ns)
    try:
        if ns.verbose:
            print(">>", _hex(raw, ns.dense_hex), file=sys.stderr)
        link.write(raw)
        if ns.reads > 0:
            data = link.read_n(ns.reads)
            print(_hex(data, ns.dense_hex))
    finally:
        link.close()


def _cmd_cmd04440(ns: argparse.Namespace) -> None:
    wait = not ns.no_wait
    link = _open(ns)
    try:
        pkt = fun_04440(ns.opcode, ns.value, ns.payload_bytes, wait)
        if wait:
            rsp = _tx_rx10(
                link,
                pkt,
                ns,
                ack04440=ns.opcode if ns.check_ack else None,
            )
            print(_hex(rsp, ns.dense_hex))
        else:
            if ns.verbose:
                print(">>", _hex(pkt, ns.dense_hex), file=sys.stderr)
            link.write(pkt)
            print("ok")
    finally:
        link.close()


def _cmd_init_hard(ns: argparse.Namespace) -> None:
    """Equivalente a dsoInitHard → read-settings."""
    _cmd_read_settings(ns)


_EPILOG = """Documentación (repo, rutas relativas a la raíz del clon):
  dev_docs/pyhantek/PROTOCOLO_USB.md       Visión general USB
  dev_docs/hantek/EXPORTS_HTHardDll.md     Cada export y bloques de 64 B esperados
  dev_docs/pyhantek/IMPLEMENTACION_CHECKLIST.md  Pendientes y trazabilidad
"""


def _attach_get_source_data_args(
    p: argparse.ArgumentParser,
    *,
    with_clear_buffer: bool = False,
) -> None:
    p.add_argument(
        "--count-a",
        type=lambda x: int(x, 0),
        default=0x400,
        help="ushort LE en bytes [5:7] de opcode 0x16 (default 0x400)",
    )
    p.add_argument(
        "--count-b",
        type=lambda x: int(x, 0),
        default=0,
        help="ushort LE en bytes [7:9] de opcode 0x16 (default 0)",
    )
    p.add_argument(
        "--blocks",
        type=int,
        default=1,
        metavar="N",
        help="Bloques mínimos a leer (con --smart puede ampliarse hasta --max-total-blocks)",
    )
    p.add_argument("--smart", action="store_true")
    p.add_argument("--no-smart", action="store_false", dest="smart")
    p.set_defaults(smart=False)
    p.add_argument(
        "--retry-max",
        type=int,
        default=50,
        metavar="N",
        help="Con --smart: relecturas si el 1.er bloque parece vacío",
    )
    p.add_argument(
        "--sleep-ms",
        type=int,
        default=15,
        metavar="MS",
        help="Pausa entre reintentos (solo --smart)",
    )
    p.add_argument(
        "--max-total-blocks",
        type=int,
        default=1024,
        metavar="N",
        help="Tope de seguridad de bloques 64 B",
    )
    p.add_argument(
        "--parse",
        action="store_true",
        help="Resumen de captura (muestras crudas) en lugar de volcar todo en hex",
    )
    p.add_argument(
        "--analyze",
        action="store_true",
        help="Con --parse: métricas heurísticas (saturación, calidad) sobre el payload recortado",
    )
    p.add_argument(
        "--dump-bin",
        default=None,
        help="Guardar bytes de muestra crudos en archivo (recortado a count_a+count_b)",
    )
    p.add_argument(
        "--export-csv",
        default=None,
        metavar="FILE",
        help="CSV: por defecto dos canales index,time_s,ch1_u8,ch2_u8; con --no-interleaved una columna adc",
    )
    p.add_argument(
        "--csv-dt",
        type=float,
        default=1.0,
        metavar="S",
        help="Segundos entre muestras (time_s = index * S); solo escala el eje tiempo (default 1)",
    )
    p.add_argument(
        "--no-interleaved",
        action="store_true",
        help="Captura: un solo canal en CSV/analyze/parse (sin separar pares/impares CH1/CH2)",
    )
    if with_clear_buffer:
        p.add_argument(
            "--clear-buffer-first",
            action="store_true",
            help="Un read64 antes de la cabecera 55 0A (drenar IN)",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hantek 2xx2 (VID 0483; PID por defecto 2D42; 2D72: --pid 0x2d72) — CLI USB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")

    usb_p = _usb_parent()

    def add(name: str, fn: Callable[[argparse.Namespace], None], **kw: Any) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[usb_p], **kw)
        p.set_defaults(_fn=fn)
        return p

    # --- Diagnóstico ---
    p = sub.add_parser("list", help="Listar dispositivos USB")
    p.set_defaults(_fn=_cmd_list)

    add("endpoints", _cmd_endpoints, help="Mostrar endpoints BULK IN/OUT")
    add(
        "doctor",
        _cmd_doctor,
        help="Diagnóstico rápido: endpoints, read-settings --parse, STM/FPGA/ARM (query-31)",
    )

    # --- Información / consultas ---
    p = add(
        "read-settings",
        _cmd_read_settings,
        help="dsoHTReadAllSet (lectura) → 64 B",
    )
    p.add_argument(
        "--parse",
        action="store_true",
        help="Resumen heurístico (21 B / ASCII) en lugar de solo hex",
    )
    p = add(
        "write-settings",
        _cmd_write_settings,
        help="dsoHTReadAllSet (escritura 10 B, sin R64; byte [3]=0)",
    )
    p.add_argument(
        "--tail",
        metavar="HEX",
        default=None,
        help="Opcional: hasta 10 dígitos hex = 5 bytes para offsets 5–9",
    )

    p = add("stm-id", _cmd_stm_id, help="dsoGetSTMID → 64 B")
    p.add_argument("--parse", action="store_true", help="Texto ASCII aproximado")

    p = add("fpga-version", _cmd_fpga_version, help="dsoGetFPGAVersion → 64 B")
    p.add_argument("--parse", action="store_true")

    p = add("arm-version", _cmd_arm_version, help="dsoGetArmVersion → 64 B")
    p.add_argument("--parse", action="store_true")
    add(
        "automotive",
        lambda ns: _cmd_scope_query(ns, 0x07),
        help="dsoIsAutomotive (misma trama base que ddsSDKExist) → 64 B",
    )
    add(
        "dds-exist",
        lambda ns: _cmd_scope_query(ns, OpcodesDDS.EXIST_QUERY),
        help="ddsSDKExist → 64 B",
    )
    add("init-hard", _cmd_init_hard, help="dsoInitHard (equivale a read-settings)")

    p = add(
        "query-31",
        _cmd_query_31,
        help="Consulta genérica 00 0A 03 01 + subcódigo (byte 5) → 64 B",
    )
    p.add_argument(
        "subcode",
        type=lambda x: int(x, 0),
        help="Byte 5 de la trama (ej. 0x01 STM, 0x0A ARM, ver EXPORTS)",
    )
    p.add_argument("--parse", action="store_true")

    p = add(
        "get-device-cali",
        _cmd_get_device_cali,
        help=f"dsoGetDeviceCali (subcódigo por defecto 0x{constants.SCOPE31_DEVICE_CALI_DEFAULT:02x}; confirmar en .c)",
    )
    p.add_argument(
        "subcode",
        nargs="?",
        type=lambda x: int(x, 0),
        default=None,
        help="Override del byte 5 (opcional)",
    )
    p.add_argument("--parse", action="store_true")

    p = add(
        "device-name",
        _cmd_device_name,
        help="dsoDeviceName (patrón 00 0A 03 01; subcódigo heurístico; --magic7789)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--read", action="store_true", dest="read_mode")
    g.add_argument("--write", action="store_false", dest="read_mode")
    p.add_argument(
        "--subcode",
        type=lambda x: int(x, 0),
        default=None,
        help=f"Byte 5 (default 0x{constants.SCOPE31_DEVICE_NAME_DEFAULT:02x})",
    )
    p.add_argument(
        "--magic7789",
        action="store_true",
        help="Escribe uint16 0x7789 en bytes 6–7 (rama opcional del DLL)",
    )
    p.add_argument("--parse", action="store_true")

    p = add("button-test", _cmd_button_test, help="dsoSetButtonTest (10 B, subcódigo heurístico)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--read", action="store_true", dest="read_mode")
    g.add_argument("--write", action="store_false", dest="read_mode")
    p.add_argument(
        "--subcode",
        type=lambda x: int(x, 0),
        default=None,
        help=f"Byte 5 (default 0x{constants.SCOPE31_BUTTON_TEST_DEFAULT:02x})",
    )
    p.add_argument("--parse", action="store_true")

    p = add(
        "zero-cali",
        _cmd_zero_cali,
        help="dsoZeroCali: rama corta 10 B (heurística), o --packet-hex / --file",
    )
    p.add_argument(
        "--sub-byte5",
        type=lambda x: int(x, 0),
        default=None,
        help="Byte 5 de la trama corta (default ver constants.ZERO_CALI_SHORT_SUBBYTE5_DEFAULT)",
    )
    p.add_argument(
        "--packet-hex",
        default=None,
        help="Sustituye la trama corta por 10 bytes exactos en hex",
    )
    p.add_argument(
        "--file",
        "-f",
        dest="payload_file",
        default=None,
        help="Rama larga: enviar archivo completo",
    )
    p.add_argument(
        "--read-back",
        action="store_true",
        help="Tras escribir, leer un bloque de 64 B",
    )

    p = add(
        "fpga-update",
        _cmd_fpga_update,
        help="dsoUpdateFPGA: secuencia desde JSON (ver fpga_update ejemplo en README)",
    )
    p.add_argument(
        "script",
        help="Ruta a script.json (lista de steps hex/file)",
    )
    p.add_argument(
        "--base-dir",
        default=None,
        help="Directorio base para rutas relativas en el JSON (default: carpeta del .json)",
    )

    add(
        "windows-stub-info",
        _cmd_device_connect_info,
        help="Qué exports del DLL no tienen equivalente en pyusb",
    )

    p = add(
        "get-source-data",
        _cmd_get_source_data,
        help="dsoHTGetSourceData: cabecera 55 0A…16 + lecturas 64 B",
    )
    _attach_get_source_data_args(p)

    p = add(
        "get-real-data",
        _cmd_get_real_data,
        help="dsoHTGetRealData: captura con --smart por defecto; opcional drenar IN",
    )
    _attach_get_source_data_args(p, with_clear_buffer=True)
    p.set_defaults(smart=True, blocks=64, max_total_blocks=2048)

    def _work_type_dispatch(ns: argparse.Namespace) -> None:
        ns.read = bool(ns.read) and not ns.write_mode
        if ns.write_mode:
            ns.read = False
        _cmd_work_type(ns)

    p = add(
        "work-type",
        _work_type_dispatch,
        help="dsoWorkType: 0=osciloscopio, 1=multímetro, 2=generador (atajo: set-mode)",
    )
    p.add_argument(
        "mode",
        type=lambda x: int(x, 0),
        help="Byte de modo (0 osciloscopio, 1 multímetro, 2 generador)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--read", action="store_true", help="Consultar → lee 64 B")
    g.add_argument("--write", action="store_true", dest="write_mode", help="Solo escribir")
    p.set_defaults(read=False, write_mode=False)

    p = add(
        "set-mode",
        _cmd_set_mode,
        help="Cambiar modo sin número: osc | dmm | dds (equivale a work-type N --write)",
    )
    p.add_argument(
        "which",
        choices=("osc", "dmm", "dds"),
        help="osc=0 osciloscopio, dmm=1 multímetro, dds=2 generador",
    )

    p = add("factory-pulse", _cmd_factory_pulse, help="dsoFactorySetup (primer envío; ver EXPORTS)")
    p.add_argument(
        "--wait-read",
        action="store_true",
        help="Esperar y ejecutar read-settings en la misma sesión USB",
    )
    p.add_argument(
        "--sleep-s",
        type=float,
        default=3.0,
        help="Segundos de espera antes de read-settings (default 3)",
    )
    p.add_argument("--parse", action="store_true", help="Con --wait-read: salida parseada")
    add("clear-buffer", _cmd_clear_buffer, help="dsoClearBuffer (solo lectura 64 B)")

    p = add(
        "dmm-type",
        _cmd_dmm_type,
        help="dsoSetDMMType (5 B); índice 0..10 según lista de dmm-modes (hipótesis lug 11040+)",
    )
    p.add_argument("dmm_type", type=lambda x: int(x, 0))

    add(
        "dmm-modes",
        _cmd_dmm_modes,
        help="Lista índice→nombre de modo DMM (hipótesis desde .lug); sin USB",
    )

    p = add(
        "dmm-read",
        _cmd_dmm_read,
        help="dsoGetDMMData (pedido 64 B IN; la respuesta puede ser más corta)",
    )
    p.add_argument(
        "--parse",
        action="store_true",
        help="Decodificación DMM (float/µV, candidatos de modo) + patrón genérico",
    )
    p.add_argument(
        "--ensure-dmm",
        action="store_true",
        help="Antes: dsoWorkType escritura modo multímetro (p. ej. si estaba en osciloscopio)",
    )
    p.add_argument(
        "--set-type",
        type=lambda x: int(x, 0),
        default=None,
        metavar="N",
        help="Antes: dsoSetDMMType N (0..10, ver dmm-modes); p. ej. 5 = DC(V) hipótesis",
    )
    p.add_argument(
        "--settle-ms",
        type=float,
        default=None,
        metavar="MS",
        help="Pausa tras ensure-dmm / set-type (default 80 ms si usaste alguno, si no 0). "
        "Si cambias la fuente externa (p. ej. HA) antes de este comando, espera en el shell "
        "o usa un valor mayor (200–500 ms).",
    )
    p.add_argument(
        "--sample-delay-ms",
        type=float,
        default=0.0,
        metavar="MS",
        dest="sample_delay_ms",
        help="Tras cada petición dsoGetDMMData y antes de leer el IN: da tiempo al ADC/firmware "
        "(prueba 80–150 ms si la lectura oscila; 0 por defecto).",
    )
    p.add_argument(
        "--reads",
        type=int,
        default=1,
        metavar="N",
        help="Ciclos escribir petición + leer IN; se usa el bloque más largo (útil si el primero es corto)",
    )

    p = add(
        "device-sn",
        _cmd_device_sn,
        help="dsoDeviceSN: trama 10 o 37 B (hex o --file) → 64 B",
    )
    p.add_argument(
        "hex_payload",
        nargs="?",
        default=None,
        help="Hex (omitir si usas --file)",
    )
    p.add_argument("--file", "-f", dest="payload_file", default=None)

    p = add(
        "write-cali",
        _cmd_write_device_cali,
        help="dsoWriteDeviceCali: ≥5 B, trama completa (hex o --file)",
    )
    p.add_argument("hex_payload", nargs="?", default=None, help="Hex (omitir si usas --file)")
    p.add_argument("--file", "-f", dest="payload_file", default=None)

    p = add(
        "bulk-send",
        _cmd_bulk_send,
        help="Envío bulk (cualquier longitud) + opcional --reads bloques 64 B",
    )
    p.add_argument("hex_payload", nargs="?", default=None, help="Hex (omitir si usas --file)")
    p.add_argument("--file", "-f", dest="payload_file", default=None)
    p.add_argument(
        "--reads",
        type=int,
        default=0,
        metavar="N",
        help="Bloques de 64 B a leer tras escribir (default: 0)",
    )

    p = add(
        "write-banner",
        _cmd_write_banner,
        help="dsoWriteBanner: exactamente 30 bytes (hex o --file)",
    )
    p.add_argument("hex_payload", nargs="?", default=None, help="Hex (omitir si usas --file)")
    p.add_argument("--file", "-f", dest="payload_file", default=None)

    p = sub.add_parser(
        "dds-download",
        parents=[usb_p],
        help=(
            f"ddsSDKDownload: arb1–arb4 (firmware 0x400 B muestras + cab. "
            f"{DDS_DOWNLOAD_HEADER_LEN_SHORT} o {DDS_DOWNLOAD_HEADER_LEN_LONG} B); "
            f"total {DDS_DOWNLOAD_SIZE_SHORT} / {DDS_DOWNLOAD_SIZE_LONG} B"
        ),
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--short",
        action="store_const",
        const="short",
        dest="variant",
        help=f"Cuerpo {DDS_DOWNLOAD_SIZE_SHORT} (0x406) bytes",
    )
    g.add_argument(
        "--long",
        action="store_const",
        const="long",
        dest="variant",
        help=f"Cuerpo {DDS_DOWNLOAD_SIZE_LONG} (0x46C) bytes",
    )
    p.add_argument("hex_payload", nargs="?", default=None, help="Hex (omitir si usas --file)")
    p.add_argument("--file", "-f", dest="payload_file", default=None)
    p.set_defaults(_fn=_cmd_dds_download)

    # --- Osciloscopio (FUN_10004440) ---
    def _run_stop_dispatch(ns: argparse.Namespace) -> None:
        pause = getattr(ns, "pause", False)
        ns.run = not (ns.stop or pause)
        _cmd_run_stop(ns)

    p = add(
        "run-stop",
        _run_stop_dispatch,
        help="Marcha/paro (trama STM32 FUN_080326b8; ver --legacy-04440)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--stop", action="store_true")
    g.add_argument(
        "--pause",
        action="store_true",
        help="Igual que --stop (pausa adquisición; no hay otro opcode distinto en el protocolo mapeado)",
    )
    p.set_defaults(run=False, stop=False, pause=False)
    p.add_argument("--no-wait", action="store_true", help="Sin lectura de 64 B")
    p.add_argument(
        "--legacy-04440",
        action="store_true",
        help="Usar trama DLL fun_04440 opcode 0x0C (no controla bien RUN/STOP en el STM32)",
    )

    def _add_trig2(name: str, opcode: int, h: str) -> None:
        pp = add(name, lambda ns, op=opcode: _cmd_trig2(ns, op), help=h)
        pp.add_argument("value", type=lambda x: int(x, 0))
        pp.add_argument("--no-wait", action="store_true")

    _add_trig2("set-time-div", Opcodes04440.TIME_DIV, "dsoHTSetTimeDiv")
    _add_trig2("set-yt-format", Opcodes04440.YT_FORMAT, "dsoHTSetYTFormat")
    _add_trig2("set-trig-source", Opcodes04440.TRIGGER_SOURCE, "dsoHTSetTriggerSource")
    _add_trig2("set-trig-slope", Opcodes04440.TRIGGER_SLOPE, "dsoHTSetTriggerSlope")
    _add_trig2("set-trig-sweep", Opcodes04440.TRIGGER_SWEEP, "dsoHTSetTriggerSweep")

    p = add("set-trig-hpos", _cmd_trig_hpos, help="dsoHTSetTriggerHPos (3 B)")
    p.add_argument("value", type=lambda x: int(x, 0))
    p.add_argument("--no-wait", action="store_true")

    p = add("set-trig-vpos", _cmd_trig_vpos, help="dsoHTSetTriggerVPos (1 B)")
    p.add_argument("value", type=lambda x: int(x, 0))
    p.add_argument("--no-wait", action="store_true")

    def _add_ch(name: str, sub: int, h: str) -> None:
        pp = add(
            name,
            lambda ns, s=sub: _cmd_ch1(ns, s),
            help=h,
        )
        pp.add_argument("channel", type=int, help="Índice de canal (0, 1, …)")
        pp.add_argument("value", type=lambda x: int(x, 0))
        pp.add_argument("--no-wait", action="store_true")

    _add_ch("ch-onoff", 0, "dsoHTSetCHOnOff")
    _add_ch("ch-couple", 1, "dsoHTSetCHCouple")
    _add_ch("ch-probe", 2, "dsoHTSetCHProbe")
    _add_ch("ch-bw", 3, "dsoHTSetCHBWLimit")
    _add_ch("ch-volt", 4, "dsoHTSetCHVolt")
    _add_ch("ch-pos", 5, "dsoHTSetCHPos")

    p = add(
        "ch-invert",
        _cmd_ch_invert,
        help="[Experimental] Opcode 0x18: en 2D42 puede romper el disparo; invert usar menú. Ver dev_docs/pyhantek/PROTOCOLO_USB.md",
    )
    p.add_argument("channel", type=int, help="Solo 0 = CH1")
    p.add_argument(
        "--xor-mask",
        type=lambda x: int(x, 0),
        default=0x02,
        help="Máscara XOR sobre ram9c_byte9 antes de enviar 0x18 (default 0x02; otra sesión pudo usar 0x12)",
    )
    p.add_argument(
        "--raw-byte",
        type=lambda x: int(x, 0),
        default=None,
        dest="raw_byte",
        metavar="U8",
        help="Sin lectura: enviar este byte tal cual con opcode 0x18",
    )

    add("scope-autoset", _cmd_scope_autoset, help="dsoHTScopeAutoSet (solo escribe)")
    add(
        "scope-zero-cali",
        _cmd_scope_zero,
        help="dsoHTScopeZeroCali: opcode 0x17 (solo escribe). En 2D42 la pantalla muestra "
        "«Calibrating» (calibración/cero); es la orden correcta según el DLL, no el «Force Trigger» del manual.",
    )
    add(
        "trig-force",
        _cmd_trig_force,
        help="Alias de scope-zero-cali (0x17). Nombre engañoso: en 2D42 dispara calibración "
        "(mensaje Calibrating), no la acción «Force Trigger» del manual PDF.",
    )

    # --- DDS ---
    def _add_dds32(
        name: str,
        sub: int,
        h: str,
        *,
        value_help: str = "uint32 little-endian",
        default_write_only: bool = False,
    ) -> None:
        pp = add(name, lambda ns, s=sub: _cmd_dds_u32(ns, s), help=h)
        pp.add_argument("value", type=lambda x: int(x, 0), help=value_help)
        pp.add_argument(
            "--parse",
            action="store_true",
            help="Interpretar respuesta IN (subcode/u32); no implica eco fiable del valor",
        )
        g = pp.add_mutually_exclusive_group()
        g.add_argument(
            "--write-only",
            action="store_true",
            dest="write_only",
            help="Solo enviar (equivalente a param_3≠0 en DLL)",
        )
        g.add_argument(
            "--readback",
            action="store_false",
            dest="write_only",
            help="Forzar ruta de escritura+lectura (param_3=0), útil para comparar con DLL",
        )
        pp.set_defaults(write_only=default_write_only)

    _add_dds32(
        "dds-fre",
        OpcodesDDS.FREQUENCY,
        "ddsSDKFre. En 2D42 suele aplicar mejor en write puro por defecto; usa --readback para ruta DLL-like.",
        default_write_only=True,
    )
    _add_dds32(
        "dds-amp",
        OpcodesDDS.AMP,
        "ddsSDKAmp. En 2D42 suele aplicar mejor en write puro por defecto; usa --readback para ruta DLL-like.",
        default_write_only=True,
    )
    p = add(
        "dds-offset",
        _cmd_dds_offset,
        help="ddsSDKOffset. Firmware: [5:6]=magnitud u16, [7]=signo; el eco IN/LCD puede no reflejarlo.",
    )
    p.add_argument(
        "value",
        type=lambda x: int(x, 0),
        help="offset firmado (raw): >=0 positivo/cero, <0 negativo; magnitud máxima 65535",
    )
    p.add_argument(
        "--parse",
        action="store_true",
        help="Interpretar respuesta IN (no implica eco fiable del offset aplicado)",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--write-only",
        action="store_true",
        dest="write_only",
        help="Solo enviar (equivalente a param_3≠0 en DLL)",
    )
    g.add_argument(
        "--readback",
        action="store_false",
        dest="write_only",
        help="Forzar ruta de escritura+lectura (param_3=0), útil para comparar con DLL",
    )
    p.set_defaults(write_only=False)
    _add_dds32(
        "dds-square-duty",
        OpcodesDDS.SQUARE_DUTY,
        "ddsSDKSquareDuty (solo cuadrada). En 2D42: duty_lcd≈(value&0xFF)/100; ejemplo 65→0.65.",
        value_help="uint32 LE; regla práctica 2D42: usar value=round(duty*100), p.ej. 0.65→65",
    )
    _add_dds32(
        "dds-ramp-duty",
        OpcodesDDS.RAMP_DUTY,
        "ddsSDKRampDuty (0x05). En UI trapecio suele haber rise/high/fall duty; "
        "solo hay dos opcodes RAMP/TRAP en DLL — ver HALLAZGOS_DMM_DDS_2026-03.md § trapezoid.",
    )
    _add_dds32(
        "dds-trap-duty",
        OpcodesDDS.TRAP_DUTY,
        "ddsSDKTrapDuty (0x06) como uint32 LE. Trapecio de 3 sliders: usar `dds-trapezoid-duty` (bytes 5–7).",
    )
    p = add(
        "dds-trapezoid-duty",
        _cmd_dds_trapezoid_duty,
        help="Trapecio 3 parámetros en un envío (opcode 0x06): rise/high/fall en bytes 5/6/7.",
    )
    p.add_argument("rise", type=lambda x: int(x, 0), help="uint8 (0..255), sugerido duty*100")
    p.add_argument("high", type=lambda x: int(x, 0), help="uint8 (0..255), sugerido duty*100")
    p.add_argument("fall", type=lambda x: int(x, 0), help="uint8 (0..255), sugerido duty*100")
    p.add_argument("--write-only", action="store_true")
    p.add_argument(
        "--parse",
        action="store_true",
        help="Interpretar respuesta IN (subcode/u32); no implica eco fiable",
    )

    p = add(
        "dds-wave",
        _cmd_dds_wave,
        help="ddsSDKWaveType (ushort): 0 square, 1 triangular, 2 sine, 3 trapezoid, 4–7 arb1–arb4",
    )
    p.add_argument("wave", type=lambda x: int(x, 0))
    p.add_argument("--write-only", action="store_true")
    p.add_argument(
        "--parse",
        action="store_true",
        help="Interpretar respuesta IN (subcode/u32); no implica eco fiable",
    )

    add(
        "dds-waves",
        _cmd_dds_waves,
        help="Lista índice→tipo de onda DDS (sin USB)",
    )

    p = add("dds-onoff", _cmd_dds_onoff, help="ddsSDKSetOnOff")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    p.set_defaults(on=False, off=False)
    p.add_argument("--write-only", action="store_true")
    p.add_argument(
        "--parse",
        action="store_true",
        help="Interpretar respuesta IN (subcode/u32); no implica eco fiable",
    )

    def _dds_onoff_dispatch(ns: argparse.Namespace) -> None:
        ns.on = bool(ns.on) and not ns.off
        _cmd_dds_onoff(ns)

    p.set_defaults(_fn=_dds_onoff_dispatch)

    p = add("dds-options", _cmd_dds_options, help="ddsSDKSetOptions (0xf12f / 0xf13f)")
    p.add_argument("variant", choices=("f12f", "f13f"), help="Constante mágica del DLL")

    # --- Avanzado ---
    p = add("raw", _cmd_raw, help="10 bytes hex + N lecturas 64 B")
    p.add_argument("hex_bytes")
    p.add_argument("--reads", type=int, default=1)

    p = add(
        "cmd04440",
        _cmd_cmd04440,
        help="Armar FUN_10004440 genérico (scope; ver Opcodes04440 en protocol.py)",
    )
    p.add_argument("opcode", type=lambda x: int(x, 0))
    p.add_argument("value", type=lambda x: int(x, 0), nargs="?", default=0)
    p.add_argument("--bytes", type=int, default=2, dest="payload_bytes")
    p.add_argument("--no-wait", action="store_true")
    p.epilog = (
        "Opcode 0x18: puede inestabilizar disparo en 2D42; ``ch-invert`` solo RE. "
        "Sonda: cmd04440 0x18 0 --no-wait --bytes 1."
    )

    p = add(
        "decode-hex",
        _cmd_decode_hex,
        help="Interpretar una respuesta en hex (sin hardware); pega la salida del CLI",
    )
    p.add_argument("hex_blob", help="Hex con o sin espacios")
    p.add_argument(
        "--dmm",
        action="store_true",
        help="Tratar el buffer como respuesta dsoGetDMMData (misma salida que dmm-read --parse)",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fn = getattr(args, "_fn", None)
    if fn is None:
        print("Error interno: subcomando sin manejador (_fn).", file=sys.stderr)
        return 2
    try:
        fn(args)
    except HantekUsbError as e:
        print(e, file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    except usb.core.USBError as e:
        print(f"USB: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
