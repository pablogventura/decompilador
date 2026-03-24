"""
Interpretación de respuestas IN tras comandos DDS (familia 00 0A 02 …).

Observación en 2D42: el bulk IN suele ser **corto (~10 B)**, no 64 B completos.
En pruebas reales, el **u32 en [4:8] no coincidió** de forma fiable con el valor
escrito en el TX (ni el subcódigo en [3] con el comando enviado en todos los casos).

Hallazgos adicionales del chat de calibración:
- `dds-square-duty` en LCD parece depender del byte bajo: duty ~= (value & 0xFF) / 100.
- `dds-amp 1000` mostró 1.00 V en ese equipo concreto.
- `dds-offset` puede aceptar TX pero no reflejarse de forma fiable en IN/LCD.

Usar esta salida como **diagnóstico estructural**, no como eco verificado del set.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional

from hantek_usb.protocol import OpcodesDDS

_SUBNAME: Dict[int, str] = {
    OpcodesDDS.WAVE_TYPE: "WAVE_TYPE",
    OpcodesDDS.FREQUENCY: "FREQUENCY",
    OpcodesDDS.AMP: "AMP",
    OpcodesDDS.OFFSET: "OFFSET",
    OpcodesDDS.SQUARE_DUTY: "SQUARE_DUTY",
    OpcodesDDS.RAMP_DUTY: "RAMP_DUTY",
    OpcodesDDS.TRAP_DUTY: "TRAP_DUTY",
    OpcodesDDS.EXIST_QUERY: "EXIST_QUERY",
    OpcodesDDS.SET_ONOFF: "SET_ONOFF",
    OpcodesDDS.SET_OPTIONS: "SET_OPTIONS",
}


def parse_dds_response(data: bytes) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "length": len(data),
        "hex": data.hex(),
    }
    if len(data) < 4:
        out["nota"] = "Respuesta demasiado corta."
        return out

    out["prefix_0_3"] = " ".join(f"{b:02x}" for b in data[:4])
    if data[0] == 0x55 and len(data) >= 9:
        sc = data[3]
        u32 = struct.unpack_from("<I", data, 4)[0]
        out["byte_3_subcode_guess"] = sc
        out["subcode_name_guess"] = _SUBNAME.get(sc, f"0x{sc:02x}")
        out["u32_le_at_4"] = u32
    if len(data) >= 10 and data[-1] == 0x55:
        out["trailer_55"] = True
    out["advertencia"] = (
        "En hardware 2D42 el IN no replica de forma fiable el valor enviado ni "
        "siempre el subcomando; validar con pantalla del equipo o medición física."
    )
    return out


def format_dds_response(
    data: bytes,
    *,
    sent_subcode: Optional[int] = None,
    sent_u32: Optional[int] = None,
) -> str:
    d = parse_dds_response(data)
    lines: List[str] = []
    lines.append(f"DDS IN: {d['length']} B | {d.get('hex', '')}")
    if "u32_le_at_4" in d:
        lines.append(
            f"  [3] subcode (lectura): 0x{d['byte_3_subcode_guess']:02x} "
            f"→ {d.get('subcode_name_guess', '')} | u32@[4:8]={d['u32_le_at_4']}"
        )
    if sent_subcode is not None:
        match = (
            d.get("byte_3_subcode_guess") == (sent_subcode & 0xFF)
            if d.get("byte_3_subcode_guess") is not None
            else None
        )
        lines.append(
            f"  TX era subcode 0x{sent_subcode & 0xFF:02x} → "
            f"{'coincide [3]' if match else 'no coincide [3] (habitual en 2D42)'}"
        )
    if sent_u32 is not None and "u32_le_at_4" in d:
        same = d["u32_le_at_4"] == (sent_u32 & 0xFFFFFFFF)
        lines.append(
            f"  TX u32={sent_u32} vs IN u32={d['u32_le_at_4']} → "
            f"{'igual' if same else 'distinto (esperado en muchos casos)'}"
        )
    elif sent_u32 is None and "u32_le_at_4" in d and sent_subcode is not None:
        lines.append(
            f"  IN u32@[4:8]={d['u32_le_at_4']} (sin comparar: TX no usa u32 en este comando)"
        )
    lines.append(f"  {d.get('advertencia', '')}")
    return "\n".join(lines)
