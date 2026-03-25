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

# Mapeo empírico TIME_DIV (USB idx -> texto de pantalla), medido en hardware.
# Fuente: time_div_map_empirico.json en la raíz del proyecto pyhantek/ (sesión 2026-03-24).
TIME_DIV_LABELS: Dict[int, str] = {
    0: "5.000ns/div",
    1: "10.000ns/div",
    2: "20.00ns/div",
    3: "50.00ns/div",
    4: "100.0ns/div",
    5: "200.0ns/div",
    6: "500.0ns/div",
    7: "1.000us/div",
    8: "2.000us/div",
    9: "5.000us/div",
    10: "10.00us/div",
    11: "20.00us/div",
    12: "50.00us/div",
    13: "100.0us/div",
    14: "200.0us/div",
    15: "500.0us/div",
    16: "1.000ms/div",
    17: "2.000ms/div",
    18: "5.000ms/div",
    19: "10.00ms/div",
    20: "20.00ms/div",
    21: "50.00ms/div",
    22: "100.0ms/div",
    23: "200.0ms/div",
    24: "500.0ms/div",
    25: "1.000s/div",
    26: "2.000s/div",
    27: "5.000s/div",
    28: "10.00s/div",
    29: "20.00s/div",
    30: "50.00s/div",
    31: "100.0s/div",
    32: "200.0s/div",
    33: "500.0s/div",
}

# Flanco de disparo (USB idx → texto pantalla). Fuente: trig_slope_labels.json en pyhantek/ (2026-03-24).
TRIGGER_SLOPE_LABELS: Dict[int, str] = {
    0: "rising",
    1: "falling",
    2: "rising & falling (double)",
}

# Modo de barrido (USB idx → texto). Fuente: validación manual previa (PROTOCOLO_USB.md).
TRIGGER_SWEEP_LABELS: Dict[int, str] = {
    0: "Auto",
    1: "Normal",
    2: "Single",
}

# V/div por índice firmware (opcode ch×6+4). Fuente: ch_volt_map_empirico.json en pyhantek/
# (walk con --channel 1 = CH2; en la práctica CH1 suele compartir la misma escala).
# idx 10–11: en pantalla repitieron 100 mV / 200 mV (notas del usuario; posible wrap UI).
CH_VOLT_DIV_LABELS: Dict[int, str] = {
    0: "10 mV/div",
    1: "20 mV/div",
    2: "50 mV/div",
    3: "100 mV/div",
    4: "200 mV/div",
    5: "500 mV/div",
    6: "1 V/div",
    7: "2 V/div",
    8: "5 V/div",
    9: "10 V/div",
    10: "100 mV/div (idx alto; UI repite — ver nota)",
    11: "200 mV/div (idx alto; UI repite — ver nota)",
}


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
                "→ Respuesta a **dsoHTReadAllSet** (subcomando 0x15 en la petición de 10 B). "
                "El firmware STM32 arma **25 B** totales: ``[0]=0x55``, ``[1]=0x19`` (longitud), "
                "``[3]=0x15``, **21 B** de estado en ``[4:25]`` (ver ``FUN_08032140`` en "
                "``firmware/decompilado/``)."
            )
            if n >= 21:
                lines.append(
                    f"  Primeros 21 B (coinciden con lo que el DLL copia a estado): {data[:21].hex()}"
                )
            lines.append(
                "  Tabla campo a campo (RAM ``DAT_08032694`` / ``98`` / ``9c``): "
                "``read-settings --parse`` o ``parse_resp.format_read_all_set_firmware_decode``."
            )
            if n >= 8:
                u32 = int.from_bytes(data[4:8], "little", signed=False)
                lines.append(
                    f"  Nota: u32 LE [4:8]={u32} (0x{u32:08x}) **no** es un único registro lógico; "
                    f"el firmware envía **bytes sueltos** (ver ``decode_read_all_set_firmware25``)."
                )
            if n >= 12:
                u32b = int.from_bytes(data[8:12], "little", signed=False)
                lines.append(f"  Igual para u32 LE [8:12]={u32b} (0x{u32b:08x}).")
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
                "→ Subcódigo [2:4] no catalogado en este decodificador; compara con dev_docs/hantek/EXPORTS_HTHardDll.md."
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


