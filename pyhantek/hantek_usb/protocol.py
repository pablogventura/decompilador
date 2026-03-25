"""
Construcción de tramas según HTHardDll descompilado.
Ver dev_docs/hantek/EXPORTS_HTHardDll.md (desde la raíz del repo).
"""

from __future__ import annotations

import math
import struct
from typing import Final, Literal, Sequence

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
    # dsoHTSetYTFormat (HTHardDll): único export que usa 0x0D. En FUN_08031a9e la rama
    # ``bVar1 < 0x0E`` con opcode 0x0D solo hace ``*DAT_080326b0 = 0``; no escribe el byte
    # de modo horizontal que refleja ``ram98_byte0`` en la respuesta 0x15.
    YT_FORMAT: Final = 0x0D
    TIME_DIV: Final = 0x0E
    TRIGGER_HPOS: Final = 0x0F
    TRIGGER_SOURCE: Final = 0x10
    TRIGGER_SLOPE: Final = 0x11
    TRIGGER_SWEEP: Final = 0x12
    SCOPE_AUTOSET: Final = 0x13
    TRIGGER_VPOS: Final = 0x14
    # Firmware `FUN_08031a9e`: opcode **0x18** (sin export en HTHardDll). FUN_04440 **1 B** en [5]
    # mueve ``ram9c_byte9_plus_d`` en la respuesta ``read-settings``; en 2D42 la escritura USB
    # puede **romper el disparo** (empírico) — no usar como invert operativo; ver PROTOCOLO_USB.md.
    SCOPE_FIRMWARE_ONLY_0x18: Final = 0x18
    # DLL: dsoHTScopeZeroCali. En hardware 2D42 la pantalla muestra «Calibrating» al enviar
    # esta orden (empírico). No confundir con «Force Trigger» del manual PDF: ese texto
    # describe otra acción de UI; el opcode 0x17 por USB es calibración/cero según DLL y prueba.
    SCOPE_ZERO_CALI: Final = 0x17


# Invert CH1 y ``ram9c_byte9_plus_d``: ver doble captura en ``captures/COMPARACION_invert_CH1.txt``.
# En una sesión 2D42 el menú solo alteró el **bit 1** del último byte (XOR ``0x02`` entre estados).
CH1_INVERT_TOGGLE_XOR_DEFAULT: Final = 0x02


def ram9c_byte9_apply_xor(current_u8: int, mask: int = CH1_INVERT_TOGGLE_XOR_DEFAULT) -> int:
    """Siguiente valor del byte para un toggle XOR (p. ej. máscara 0x02)."""
    return (int(current_u8) ^ (int(mask) & 0xFF)) & 0xFF


def scope_ram9c_byte9_packet(raw_u8: int) -> bytes:
    """Experimental: fija en bruto el byte leído como ``ram9c_byte9_plus_d`` (opcode 0x18)."""
    return fun_04440(Opcodes04440.SCOPE_FIRMWARE_ONLY_0x18, int(raw_u8) & 0xFF, 1, False)


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
    dsoHTReadAllSet escritura (``param_3 != 0`` en el DLL): prefijo como lectura pero
    byte [3]=0. ``FUN_10002060`` solo envía **10 B** al USB. El DLL copia hasta **21 B**
    desde el buffer de aplicación a ``DAT_100e20de`` (estado local), pero esos bytes
    extra **no** amplían el write USB; por tanto el CLI solo expone ``--tail`` de **5 B**
    en [5:9], alineado con lo que cabe en el paquete de 10. No alcanza para parchear
    solo el byte índice 13 del payload 0x15 (``ram98_byte0``) sin otra vía.
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

# Muestras arb: 512 × int16 LE (tamaño fijo en firmware)
DDS_ARB_NUM_SAMPLES: Final = DDS_ARB_SAMPLE_BLOCK_BYTES // 2


def dll_float_to_int16(f: float) -> int:
    """
    Conversión **float → int16** como en ``ddsSDKDownload`` (Ghidra: ``__ftol``,
    cast a ``short``, saturación a **±0x7FFF** si ``abs`` del resultado supera
    **0x7FFF**; en saturación el signo sale del **float** actual, no solo del
    entero truncado).

    Equivalente práctico a MSVC ``(short)(__int64)truncación`` y comprobación
    de rango sobre el valor **int16** resultante (incl. ``-32768`` → saturar).
    """
    if isinstance(f, float) and math.isnan(f):
        raise ValueError("dll_float_to_int16: NaN no es válido")
    t = math.trunc(f)
    lo = int(t) & 0xFFFF
    s = lo - 0x10000 if (lo & 0x8000) else lo
    ab = 32768 if s == -32768 else abs(s)
    if ab > 0x7FFF:
        return -0x7FFF if f <= 0.0 else 0x7FFF
    return s


