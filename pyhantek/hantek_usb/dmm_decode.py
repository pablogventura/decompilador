"""
Decodificación heurística de la respuesta a dsoGetDMMData (bloque ≤64 B).

Validado contra firmware decompilado (HantekHTX2021090901):
- Frame DMM corto: 14 B, cabecera 55 0B ... 55.
- El "modo de función" viaja en byte [3] (salida de FUN_08031698).
- Los bytes [11] y [12] son flags/subrango derivados de bits, no enum de modo.
"""

from __future__ import annotations

import math
import struct
from typing import Any, Dict, List, Optional, Tuple

# Orden de strings de UI (11040…11050) → índice 0..10 como posible enum del firmware
DMM_MODE_NAMES_ORDERED: List[str] = [
    "AC(A)",
    "DC(A)",
    "AC(mA)",
    "DC(mA)",
    "DC(mV)",
    "DC(V)",
    "AC(V)",
    "C",  # capacitancia
    "RES",  # resistencia
    "COUNT",
    "Diode",
]

# Si el byte de tipo no coincide con 0..len-1, añade aquí tras RE (byte → nombre)
DMM_TYPE_FROM_BYTE: Dict[int, str] = {}


def _guess_mode_from_byte(b: int) -> str:
    if b in DMM_TYPE_FROM_BYTE:
        return DMM_TYPE_FROM_BYTE[b]
    if 0 <= b < len(DMM_MODE_NAMES_ORDERED):
        return DMM_MODE_NAMES_ORDERED[b] + " (índice lug 11040+N, hipótesis)"
    return f"desconocido (byte tipo 0x{b:02x})"


def _try_float_le(buf: bytes, off: int) -> Optional[float]:
    if off + 4 > len(buf):
        return None
    (v,) = struct.unpack_from("<f", buf, off)
    if math.isnan(v) or math.isinf(v):
        return None
    if not (-1e9 <= v <= 1e9):
        return None
    return float(v)


def _try_i32_le(buf: bytes, off: int) -> Optional[int]:
    if off + 4 > len(buf):
        return None
    return struct.unpack_from("<i", buf, off)[0]


def _decode_volt_fmt02(d7: int, d8: int, d9: int, d10: int) -> Optional[float]:
    """
    Barrido Home Assistant RD6006 + 2D42 DMM (mar 2026): [6]==0x02.

    - [7]==0: V = [8] + ([9]*10+[10])/100  (aprox. 0–9,99 V)
    - [7]>=1: V = ([7]*10+[8]) + ([9]*10+[10])/100  (aprox. 10–99,99 V)

    [9],[10] deben ser dígitos decimales 0–9; si [9] o [10] > 9 (p. ej. 7,77 V), no aplica.
    """
    if d9 > 9 or d10 > 9:
        return None
    frac = (d9 * 10 + d10) / 100.0
    if d7 == 0:
        return float(d8) + frac
    return float(d7 * 10 + d8) + frac


def _decode_ac_volt_fmt03_empirical(
    b3: int, d7: int, d8: int, d9: int, d10: int
) -> Tuple[Optional[float], str]:
    """
    AC(V) (`b3==6`): en 2D42 aparece `[6]==0x03` con dígitos que no siguen la misma
    regla que DC; una captura con LCD ~0 V dio `[7:10]=02 08 09 03`.
    """
    if b3 != 6 or (d7, d8, d9, d10) != (0x02, 0x08, 0x09, 0x03):
        return None, ""
    return (
        0.0,
        "[6]=03, AC(V): patrón 02 08 09 03 → ~0 V (empírico 2D42, sin señal / casi cero)",
    )


def _decode_capacitance_fmt03(
    d7: int, d8: int, d9: int, d10: int
) -> Tuple[Optional[float], str]:
    """
    Modo capacidad (`b3==7`), `[6]==0x03`.

    Empírico 2D42: magnitud en **nanofarads** como entero BCD en `[7:10]`:

    ``nF = [7]*1000 + [8]*100 + [9]*10 + [10]`` → ``F = nF * 1e-9``.

    Ejemplos: ceros → 0 nF; capacitor ~1 µF → ``00 09 03 01`` → 931 nF (≈0,93 µF).
    """
    if any(x > 9 for x in (d7, d8, d9, d10)):
        return None, ""
    n_nF = d7 * 1000 + d8 * 100 + d9 * 10 + d10
    f_val = n_nF * 1e-9
    if n_nF == 0:
        return (
            0.0,
            "[6]=03, capacidad: [7:10]=0 → 0 F (sin componente / descargado; empírico 2D42)",
        )
    return (
        f_val,
        f"[6]=03, capacidad: nF=[7]*1000+[8]*100+[9]*10+[10]={n_nF} → {f_val:.6e} F "
        "(empírico 2D42)",
    )