def read_all_set_firmware_field_names() -> List[str]:
    """
    Nombres lógicos alineados con ``FUN_08032140`` (rama ``bVar1 == 0x15``, respuesta 25 B).

    Fuente: ``firmware/decompilado/FUN_08032140_08032140.c`` líneas 222–249: el firmware
    rellena ``puVar5[4..0x18]`` (21 bytes útiles) desde ``DAT_08032694``, ``DAT_08032690``,
    ``DAT_08032698``, ``DAT_0803269c``. Varios campos aplican ``+ 'd'`` (+100 decimal) al
    bajo byte de un ``ushort`` (posible formato display en el instrumento).

    **SRAM (referencia estática):** el puntero cargado desde el literal pool en flash
    ``~0x08032624`` apunta a ``0x2000cc4c``, primer byte = ``ram98_byte0``. Esa base cumple
    ``0x2000cc4c == 0x2000ca4c + 0x200`` (misma región que el pool time/div en
    ``ReportPoolTableXrefs``). Ver ``dev_scripts/ram98_sram_address.py`` y ``PROTOCOLO_USB.md``.
    """
    return [
        "ram94_u16_0x06_lo",
        "ram94_u16_0x18_lo",
        "ram94_u16_0x1e_lo",
        "ram94_u16_0x2a_lo",
        "ram94_u16_0x42_lo",
        "ram94_u16_0x3c_lo_plus_d",
        "ram94_u16_0x50_lo",
        "ram94_u16_0x62_lo",
        "ram94_u16_0x68_lo",
        "ram94_u16_0x74_lo",
        "ram94_u16_0x8c_lo",
        "ram94_u16_0x86_lo_plus_d",
        "ram90_byte_at_2",
        "ram98_byte0",
        "ram98_byte3",
        "ram98_word9_lo",
        "ram98_word9_hi",
        "ram9c_byte0",
        "ram9c_byte3",
        "ram9c_byte6",
        "ram9c_byte9_plus_d",
    ]


def decode_read_all_set_firmware25(data: bytes) -> Dict[str, Any]:
    """
    Decodifica los **21 bytes de payload** (índices 4..24) de la respuesta ReadAllSet de 25 B
    cuando coincide con el layout del firmware (cabecera ``55 19 00 15``).
    """
    names = read_all_set_firmware_field_names()
    out: Dict[str, Any] = {"valid_layout": False, "payload_len": 0, "fields": {}}
    if len(data) < 25 or data[0] != 0x55 or data[1] != 0x19 or data[3] != 0x15:
        return out
    out["valid_layout"] = True
    payload = data[4:25]
    out["payload_len"] = len(payload)
    for i, b in enumerate(payload):
        if i < len(names):
            name = names[i]
            entry: Dict[str, Any] = {"u8": b}
            if "plus_d" in name:
                entry["minus_100_u8"] = (b - 100) & 0xFF
            if name == "ram98_byte0":
                # Modo horizontal Y-T vs Roll: empírico 2D42 (diff read-settings al togglear Time).
                if b == 0:
                    entry["horizontal_mode_hint"] = "Y-T (empírico)"
                elif b == 1:
                    entry["horizontal_mode_hint"] = "Roll (empírico)"
                elif b == 2:
                    entry["horizontal_mode_hint"] = "X-Y (empírico)"
            if name == "ram98_byte3":
                # Índice de time/div observado en lectura 0x15 (FUN_08032140, byte [0x12]).
                if b in TIME_DIV_LABELS:
                    entry["time_div_label"] = TIME_DIV_LABELS[b]
                elif b == 34:
                    entry["time_div_label"] = "invalid_ui_overflow"
            if name == "ram9c_byte3" and b in TRIGGER_SLOPE_LABELS:
                entry["trigger_slope_label"] = TRIGGER_SLOPE_LABELS[b]
            if name == "ram9c_byte6" and b in TRIGGER_SWEEP_LABELS:
                entry["trigger_sweep_label"] = TRIGGER_SWEEP_LABELS[b]
            # Invert CH1: correlación menú ↔ byte (varía entre sesiones; ver COMPARACION_invert_CH1.txt).
            if name == "ram9c_byte9_plus_d" and b == 0x9D:
                entry["invert_ch1_hint"] = "pareja 0x9d/0x8f (XOR 0x12): posible invert OFF"
            if name == "ram9c_byte9_plus_d" and b == 0x8F:
                entry["invert_ch1_hint"] = "pareja 0x9d/0x8f (XOR 0x12): posible invert ON"
            if name == "ram9c_byte9_plus_d" and b == 0x97:
                entry["invert_ch1_hint"] = "pareja 0x97/0x95 (XOR 0x02): posible invert OFF"
            if name == "ram9c_byte9_plus_d" and b == 0x95:
                entry["invert_ch1_hint"] = "pareja 0x97/0x95 (XOR 0x02): posible invert ON"
            out["fields"][name] = entry
    return out


