"""
Construcción de tramas según HTHardDll descompilado.
Ver hantek/EXPORTS_HTHardDll.md.
"""

from __future__ import annotations

import struct
from typing import Final

from hantek_usb.constants import ZERO_CALI_SHORT_SUBBYTE5_DEFAULT

# --- FUN_10004440 (órdenes scope: disparo, canales, run/stop, …) ---


def scope_run_stop_stm32(run: bool) -> bytes:
    """
    RUN/STOP según FUN_080326b8 + FUN_08034184 (ruta [2]==2, [3]==0).

    Con [4]==8: [5]==0 para STOP, [5]==1 para RUN (FUN_080326b8 líneas 121–134).
    No usar la trama FUN_04440 con opcode 0x0C: en FUN_08032140 esa orden solo hace eco
    de estado interno, no escribe el bit de marcha/paro desde [5:6].
    """
    return bytes(
        [
            0x00,
            0x0A,
            0x02,
            0x00,
            0x08,  # RUN_STOP_STM32 (FUN_080326b8; ver class Opcodes04440)
            0x01 if run else 0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )


def fun_04440(
    opcode: int,
    value: int = 0,
    payload_bytes: int = 2,
    wait_response: bool = True,
) -> bytes:
    """
    10 bytes: [0]=0 [1]=10 [2]=0 [3]=wait [4]=opcode [5:5+len]=value LE.
    """
    if not 1 <= payload_bytes <= 4:
        raise ValueError("payload_bytes debe estar entre 1 y 4")
    buf = bytearray(10)
    buf[0] = 0
    buf[1] = 10
    buf[2] = 0
    buf[3] = 1 if wait_response else 0
    buf[4] = opcode & 0xFF
    for i in range(payload_bytes):
        buf[5 + i] = (int(value) >> (8 * i)) & 0xFF
    return bytes(buf)


def ch_opcode(channel: int, sub: int) -> int:
    """sub 0..5: onoff, couple, probe, bw, volt, pos."""
    if channel < 0 or sub < 0 or sub > 5:
        raise ValueError("canal y sub(0..5) deben ser válidos")
    return channel * 6 + sub


class Opcodes04440:
    # En el DLL (FUN_10004440) el run/stop usa opcode 0x0C en [4] con prefijo [2]=0,[3]=1.
    # En el firmware STM32, esa ruta (FUN_08032140) **no aplica** el valor de [5:6]: solo
    # devuelve estado (ver FUN_08032140, rama bVar1==0x0C). El RUN/STOP real está en
    # FUN_080326b8: [2]=2 [3]=0 [4]=8 [5]=0|1 → `scope_run_stop_stm32`.
    RUN_STOP: Final = 0x0C
    RUN_STOP_STM32: Final = 0x08
    YT_FORMAT: Final = 0x0D
    TIME_DIV: Final = 0x0E
    TRIGGER_HPOS: Final = 0x0F
    TRIGGER_SOURCE: Final = 0x10
    TRIGGER_SLOPE: Final = 0x11
    TRIGGER_SWEEP: Final = 0x12
    SCOPE_AUTOSET: Final = 0x13
    TRIGGER_VPOS: Final = 0x14
    SCOPE_ZERO_CALI: Final = 0x17


# --- Familia “00 0A 03 01” + subcódigo byte 5 (consultas tipo dsoGet*) ---


def scope_query_3_1(subcode: int) -> bytes:
    return bytes([0x00, 0x0A, 0x03, 0x01, subcode & 0xFF, 0, 0, 0, 0, 0])


def scope_query_3_1_custom(
    subcode: int,
    *,
    read: bool = True,
    word_at_6: int | None = None,
) -> bytes:
    """
    Igual que `scope_query_3_1` pero [3]=0 si read=False (solo escribe).
    Si word_at_6 no es None, uint16 LE en bytes 6–7 (p. ej. magic 0x7789).
    Layout: [4] = subcódigo (como en scope_query_3_1).
    """
    b = bytearray(
        [
            0x00,
            0x0A,
            0x03,
            1 if read else 0,
            subcode & 0xFF,
            0,
            0,
            0,
            0,
            0,
        ]
    )
    if word_at_6 is not None:
        struct.pack_into("<H", b, 6, int(word_at_6) & 0xFFFF)
    return bytes(b)


def zero_cali_short_packet(sub_byte5: int | None = None) -> bytes:
    """dsoZeroCali (rama corta 10 B): patrón 00 0A 03 00 + sub en byte 5 (heurístico)."""
    s = ZERO_CALI_SHORT_SUBBYTE5_DEFAULT if sub_byte5 is None else int(sub_byte5)
    return bytes([0x00, 0x0A, 0x03, 0x00, s & 0xFF, 0, 0, 0, 0, 0])


def read_all_settings() -> bytes:
    """dsoHTReadAllSet lectura."""
    return bytes([0x00, 0x0A, 0x00, 0x01, 0x15, 0, 0, 0, 0, 0])


def write_all_settings_packet(tail_5: bytes | None = None) -> bytes:
    """
    dsoHTReadAllSet escritura (sin lectura R64): mismo prefijo que lectura pero
    byte en posición 3 = 0 en lugar de 1. Los 5 bytes finales (índices 5–9)
    suelen ser 0 hasta que el .c fije otra cosa.
    """
    b = bytearray([0x00, 0x0A, 0x00, 0x00, 0x15, 0, 0, 0, 0, 0])
    if tail_5:
        if len(tail_5) > 5:
            raise ValueError("tail_5: como máximo 5 bytes")
        for i, x in enumerate(tail_5):
            b[5 + i] = int(x) & 0xFF
    return bytes(b)


# ddsSDKDownload — longitud total del write (ver EXPORTS_HTHardDll.md)
DDS_DOWNLOAD_SIZE_SHORT: Final = 0x406
DDS_DOWNLOAD_SIZE_LONG: Final = 0x46C

# Bloque de muestras por slot arb en firmware (FUN_080326b8 → FUN_0801c9a4(..., 0x400, ...))
DDS_ARB_SAMPLE_BLOCK_BYTES: Final = 0x400

# Diferencia DLL vs bloque 0x400: cabecera delante del payload (layout exacto: solo en DLL/captura)
DDS_DOWNLOAD_HEADER_LEN_SHORT: Final = DDS_DOWNLOAD_SIZE_SHORT - DDS_ARB_SAMPLE_BLOCK_BYTES  # 6
DDS_DOWNLOAD_HEADER_LEN_LONG: Final = DDS_DOWNLOAD_SIZE_LONG - DDS_ARB_SAMPLE_BLOCK_BYTES  # 0x6C


def source_data_request_packet(count_a_u16: int = 0x400, count_b_u16: int = 0) -> bytes:
    """
    Petición para `dsoHTGetSourceData` / `dsoHTGetRealData` (opcode 0x16 en byte [4]).

    Firmware (`FUN_08032140`):
      total_bytes = ushort_le@[5] + ushort_le@[7]
    y devuelve esos bytes en bloques de hasta 0x40.
    """
    a = int(count_a_u16) & 0xFFFF
    b = int(count_b_u16) & 0xFFFF
    return bytes(
        [
            0x55,
            0x0A,
            0x00,
            # FUN_08034184: solo si [2]==0 y [3]==0x01 se llama FUN_08032140 (opcode 0x16 en [4]).
            0x01,
            0x16,
            a & 0xFF,
            (a >> 8) & 0xFF,
            b & 0xFF,
            (b >> 8) & 0xFF,
            0x00,
        ]
    )


def source_data_request_packet_legacy(ext_u16: int = 0) -> bytes:
    """
    Antes: trama con 0x01/0x16 en bytes 4–5 y cola 0x14; el despacho real exige [3]==0x01
    y opcode 0x16 en [4], igual que `source_data_request_packet(count_a, 0)`.
    """
    return source_data_request_packet(ext_u16, 0)


def factory_setup_pulse() -> bytes:
    """dsoFactorySetup primer envío."""
    return bytes([0x00, 0x0A, 0x03, 0x00, 0x0A, 0, 0, 0, 0, 0])


def work_type_packet(mode_byte: int, read: bool) -> bytes:
    """
    dsoWorkType: consulta (read=True) o escritura (read=False, modo en byte índice 5).

    Modos habituales (2xx2): 0=osciloscopio, 1=multímetro, 2=generador (ver constants).
    """
    b = bytearray(10)
    b[0] = 0
    b[1] = 10
    b[2] = 3
    b[3] = 1 if read else 0
    b[4] = 0
    b[5] = mode_byte & 0xFF
    return bytes(b)


# --- DDS: byte [2] = 2 ---


class OpcodesDDS:
    WAVE_TYPE: Final = 0x00
    FREQUENCY: Final = 0x01
    AMP: Final = 0x02
    OFFSET: Final = 0x03
    SQUARE_DUTY: Final = 0x04
    RAMP_DUTY: Final = 0x05
    TRAP_DUTY: Final = 0x06
    EXIST_QUERY: Final = 0x07
    SET_ONOFF: Final = 0x08
    SET_OPTIONS: Final = 0x0D


def dds_packet(
    subcode: int,
    *,
    wait: bool = True,
    u32_value: int | None = None,
) -> bytes:
    b = bytearray(10)
    b[0] = 0
    b[1] = 10
    b[2] = 2
    b[3] = 1 if wait else 0
    b[4] = subcode & 0xFF
    if u32_value is not None:
        struct.pack_into("<I", b, 5, u32_value & 0xFFFFFFFF)
    return bytes(b)


def dds_trap_three_packet(
    rise: int,
    high: int,
    fall: int,
    *,
    wait: bool = True,
) -> bytes:
    """
    Trapecio extendido (opcode 0x06): bytes 5,6,7 = rise/high/fall (uint8).

    Basado en firmware decompilado (`FUN_080326b8`): para subcomando 0x06
    el parser consume tres bytes independientes del payload.
    """
    b = bytearray(10)
    b[0] = 0
    b[1] = 10
    b[2] = 2
    b[3] = 1 if wait else 0
    b[4] = OpcodesDDS.TRAP_DUTY
    b[5] = int(rise) & 0xFF
    b[6] = int(high) & 0xFF
    b[7] = int(fall) & 0xFF
    return bytes(b)


def dds_u16_packet(subcode: int, u16: int, *, read: bool) -> bytes:
    """ddsSDKWaveType y similares: ushort en bytes 5–6."""
    b = bytearray(10)
    b[0] = 0
    b[1] = 10
    b[2] = 2
    b[3] = 1 if read else 0
    b[4] = subcode & 0xFF
    b[5] = u16 & 0xFF
    b[6] = (u16 >> 8) & 0xFF
    return bytes(b)


def dds_onoff_packet(on: bool, *, read: bool) -> bytes:
    """ddsSDKSetOnOff: sub 8, byte 5 = 0/1."""
    b = bytearray(10)
    b[0] = 0
    b[1] = 10
    b[2] = 2
    b[3] = 1 if read else 0
    b[4] = OpcodesDDS.SET_ONOFF
    b[5] = 1 if on else 0
    return bytes(b)


def dds_set_options_packet(use_f13f_variant: bool) -> bytes:
    """ddsSDKSetOptions: solo 0xf12f o 0xf13f."""
    # 00 0a 03 00 0d local_3b 00 00 00 00
    return bytes(
        [
            0x00,
            0x0A,
            0x03,
            0x00,
            0x0D,
            1 if use_f13f_variant else 0,
            0,
            0,
            0,
            0,
        ]
    )


# --- DMM 5 bytes ---


def dmm_set_type_packet(dmm_type: int) -> bytes:
    return bytes([0x00, 0x05, 0x01, 0x00, dmm_type & 0xFF])


def dmm_get_data_packet() -> bytes:
    return bytes([0x00, 0x05, 0x01, 0x01])


# --- Validación respuesta FUN_10004440 ---


def check_04440_ack(response: bytes, opcode: int) -> bool:
    if len(response) < 4:
        return False
    return response[3] == (opcode & 0xFF)