def _decode_diode_volt_fmt03(
    d7: int, d8: int, d9: int, d10: int
) -> Tuple[Optional[float], str]:
    """
    Modo diodo (`b3==10`), `[6]==0x03`: caída directa en V (empírico 2D42).

    Trama usuario: `[7:10]=00 06 09 02` → LCD ~0,697 V; la trama da **0,692 V**
    con ``([8]*100+[9]*10+[10])/1000`` (puede diferir unos mV del LCD o del instante).
    """
    if d7 != 0:
        return None, ""
    if any(x > 9 for x in (d8, d9, d10)):
        return None, ""
    v = (d8 * 100 + d9 * 10 + d10) / 1000.0
    return (
        v,
        f"[6]=03, diodo: ([8]*100+[9]*10+[10])/1000 = {v:.4f} V "
        "(caída directa, empírico 2D42)",
    )


def _decode_volt_fmt03(d7: int, d8: int, d9: int, d10: int) -> Tuple[Optional[float], str]:
    """
    Subformato [6]==0x03 (tensión baja / otro rango). Validado: 0 V, 2,5 V; 3,33 V
    como (300+30+3)/100; 1,00 V con patrón 09 09 08 (aún sin fórmula cerrada).

    Devuelve (valor | None, formula o motivo).
    """
    if d7 == 0 and d8 == 0 and d9 == 0 and d10 == 0:
        return 0.0, "[6]=03 y [7:10]=0 → 0 V"

    if d7 == 2 and d8 == 5 and d9 == 0 and d10 in (0, 3):
        return 2.5, "[6]=03, patrón 02 05 00 (00|03) → 2,50 V (validado hardware)"

    if d7 == 3 and d8 == 3 and d9 == 3 and d10 == 1:
        v = (d7 * 100 + d8 * 10 + d9) / 100.0
        return v, f"[6]=03, ({d7}{d8}{d9})/100 = {v:.2f} V (validado HA)"

    if d7 == 0 and d8 == 9 and d9 == 9 and d10 == 8:
        return 1.0, "[6]=03, patrón 09 09 08 → 1,00 V (empírico HA; fórmula general pendiente)"

    if d7 == 1 and d8 == 0 and d9 == 0 and d10 == 0:
        return 1.0, "[6]=03, patrón 01 00 00 00 → 1,00 V (validado hardware)"

    return None, "subformato [6]=03 no reconocido"


def _is_ol_display(d7: int, d8: int, d9: int, d10: int) -> bool:
    """Patrón pantalla overload / abierto: segmento 'L' (0x4C) en [9]."""
    return d7 == 0xFF and d8 == 0x00 and d9 == 0x4C and d10 == 0xFF


def _unidad_por_modo(b3: int) -> str:
    """Unidad lógica según índice de modo en [3] (alineado con DMM_MODE_NAMES_ORDERED)."""
    u = {
        0: "A",
        1: "A",
        2: "mA",
        3: "mA",
        4: "mV",
        5: "V",
        6: "V",
        7: "F",
        8: "Ω",
        9: "",
        10: "V",
    }
    return u.get(b3, "?")


def _etiqueta_sobrecarga(b3: int) -> str:
    if b3 == 8:
        return "resistencia: OL / fuera de rango"
    if b3 == 9:
        return "conteo: fuera de rango / sin lectura"
    if b3 == 10:
        return "diodo: OL (abierto / sin carga útil; patrón FF 00 4C FF)"
    return "sobrecarga o lectura no numérica (OL)"


def _base_packet_fields(
    *,
    b2: int,
    b3: int,
    b5: int,
    b6: int,
    d7: int,
    d8: int,
    d9: int,
    d10: int,
    b11: int,
    b12: int,
    mode_name: str,
) -> Dict[str, Any]:
    return {
        "frame_ok": True,
        "bytes_5_12": (
            f"{b5:02x} {b6:02x} {d7:02x} {d8:02x} {d9:02x} {d10:02x} {b11:02x} {b12:02x}"
        ),
        "byte_2": b2,
        "modo_byte_3": b3,
        "modo_nombre_3": mode_name,
        "subformato_6": f"0x{b6:02x}",
        "rango_byte_11": b11,
        "flags_byte_12": b12,
    }


