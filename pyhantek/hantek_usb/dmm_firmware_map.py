"""
Tablas extraídas del firmware HantekHTX2021090901 (decompilado).

Referencias:
- FUN_08031698: estado interno DAT_080320e0 → byte USB [3] del frame DMM 14 B.
- FUN_0803170c: selector físico (byte en DAT_080320e4+4) → DAT_080320e0 (+ índice UI auxiliar).
- FUN_0803190a: construcción del buffer 14 B (bytes [4]–[12]).
- FUN_08027680: “raw” de segmentos LCD → dígitos 0–9 / 0x4C (L) / 0xFF (apagado) y signo.

El valor “físico” no viaja como float IEEE en [7:10]: son **dígitos de display** + flags;
la unidad y escala vienen del modo ([3]) y del subformato ([6]).
"""

from __future__ import annotations

from typing import Final

# FUN_08031698: *DAT_080320e0 (char) → byte USB [3]
_INTERNAL_E0_TO_USB_BYTE3: dict[int, int] = {
    1: 1,
    2: 0,
    3: 3,
    4: 2,
    5: 7,
    6: 8,
    7: 9,
    8: 10,
    9: 4,
    10: 5,
    11: 6,
}

# Inversa: USB [3] → estado interno e0 (útil para trazar con FUN_0803170c)
_USB_BYTE3_TO_INTERNAL_E0: dict[int, int] = {v: k for k, v in _INTERNAL_E0_TO_USB_BYTE3.items()}


def internal_e0_to_usb_mode_byte(e0: int) -> int:
    """Replica FUN_08031698 para e0 ∈ {1..11}; otros valores se devuelven tal cual (rama else)."""
    e = int(e0) & 0xFF
    return _INTERNAL_E0_TO_USB_BYTE3.get(e, e)


def usb_mode_byte_to_internal_e0(b3: int) -> int | None:
    """Inversa parcial; None si no hay entrada 1:1 (no debería ocurrir para modos normales)."""
    return _USB_BYTE3_TO_INTERNAL_E0.get(int(b3) & 0xFF)


# FUN_0803170c: selector en *(DAT_080320e4 + 4) → *DAT_080320e0
# Solo valores que aparecen explícitos en el .c (orden de ramas if/else).
SELECTOR_TO_INTERNAL_E0: dict[int, int] = {
    0: 2,
    1: 1,
    2: 4,
    3: 3,
    4: 9,
    5: 10,
    6: 11,
    7: 5,
    8: 6,
    9: 7,
    10: 8,
}

# Derivado: selector → USB [3] (composición FUN_0803170c ∘ FUN_08031698)
SELECTOR_TO_USB_BYTE3: Final[dict[int, int]] = {
    sel: internal_e0_to_usb_mode_byte(e0) for sel, e0 in SELECTOR_TO_INTERNAL_E0.items()
}

# Subformato [6] en FUN_0803190a (resumen):
# - Si bit MSB de pbVar2[0xc]: rama “especial” (Ω/continuidad según bits en 0xc y DAT_0803212c);
#   [6] ∈ {1,2,3} según bit4 de 0xc y resultado de FUN_0800cd7c.
# - Si no: [6] por prioridad fija sobre bits MSB de pbVar2[3], [5], [7] (último que aplique gana):
#   bit de [7] → 1, bit de [5] → 2, bit de [3] → 3.
#
# Byte [11] (índice 0xb): prioridad fija sobre bits de pbVar2[9] y [10] → 0..5 (default 5).
# Byte [12] (índice 0xc): prioridad sobre bits de pbVar2[11] y [12] → 0..4 (default 4).
