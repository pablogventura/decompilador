"""Constantes USB y de transporte."""

# VID común a la familia 2xx2 (no implica modelo concreto).
VID_HANTEK_2XX2 = 0x0483
# Nombre antiguo: mismo valor que VID_HANTEK_2XX2 (no significa “solo 2D42”).
VID_HANTEK_2D42 = VID_HANTEK_2XX2

PID_HANTEK_2D42 = 0x2D42
PID_HANTEK_2D72 = 0x2D72

# CLI / HantekLink: por defecto 2D42 (`0483:2d42`). Otro modelo p. ej. 2D72: `--pid 0x2d72`.
DEFAULT_PID_HANTEK = PID_HANTEK_2D42

# Tamaño de bloque que usa el DLL en ReadFile/WriteFile (FUN_10001c60 / FUN_10001e00).
CHUNK = 0x40

DEFAULT_TIMEOUT_MS = 3000

# --- Subcódigos 00 0A 03 01 (byte índice 5 del paquete de 10) ---
# Los valores HEURÍSTICOS deben contrastarse con HTHardDll descompilado / captura USB.
SCOPE31_DEVICE_CALI_DEFAULT = 0x09
SCOPE31_DEVICE_NAME_DEFAULT = 0x03
SCOPE31_BUTTON_TEST_DEFAULT = 0x0E

# dsoZeroCali rama “corta” (10 B): byte 5 HEURÍSTICO — sustituir con zero-cali --packet-hex
ZERO_CALI_SHORT_SUBBYTE5_DEFAULT = 0x0B

# Tamaño típico de trozo en dsoUpdateFPGA (EXPORTS)
FPGA_UPDATE_CHUNK_SIZE = 0x30

# dsoWorkType — byte de modo (confirmado para 2D42 / familia 2xx2)
WORK_TYPE_OSCILLOSCOPE: int = 0
WORK_TYPE_MULTIMETER: int = 1
WORK_TYPE_SIGNAL_GENERATOR: int = 2

WORK_TYPE_LABELS: dict[int, str] = {
    WORK_TYPE_OSCILLOSCOPE: "osciloscopio",
    WORK_TYPE_MULTIMETER: "multímetro",
    WORK_TYPE_SIGNAL_GENERATOR: "generador de señales",
}

# ddsSDKWaveType — índice enviado en dds-wave (confirmado por usuario / hardware 2D42)
DDS_WAVE_TYPE_LABELS: dict[int, str] = {
    0: "square",
    1: "triangular",
    2: "sine",
    3: "trapezoid",
    4: "arb1",
    5: "arb2",
    6: "arb3",
    7: "arb4",
}