def _try_decode_ohm_continuity_14(
    b6: int, b11: int, b12: int, d7: int, d8: int, d9: int, d10: int
) -> Optional[Dict[str, Any]]:
    """
    Continuidad / Ω en 2D42: trama con [6]=0x01 y [12]=0x02 (distinta del voltaje [6]=02/03).

    - **Abierto (OL)** en pantalla: ``FF 00 4C FF`` en [7:10] (0x4C = 'L' en ASCII).
    - **Corto ~0,5 Ω** (000.5): ``00 00 00 05`` en [7:10] → Ω = ([7][8][9] como miliohm
      implícitos)/1000 + [10]/10  →  0 + 0,5.
    """
    if b6 != 0x01 or b12 != 0x02:
        return None
    # OL (captura usuario: puntas al aire, pantalla OL)
    if d7 == 0xFF and d10 == 0xFF and d9 == 0x4C and d8 == 0x00:
        return {
            "circuito_abierto": True,
            "valor_ohm": None,
            "formula": "OL: [7]=FF, [8]=00, [9]=4C ('L'), [10]=FF",
            "unidad_guess": "Ω",
            "modo_fisico": "continuidad / Ω",
            "omit_float_heuristic": True,
        }
    if d7 <= 9 and d8 <= 9 and d9 <= 9 and d10 <= 9:
        ohm = (d7 * 100 + d8 * 10 + d9) / 1000.0 + d10 / 10.0
        return {
            "circuito_abierto": False,
            "valor_ohm": ohm,
            "valor": ohm,
            "formula": (
                f"Ω = (([7]*100+[8]*10+[9])/1000)+[10]/10 = {ohm:.4f} "
                f"(formato pantalla tipo 000.X)"
            ),
            "unidad_guess": "Ω",
            "modo_fisico": "continuidad / Ω",
            "omit_float_heuristic": True,
        }
    return None