def float_samples_to_dds_int16(samples: Sequence[float]) -> list[int]:
    """512 floats → 512 int16 con la misma regla que ``ddsSDKDownload``."""
    if len(samples) != DDS_ARB_NUM_SAMPLES:
        raise ValueError(
            f"se requieren exactamente {DDS_ARB_NUM_SAMPLES} floats; hay {len(samples)}"
        )
    return [dll_float_to_int16(float(x)) for x in samples]


def dds_long_chunked_blob_to_samples(blob: bytes) -> list[int]:
    """
    Recupera las **512** muestras **int16** desde el cuerpo **0x46C** (rama larga
    truncada). Inverso de ``dds_download_long_chunked_blob`` para el wire exacto.
    El bloque **17** solo aporta **19** muestras (bytes **1088..1131**).
    """
    if len(blob) != DDS_DOWNLOAD_SIZE_LONG:
        raise ValueError(
            f"blob largo: se requieren exactamente {DDS_DOWNLOAD_SIZE_LONG} B; hay {len(blob)}"
        )
    out = [0] * DDS_ARB_NUM_SAMPLES
    for i in range(18):
        off = i * 0x40
        n_shorts = 19 if i == 17 else 29
        for j in range(n_shorts):
            idx = i * 0x1D + j
            if idx >= DDS_ARB_NUM_SAMPLES:
                break
            out[idx] = struct.unpack_from("<h", blob, off + 6 + 2 * j)[0]
    return out


def dds_download_long_chunked_blob(
    samples: Sequence[int],
    arb_slot: int = 0,
) -> bytes:
    """
    Cuerpo **0x46C** de la rama **larga** de ``ddsSDKDownload`` (Ghidra:
    ``ddsSDKDownload_10004180.c`` cuando ``DAT_100e1b94[dev*0x2f6]==0``).

    El DLL rellena **18** bloques de **64 B** (``0x40``); ``FUN_10002060`` envía solo
    **0x46C** bytes (``FUN_10001c60``: 17×64 + 44 en el último trozo). Los últimos **20 B**
    del bloque 18 no se transmiten.

    Cada bloque ``i`` (0..17): cabecera 6 B ``[i+1][b1][0x02][0x00][0x07][slot+1]`` con
    ``b1 = 0x2c`` si ``i==17`` else ``0x40``; luego **29×int16** tomados de
    ``samples[i*29 : i*29+29]`` (índices fuera de rango → **0**).
    """
    if len(samples) != DDS_ARB_NUM_SAMPLES:
        raise ValueError(
            f"se requieren exactamente {DDS_ARB_NUM_SAMPLES} muestras; hay {len(samples)}"
        )
    s = int(arb_slot)
    if s < 0 or s > 3:
        raise ValueError("arb_slot debe ser 0..3 (arb1..arb4)")
    slot_b = (s + 1) & 0xFF
    raw = bytearray(18 * 0x40)
    for i in range(18):
        off = i * 0x40
        raw[off] = (i + 1) & 0xFF
        raw[off + 1] = 0x2C if i == 17 else 0x40
        raw[off + 2] = 0x02
        raw[off + 3] = 0x00
        raw[off + 4] = 0x07
        raw[off + 5] = slot_b
        base = i * 0x1D
        for j in range(29):
            idx = base + j
            v = int(samples[idx]) if idx < DDS_ARB_NUM_SAMPLES else 0
            if v < -32768:
                v = -32768
            elif v > 32767:
                v = 32767
            struct.pack_into("<h", raw, off + 6 + 2 * j, v)
    return bytes(raw[:DDS_DOWNLOAD_SIZE_LONG])


