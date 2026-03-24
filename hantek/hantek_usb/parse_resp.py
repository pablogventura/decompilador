"""
Interpretación de bloques USB (respuestas del 2D42 / familia Hantek 2xx2).

Basado en tramas observadas con el CLI; el DLL puede usar offsets distintos.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from hantek_usb import constants

# Subcódigos enviados en consultas 00 0A 03 01 (byte tras el prefijo de 10 B)
SCOPE31_STM = 0x01
SCOPE31_ARM = 0x0A
SCOPE31_FPGA = 0x0C


def _ascii_runs(data: bytes) -> List[str]:
    out: List[str] = []
    for m in re.finditer(rb"[\x20-\x7e]{3,}", data):
        out.append(m.group().decode("ascii", "replace"))
    return out


def _hex_spaced(data: bytes, limit: int = 64) -> str:
    chunk = data[:limit]
    return " ".join(f"{b:02x}" for b in chunk) + (" …" if len(data) > limit else "")


def _nul_ascii(data: bytes, start: int) -> str:
    if start >= len(data):
        return ""
    end = data.find(b"\x00", start)
    if end < 0:
        end = len(data)
    return data[start:end].decode("ascii", "replace")


def decode_response_lines(data: bytes) -> List[str]:
    """
    Explicación en español de un IN bulk típico (cualquier longitud).
    """
    lines: List[str] = []
    n = len(data)
    lines.append(f"Longitud: {n} byte(s)")
    lines.append(f"Hex: {_hex_spaced(data, 80)}")

    if n == 0:
        lines.append("(vacío)")
        return lines

    b0, b1 = data[0], data[1] if n > 1 else 0

    if b0 == 0x55:
        lines.append(
            "Prefijo 0x55: mismo «mundo» que la cabecera 55 0A de captura (PROTOCOLO_USB.md); "
            "aquí es respuesta del firmware."
        )
    else:
        lines.append(
            f"Primer byte 0x{b0:02x}: no es 0x55; puede ser otro tipo de respuesta o transferencia corta."
        )

    if n >= 2:
        if b1 == 0x19:
            lines.append(
                "Byte [1]=0x19: en muchas respuestas de este modelo acompaña a 0x55 (tipo/longitud interna)."
            )
        else:
            lines.append(f"Byte [1]=0x{b1:02x}")

    # --- 55 19 … respuestas «gordas» (settings, consultas 3/1) ---
    if n >= 4 and data[0] == 0x55 and data[1] == 0x19:
        a, c = data[2], data[3]
        lines.append(
            f"Campos [2:4] = {a:02x} {c:02x}: suelen describir la orden consultada o un sub-bloque."
        )

        if a == 0x00 and c == 0x15:
            lines.append(
                "→ Parece respuesta a **dsoHTReadAllSet** (subcomando 0x15 en la petición de 10 B)."
            )
            if n >= 21:
                lines.append(
                    f"  Primeros 21 B (el DLL copia ~21 B a estado interno): {data[:21].hex()}"
                )
            if n >= 8:
                u32 = int.from_bytes(data[4:8], "little", signed=False)
                lines.append(f"  u32 little-endian en [4:8] = {u32} (0x{u32:08x})")
            if n >= 12:
                u32b = int.from_bytes(data[8:12], "little", signed=False)
                lines.append(f"  u32 little-endian en [8:12] = {u32b} (0x{u32b:08x})")
            for s in _ascii_runs(data):
                lines.append(f"  Texto ASCII detectado: «{s}»")

        elif a == 0x03 and c == SCOPE31_STM:
            lines.append("→ Respuesta tipo **dsoGetSTMID** (consulta con byte 5 = 0x01).")
            tail = _nul_ascii(data, 4)
            if tail:
                lines.append(f"  Cadena desde [4] hasta NUL: «{tail}»")
            for s in _ascii_runs(data[4:]):
                if s != tail:
                    lines.append(f"  Otro ASCII: «{s}»")

        elif a == 0x03 and c == SCOPE31_ARM:
            lines.append("→ Respuesta tipo **dsoGetArmVersion** (sub 0x0A).")
            tail = _nul_ascii(data, 4)
            if tail:
                lines.append(
                    f"  **Versión / build ARM (ASCII):** «{tail}» "
                    "(en tu equipo parecía una fecha tipo YYYYMMDD…)."
                )

        elif a == 0x03 and c == SCOPE31_FPGA:
            lines.append("→ Respuesta tipo **dsoGetFPGAVersion** (sub 0x0C).")
            if n >= 6:
                u16 = int.from_bytes(data[4:6], "little", signed=False)
                lines.append(f"  u16 LE en [4:6] = {u16} (0x{u16:04x})")
            if n >= 5:
                lines.append(f"  Byte [4] suelto también puede ser versión menor: 0x{data[4]:02x}")

        elif a == 0x03 and c == 0x00:
            lines.append("→ Eco relacionado con **dsoWorkType** (modo trabajo).")
            if n > 4:
                mb = data[4]
                name = constants.WORK_TYPE_LABELS.get(mb)
                if name:
                    lines.append(f"  Modo en [4]={mb}: **{name}**")
                lines.append(f"  Datos útiles a partir de [4]: {_hex_spaced(data[4:], 24)}")

        elif a == 0x03 and c == 0x03:
            lines.append("→ Posible eco de consulta con sub 0x03 (p. ej. automotive / ramas similares).")

        else:
            lines.append(
                "→ Subcódigo [2:4] no catalogado en este decodificador; compara con EXPORTS_HTHardDll.md."
            )
            for s in _ascii_runs(data):
                lines.append(f"  ASCII: «{s}»")

    # --- 55 05 … acuses cortos (run/stop, DDS, etc.) ---
    if n >= 4 and data[0] == 0x55 and data[1] == 0x05:
        lines.append("Patrón **55 05**: trama corta de acuse (similar a eco FUN_10004440 / familia corta).")
        if n >= 4 and data[2] == 0x00 and data[3] == 0x0C:
            lines.append(
                "  [2:4] = 00 0c → eco tipo **run/stop** por opcode 0x0C (DLL); en el STM32 el RUN/STOP "
                "real va por **00 0a 02 00 08** (FUN_080326b8), no por 0x0C en FUN_08032140."
            )
            if n >= 5:
                lines.append(f"  [4] = 0x{data[4]:02x} (valor o estado devuelto).")
        elif n >= 5 and data[2] == 0x03:
            lines.append(
                f"  [2:] = {_hex_spaced(data[2:], 16)} — eco de subfamilia 03 (p. ej. DDS / existencia)."
            )

    # --- DMM u otros que empiezan distinto ---
    if n >= 2 and data[0] == 0x55 and data[1] not in (0x05, 0x19):
        lines.append(
            f"Segundo byte 0x{data[1]:02x}: puede ser bloque DMM u otro canal (compara con trama enviada)."
        )

    if not any("→" in ln for ln in lines) and n >= 4:
        lines.append(
            "No hay plantilla fija: guarda el hex y crúzalo con el .c del export correspondiente."
        )

    return lines


def parse_settings_read_all_set(data: bytes) -> Dict[str, Any]:
    r: Dict[str, Any] = {"length": len(data)}
    if len(data) >= 10:
        r["header_hex"] = data[:10].hex()
    if len(data) >= 21:
        r["first_21_hex"] = data[:21].hex()
        r["byte_15"] = data[15]
    r["ascii_snippets"] = _ascii_runs(data)
    r["decode_lines"] = decode_response_lines(data)
    return r


def parse_version_string(data: bytes, start: int = 8) -> str:
    return _nul_ascii(data, start)


def parse_fpga_version_u16(data: bytes) -> Dict[str, Any]:
    if len(data) < 6:
        return {"raw": data.hex(), "note": "buffer corto"}
    v = int.from_bytes(data[4:6], "little", signed=False)
    return {"ushort_le_at_4": v, "ascii": parse_version_string(data, 8)}


def parse_dmm_block(data: bytes) -> Dict[str, Any]:
    from hantek_usb import dmm_decode

    return {
        "length": len(data),
        "ascii_snippets": _ascii_runs(data),
        "printable_guess": "".join(chr(b) if 32 <= b < 127 else "." for b in data[:32]),
        "decode_lines": decode_response_lines(data),
        "dmm": dmm_decode.decode_dmm_response(data),
    }


def format_parsed_block(kind: str, data: bytes) -> str:
    if kind == "dmm":
        from hantek_usb import dmm_decode

        parts = [dmm_decode.format_dmm_decode(data), "--- patrón USB genérico ---"]
        parts.extend(decode_response_lines(data))
        parts.append(f"--- subcomando CLI: {kind} ---")
        return "\n".join(parts)
    lines = decode_response_lines(data)
    lines.append(f"--- subcomando CLI: {kind} ---")
    return "\n".join(lines)


def format_decode_only(data: bytes) -> str:
    """Salida única para `decode-hex`."""
    return "\n".join(decode_response_lines(data))