def decode_dmm_packet_14(data: bytes) -> Optional[Dict[str, Any]]:
    """
    Formato observado en 2D42 (IN corto): 14 B, 55 0B … 55.

    - **[3]**: modo de función (FUN_08031698).
    - **[6]**: subformato de dígitos (1 = rama Ω/continuidad típica; 2/3 = escalas tipo display).
    - **[11]/[12]**: flags de rango/estado (no modo).

    La misma disposición de dígitos [7:10] se reutiliza en varios modos; la unidad depende de [3].
    """
    if len(data) != 14:
        return None
    if data[0] != 0x55 or data[1] != 0x0B or data[13] != 0x55:
        return None

    b2, b3, b5, b6 = data[2], data[3], data[5], data[6]
    d7, d8, d9, d10 = data[7], data[8], data[9], data[10]
    b11, b12 = data[11], data[12]
    mode_name = _guess_mode_from_byte(b3)
    unit_mode = _unidad_por_modo(b3)

    base = _base_packet_fields(
        b2=b2,
        b3=b3,
        b5=b5,
        b6=b6,
        d7=d7,
        d8=d8,
        d9=d9,
        d10=d10,
        b11=b11,
        b12=b12,
        mode_name=mode_name,
    )

    # Continuidad / Ω (marcador firmware: [6]=01 y [12]=02) — antes que OL genérico
    ohm_c = _try_decode_ohm_continuity_14(b6, b11, b12, d7, d8, d9, d10)
    if ohm_c is not None:
        ohm_c.update(base)
        ohm_c["ambiguo"] = False
        ohm_c["nota"] = (
            "Modo en [3]; [11]/[12] son flags. Marcador Ω/continuidad: [6]=01 y [12]=02."
        )
        if ohm_c.get("circuito_abierto"):
            ohm_c["valor"] = None
        return ohm_c

    # Patrón OL en otros subformatos ([6]≠1 o [12]≠02), p. ej. conteo
    if _is_ol_display(d7, d8, d9, d10):
        out = {
            **base,
            "valor": None,
            "unidad_guess": unit_mode,
            "formula": "OL: FF 00 4C FF en [7:10]",
            "sobrecarga_o_abierto": True,
            "circuito_abierto": b3 == 8 or b3 == 10,
            "omit_float_heuristic": True,
            "ambiguo": False,
            "nota": _etiqueta_sobrecarga(b3),
        }
        return out

    # Dígitos no BCD en posiciones decimales (sin ser OL ya filtrado)
    if d9 > 9 or d10 > 9:
        return {
            **base,
            "valor": None,
            "unidad_guess": unit_mode,
            "formula": None,
            "ambiguo": True,
            "nota": (
                "Bytes >9 en [9]/[10]: no encaja dígito decimal 0–9; "
                "puede ser símbolo, rango u otra codificación (comparar con pantalla)."
            ),
        }

    valor: Optional[float] = None
    formula: Optional[str] = None
    nota: Optional[str] = None
    ambiguo = False
    unidad = unit_mode

    # AC(V) (`b3==6`) con [6]=0x01: dígitos tipo 227,7 (no confundir con Ω: ahí [12]=0x02).
    if b3 == 6 and b6 == 0x01 and b12 != 0x02:
        if all(x <= 9 for x in (d7, d8, d9, d10)):
            valor = d7 * 100.0 + d8 * 10.0 + d9 + d10 / 10.0
            formula = (
                f"[6]=01 AC(V): [7]*100+[8]*10+[9]+[10]/10 = {valor:.4f} V "
                "(empírico 2D42, tensión red)"
            )
        else:
            nota = "[6]=01 AC(V): dígitos fuera de 0–9 en [7:10]."

    # [6]=02 / 03: mismo layout de dígitos que en DC(V) validado; unidad según modo [3]
    elif b6 == 0x02:
        v = _decode_volt_fmt02(d7, d8, d9, d10)
        if v is not None:
            valor = v
            if d7 == 0:
                formula = (
                    f"[6]=02: entero=[8], dec={d9}{d10} → {valor:.4f} {unidad}"
                )
            else:
                formula = (
                    f"[6]=02: entero=[7][8], dec={d9}{d10} → {valor:.4f} {unidad}"
                )
        else:
            nota = "[6]=02: [9]/[10] no son centésimas BCD válidas para este subformato."
    elif b6 == 0x03:
        v: Optional[float] = None
        desc = ""
        if b3 == 7:
            v, desc = _decode_capacitance_fmt03(d7, d8, d9, d10)
        elif b3 == 10:
            v, desc = _decode_diode_volt_fmt03(d7, d8, d9, d10)
        if v is None:
            v, desc = _decode_volt_fmt03(d7, d8, d9, d10)
        if v is None:
            v_ac, desc_ac = _decode_ac_volt_fmt03_empirical(b3, d7, d8, d9, d10)
            if v_ac is not None:
                v = v_ac
                desc = desc_ac
        valor = v
        # Sustituir sufijo V en descripciones heredadas de calibración voltaje cuando el modo no es V
        if b3 in (0, 1, 2, 3, 7, 10):
            formula = desc.replace(" V", f" {unidad}").replace("→ 0 V", f"→ 0 {unidad}")
        else:
            formula = desc
        if v is None:
            nota = desc
    else:
        nota = (
            f"[6]=0x{b6:02x}: subformato no decodificado numéricamente aquí "
            "(ver firmware FUN_0803190a; puede ser rama distinta de dígitos)."
        )

    # Modo 9 (COUNT): si llegamos con valor numérico, etiquetar como contaje
    if b3 == 9 and valor is not None:
        unidad = "conteos"
        if formula:
            formula = formula + " (interpretación como contaje)"

    out: Dict[str, Any] = {
        **base,
        "valor": valor,
        "unidad_guess": unidad,
        "formula": formula,
        "ambiguo": ambiguo,
        "nota": nota,
    }
    return out