def dds_download_header_short(arb_slot: int = 0) -> bytes:
    """
    Cabecera **6 B** de la variante ``0x406`` según ``ddsSDKDownload`` en Ghidra
    (``../hantek/decompilado_HTHardDll/ddsSDKDownload_10004180.c``):
    ``00 00 02 00 07 (slot+1)``, con ``slot`` en **0..3** → arb1..arb4.
    Las muestras **int16** empiezan en el byte **6** del blob.
    """
    s = int(arb_slot)
    if s < 0 or s > 3:
        raise ValueError("arb_slot debe ser 0..3 (arb1..arb4)")
    return bytes([0x00, 0x00, 0x02, 0x00, 0x07, (s + 1) & 0xFF])


def dds_arb_samples_int16_le(samples: Sequence[int]) -> bytes:
    """
    Codifica **512** muestras signed int16 little-endian (bloque ``0x400`` B).

    Usado por el cuerpo final de ``ddsSDKDownload``; el firmware reordena pares
    de bytes al construir ``ushort`` internos antes de ``FUN_0801c9a4``.
    """
    if len(samples) != DDS_ARB_NUM_SAMPLES:
        raise ValueError(
            f"se requieren exactamente {DDS_ARB_NUM_SAMPLES} muestras; hay {len(samples)}"
        )
    return struct.pack(f"<{DDS_ARB_NUM_SAMPLES}h", *[int(x) for x in samples])


def build_dds_download_blob(
    samples_0x400: bytes,
    *,
    variant: Literal["short", "long"] = "short",
    header: bytes | None = None,
    arb_slot: int = 0,
) -> bytes:
    """
    Ensambla el cuerpo de ``ddsSDKDownload`` (tamaños según ``EXPORTS_HTHardDll``).

    - **short:** ``0x406`` = cabecera **6 B** + muestras **0x400 B**.
    - **long:** ``0x46C`` — por defecto el layout **en bloques de 64 B** de la rama larga
      del DLL (``dds_download_long_chunked_blob``), no ``0x6C`` lineal + muestras.

    ``samples_0x400`` debe ser exactamente **512×int16 LE** (p. ej. ``dds_arb_samples_int16_le``).

    **Cabecera short (por defecto):** ``dds_download_header_short(arb_slot)``.
    **Long** con ``header is None``: rama Ghidra **chunked** (condición ``DAT…==0`` en el DLL).
    **Long** con ``header`` de **0x6C** bytes: modo legado lineal ``header + samples_0x400`` (capturas USB antiguas).
    """
    if len(samples_0x400) != DDS_ARB_SAMPLE_BLOCK_BYTES:
        raise ValueError(
            f"muestras: se requieren exactamente {DDS_ARB_SAMPLE_BLOCK_BYTES} B; hay {len(samples_0x400)}"
        )
    if variant == "short":
        hlen = DDS_DOWNLOAD_HEADER_LEN_SHORT
    elif variant == "long":
        hlen = DDS_DOWNLOAD_HEADER_LEN_LONG
    else:
        raise ValueError("variant debe ser 'short' o 'long'")
    if variant == "long" and header is None:
        unpacked = struct.unpack(f"<{DDS_ARB_NUM_SAMPLES}h", samples_0x400)
        return dds_download_long_chunked_blob(unpacked, arb_slot=arb_slot)

    if header is None:
        if variant == "short":
            hdr = dds_download_header_short(arb_slot)
        else:
            raise ValueError("variant long sin header debe resolverse arriba (chunked)")
    else:
        if len(header) != hlen:
            raise ValueError(f"cabecera: se requieren {hlen} B; hay {len(header)}")
        hdr = bytes(header)
    return hdr + samples_0x400


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


def dds_offset_packet(offset_value: int, *, read: bool) -> bytes:
    """
    ddsSDKOffset (sub 0x03) según firmware `FUN_080326b8`:
    - bytes [5:6] = magnitud uint16 LE
    - byte  [7]   = signo (0 positivo/cero, 1 negativo)
    """
    v = int(offset_value)
    mag = abs(v)
    if mag > 0xFFFF:
        raise ValueError("dds-offset fuera de rango: |value| debe ser <= 65535")
    b = bytearray(10)
    b[0] = 0
    b[1] = 10
    b[2] = 2
    b[3] = 1 if read else 0
    b[4] = OpcodesDDS.OFFSET
    b[5] = mag & 0xFF
    b[6] = (mag >> 8) & 0xFF
    b[7] = 1 if v < 0 else 0
    b[8] = 0
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