def format_read_all_set_firmware_decode(data: bytes) -> str:
    """Bloque de texto para anexar a ``--parse`` en ``read-settings``."""
    d = decode_read_all_set_firmware25(data)
    if not d.get("valid_layout"):
        return ""
    lines: List[str] = [
        "--- FUN_08032140 (firmware): payload 21 B @ [4:25] → estado RAM ---",
    ]
    for name, meta in d["fields"].items():
        s = f"  [{name}] = 0x{meta['u8']:02x} ({meta['u8']})"
        if "minus_100_u8" in meta:
            s += f"  |  (valor−100)&0xff = 0x{meta['minus_100_u8']:02x}"
        if "horizontal_mode_hint" in meta:
            s += f"  |  horiz={meta['horizontal_mode_hint']}"
        if "time_div_label" in meta:
            s += f"  |  time/div={meta['time_div_label']}"
        if "trigger_slope_label" in meta:
            s += f"  |  trig_slope={meta['trigger_slope_label']}"
        if "trigger_sweep_label" in meta:
            s += f"  |  trig_sweep={meta['trigger_sweep_label']}"
        if "invert_ch1_hint" in meta:
            s += f"  |  {meta['invert_ch1_hint']}"
        lines.append(s)
    lines.append(
        "  Referencia opcodes ``FUN_04440`` / canales: cruzar con ``Opcodes04440`` en protocol.py "
        "y con ``FUN_08031a9e`` (escritura por opcode en ``DAT_08032694``)."
    )
    return "\n".join(lines)


def parse_settings_read_all_set(data: bytes) -> Dict[str, Any]:
    r: Dict[str, Any] = {"length": len(data)}
    if len(data) >= 10:
        r["header_hex"] = data[:10].hex()
    if len(data) >= 21:
        r["first_21_hex"] = data[:21].hex()
        r["byte_15"] = data[15]
    r["firmware25"] = decode_read_all_set_firmware25(data)
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
    if kind == "settings":
        parts: List[str] = []
        fw = format_read_all_set_firmware_decode(data)
        if fw:
            parts.append(fw)
            parts.append("---")
        parts.extend(decode_response_lines(data))
        parts.append(f"--- subcomando CLI: {kind} ---")
        return "\n".join(parts)
    lines = decode_response_lines(data)
    lines.append(f"--- subcomando CLI: {kind} ---")
    return "\n".join(lines)


def format_decode_only(data: bytes) -> str:
    """Salida única para `decode-hex`."""
    return "\n".join(decode_response_lines(data))