def decode_dmm_response(data: bytes) -> Dict[str, Any]:
    """
    Devuelve dict con campos interpretados; 'notas' lista advertencias.
    """
    notas: List[str] = []
    out: Dict[str, Any] = {
        "length": len(data),
        "hex": data.hex(),
        "notas": notas,
    }
    n = len(data)
    if n < 4:
        out["notas"].append("Buffer demasiado corto.")
        return out

    if n < 64:
        notas.append(
            f"Solo {n} B en el IN: el host suele pedir 0x40 pero el firmware puede responder con un paquete corto."
        )

    pkt14 = decode_dmm_packet_14(data)
    if pkt14 is not None:
        out["paquete_14"] = pkt14
        if pkt14.get("omit_float_heuristic") or pkt14.get("valor") is not None:
            notas.append(
                "Paquete 14 B: lectura numérica inferida (ver paquete_14); "
                "float/int32 genéricos omitidos para no mezclar con la cabecera."
            )
        elif pkt14.get("nota"):
            notas.append(str(pkt14["nota"]))

    out["header_0_2"] = f"{data[0]:02x} {data[1]:02x} {data[2]:02x}"
    if data[0] == 0x55 and data[1] == 0x0B:
        out["notas"].append("Cabecera 55 0B: patrón habitual de respuesta DMM en 2D42.")
    elif data[0] == 0x55:
        out["notas"].append(f"Primer byte 55, segundo 0x{data[1]:02x} (¿subcanal/longitud?).")

    # Legacy: candidatos históricos para inspección rápida (el modo real del frame 14B va en [3]).
    type_candidates = [2, 3, 4, 6, 8, 12, 16, 20]
    for tc in type_candidates:
        if tc < n:
            out[f"tipo_si_byte_{tc}"] = _guess_mode_from_byte(data[tc])

    if n > 3 and 0 <= data[3] < len(DMM_MODE_NAMES_ORDERED):
        notas.append(
            f"Byte [3]=0x{data[3]:02x} corresponde al modo de función (firmware FUN_08031698)."
        )

    # Float IEEE754 LE: con cabecera 55 0B, el byte [2] suele ser modo; un float
    # empezando en [2] mezcla modo + 3 B del float → valores absurdos (p. ej. ~3850).
    # Elegimos el menor offset válido desde 3 (55 0B) o desde 0 si no aplica.
    skip_float_i32 = bool(
        pkt14
        and pkt14.get("frame_ok")
        and (
            pkt14.get("omit_float_heuristic")
            or pkt14.get("circuito_abierto")
            or pkt14.get("sobrecarga_o_abierto")
            or pkt14.get("valor") is not None
        )
    )

    dmm_55_0b = n >= 2 and data[0] == 0x55 and data[1] == 0x0B
    if not skip_float_i32:
        lo_f = 3 if dmm_55_0b else 0
        candidates_f: List[Tuple[int, float]] = []
        for off in range(lo_f, min(n - 3, 56)):
            v = _try_float_le(data, off)
            if v is not None:
                candidates_f.append((off, v))
        best_f: Optional[Tuple[int, float]] = None
        if candidates_f:
            candidates_f.sort(key=lambda t: t[0])
            best_off, best_v = candidates_f[0]
            if abs(best_v) < 1e-12:
                for off, v in candidates_f:
                    if off <= 32 and abs(v) >= 1e-9:
                        best_off, best_v = off, v
                        break
            best_f = (best_off, best_v)
        if best_f is not None:
            out["valor_float_le"] = {
                "offset": best_f[0],
                "valor": best_f[1],
                "unidad_sugerida": "V, A, Ω… según modo en pantalla",
            }

        best_i: Optional[Tuple[int, int]] = None
        for off in range(0, min(n - 3, 56)):
            iv = _try_i32_le(data, off)
            if iv in (-1, -2147483648) or abs(iv) > 100_000_000:
                continue
            if best_i is None or abs(iv) > abs(best_i[1]):
                best_i = (off, iv)
        if best_i is not None and best_i[1] != 0:
            out["valor_int32_le_micro"] = {
                "offset": best_i[0],
                "raw": best_i[1],
                "como_V": best_i[1] / 1_000_000.0,
            }

        if n >= 7:
            z = _try_float_le(data, 3)
            if z is not None and abs(z) < 1e-30:
                out["cero_aproximado"] = True
                notas.append(
                    "Float ~0 en offset 3: coherente con 0.000 V en pantalla (entrada flotante)."
                )

    # ASCII dígitos (algunos firmwares mandan texto)
    digits = []
    i = 0
    while i < n:
        if 0x30 <= data[i] <= 0x39 or data[i] in (0x2E, 0x2D):  # 0-9 . -
            start = i
            while i < n and (
                0x30 <= data[i] <= 0x39 or data[i] in (0x2E, 0x2D, 0x65, 0x45)
            ):
                i += 1
            try:
                digits.append(data[start:i].decode("ascii"))
            except UnicodeDecodeError:
                pass
        else:
            i += 1
    if digits:
        out["ascii_numeros"] = digits

    notas.append(
        "Modo de función en paquete 14 B: byte [3]. "
        "Los bytes [11]/[12] se interpretan como flags/subrango."
    )
    return out


