"""
Bucle tipo FUN_10005010 / dsoHTGetSourceData: reintentos y lectura por trozos.

En el firmware (FUN_08032140) cada transferencia devuelve hasta 64 B; hay que
reenviar la misma petición 0x16 para recibir el siguiente trozo hasta completar
count_a + count_b.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, List, Optional

from hantek_usb.osc_decode import firmware_buffer_not_ready
from hantek_usb.protocol import source_data_request_packet, source_data_request_packet_legacy

if TYPE_CHECKING:
    from hantek_usb.transport import HantekLink


def likely_not_ready(block: bytes) -> bool:
    """True si el bloque parece buffer vacío / no listo (heurística + patrón firmware)."""
    if firmware_buffer_not_ready(block):
        return True
    if len(block) < 16:
        return False
    return block[:16] == b"\x00" * 16


def estimate_extra_blocks(total_bytes: int) -> Optional[int]:
    """Bloques adicionales de 64 B tras el primero (cota inferior)."""
    n = int(total_bytes)
    if n <= 0:
        return None
    total_blocks = (n + 63) // 64
    return max(0, total_blocks - 1)


def _accumulated_len(chunks: List[bytes]) -> int:
    return sum(len(c) for c in chunks)


def smart_source_data_capture(
    link: HantekLink,
    count_a_u16: int,
    count_b_u16: int,
    *,
    blocks_fixed: int,
    smart: bool,
    retry_max: int,
    sleep_ms: int,
    max_total_blocks: int,
    verbose: bool,
    emit: Callable[[str], None],
    hex_fmt: Callable[[bytes], str],
) -> List[bytes]:
    """
    Por cada trozo: escribe la petición 0x16 y lee un bloque IN (hasta 64 B).
    Reintenta el primer par escribir+leer si smart y el bloque parece vacío.
    """
    pkt = source_data_request_packet(count_a_u16, count_b_u16)
    emit(f">> {hex_fmt(pkt)}")

    total_bytes = (int(count_a_u16) & 0xFFFF) + (int(count_b_u16) & 0xFFFF)
    out: List[bytes] = []
    idx = 0

    while True:
        idx += 1
        if idx > max_total_blocks:
            break

        link.write(pkt)
        chunk = link.read64()
        retries = 0
        if smart and idx == 1:
            while likely_not_ready(chunk) and retries < retry_max:
                retries += 1
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000.0)
                if verbose:
                    emit(f"<< reintento {retries}/{retry_max} {hex_fmt(chunk)}")
                link.write(pkt)
                chunk = link.read64()

        out.append(chunk)
        emit(f"<< [{len(out)}] {hex_fmt(chunk)}")

        if total_bytes == 0:
            break

        if _accumulated_len(out) >= total_bytes:
            break

        if not smart and idx >= max(blocks_fixed, 1):
            break

    return out


def smart_source_data_capture_legacy(
    link: HantekLink,
    ext_u16: int,
    *,
    blocks_fixed: int,
    smart: bool,
    retry_max: int,
    sleep_ms: int,
    max_total_blocks: int,
    verbose: bool,
    emit: Callable[[str], None],
    hex_fmt: Callable[[bytes], str],
) -> List[bytes]:
    """Misma lógica; la trama legacy coincide con count_b=0."""
    return smart_source_data_capture(
        link,
        ext_u16,
        0,
        blocks_fixed=blocks_fixed,
        smart=smart,
        retry_max=retry_max,
        sleep_ms=sleep_ms,
        max_total_blocks=max_total_blocks,
        verbose=verbose,
        emit=emit,
        hex_fmt=hex_fmt,
    )