def format_dmm_decode(data: bytes) -> str:
    d = decode_dmm_response(data)
    lines: List[str] = []
    lines.append(f"DMM: {d['length']} B | encabezado: {d.get('header_0_2', '')}")
    shown_primary = False
    p14 = d.get("paquete_14")
    if isinstance(p14, dict) and p14.get("frame_ok"):
        b5_12 = p14.get("bytes_5_12") or p14.get("bytes_8_12", "")
        sf = p14.get("subformato_6", "")
        lines.append(
            f"  Paquete 14 B [5..12]={b5_12} | [6]={sf} | modo[3]={p14.get('modo_byte_3')} → {p14.get('modo_nombre_3', '')}"
        )
        if p14.get("rango_byte_11") is not None or p14.get("flags_byte_12") is not None:
            lines.append(
                f"  Flags: rango[11]={p14.get('rango_byte_11')}  estado[12]={p14.get('flags_byte_12')}"
            )
        if p14.get("modo_fisico"):
            lines.append(f"  Modo físico (inferido): {p14['modo_fisico']}")
        if p14.get("sobrecarga_o_abierto"):
            lines.append(f"  {p14.get('nota', 'OL / fuera de rango')}")
            shown_primary = True
            if p14.get("formula"):
                lines.append(f"  Detalle: {p14['formula']}")
        elif p14.get("circuito_abierto"):
            lines.append("  Resistencia: OL (circuito abierto / sobre rango)")
            shown_primary = True
            if p14.get("formula"):
                lines.append(f"  Detalle: {p14['formula']}")
        elif p14.get("valor_ohm") is not None:
            lines.append(f"  Resistencia estimada: {p14['valor_ohm']:.4f} Ω")
            shown_primary = True
            if p14.get("formula"):
                lines.append(f"  Detalle: {p14['formula']}")
        elif p14.get("valor") is not None:
            u = p14.get("unidad_guess", "")
            if u == "V":
                lines.append(f"  Voltaje estimado: {p14['valor']:.4f} V")
            elif u in ("A", "mA"):
                lines.append(f"  Corriente estimada: {p14['valor']:.4f} {u}")
            elif u == "mV":
                lines.append(f"  Tensión estimada: {p14['valor']:.4f} mV")
            elif u == "F":
                lines.append(f"  Capacidad estimada: {p14['valor']:.4f} F")
            elif u == "Ω":
                lines.append(f"  Valor estimado: {p14['valor']:.4f} Ω")
            elif u == "conteos":
                lines.append(f"  Conteo estimado: {p14['valor']:.4f}")
            else:
                lines.append(f"  Valor estimado: {p14['valor']:.4f} {u}".strip())
            shown_primary = True
            lines.append(f"  ({p14.get('formula', '')})")
        if p14.get("ambiguo"):
            lines.append("  Atención: lectura marcada como ambigua en metadatos.")
        if p14.get("nota"):
            lines.append(f"  ({p14['nota']})")
    if "valor_float_le" in d:
        vf = d["valor_float_le"]
        lines.append(
            f"  Float LE @[{vf['offset']}]: {vf['valor']:g}  ({vf.get('unidad_sugerida', '')})"
        )
    if "valor_int32_le_micro" in d:
        vi = d["valor_int32_le_micro"]
        lines.append(
            f"  int32 LE @[{vi['offset']}]: raw={vi['raw']}  → {vi['como_V']:.6f} V (si son µV)"
        )
    if not shown_primary and "valor_float_le" in d:
        vf = d["valor_float_le"]
        lines.append(f"  Valor principal: {vf['valor']:.4f}")
    for tc in sorted(k for k in d if k.startswith("tipo_si_byte_")):
        lines.append(f"  Si {tc.split('_')[-1]} es tipo: {d[tc]}")
    if d.get("ascii_numeros"):
        lines.append(f"  ASCII: {d['ascii_numeros']}")
    if d.get("cero_aproximado"):
        lines.append("  Lectura coherente con ~0 V (flotante / sin señal).")
    lines.append("  Notas:")
    for note in d.get("notas", []):
        lines.append(f"    - {note}")
    return "\n".join(lines)
