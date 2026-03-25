#!/usr/bin/env bash
# Decompila firmware DFU (DfuSe) con Ghidra headless.
# Salida:
#   - firmware/decompilado/*.c
#   - firmware/decompilado/index.txt
#
# Uso:
#   dev_scripts/decompile_firmware.sh
#   DFU=firmware/archivo.dfu dev_scripts/decompile_firmware.sh
#   OUT_DIR=firmware/decompilado dev_scripts/decompile_firmware.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DFU="${DFU:-$ROOT/firmware/HantekHTX2021090901.dfu}"
OUT_DIR="${OUT_DIR:-$ROOT/firmware/decompilado}"
PROJECT_DIR="${PROJECT_DIR:-$ROOT/ghidra_headless_projects}"
PROJECT_NAME="${PROJECT_NAME:-firmware_dfu_auto}"
ANALYSIS_TIMEOUT="${ANALYSIS_TIMEOUT:-1200}"

if [[ -n "${GHIDRA_ROOT:-}" && -f "$GHIDRA_ROOT/support/analyzeHeadless" ]]; then
  GHIDRA_HOME="$GHIDRA_ROOT"
else
  GHIDRA_HOME="$(ls -d "$ROOT"/ghidra_*_PUBLIC 2>/dev/null | head -1 || true)"
fi
ANALYZE="${GHIDRA_HOME:+$GHIDRA_HOME/support/analyzeHeadless}"
SCRIPTS="$ROOT/ghidra_scripts"

die() { echo "error: $*" >&2; exit 1; }

[[ -f "$DFU" ]] || die "no existe DFU: $DFU"
[[ -n "$GHIDRA_HOME" && -f "$ANALYZE" ]] || die "no se encontró Ghidra"
[[ -f "$SCRIPTS/ExportAllDecompiled.java" ]] || die "falta ExportAllDecompiled.java"
[[ -f "$SCRIPTS/RenameFromVectorTable.java" ]] || die "falta RenameFromVectorTable.java"
[[ -x "$ANALYZE" ]] || chmod +x "$ANALYZE" 2>/dev/null || true

mkdir -p "$OUT_DIR" "$PROJECT_DIR"

echo "==> DFU:    $DFU"
echo "==> Salida: $OUT_DIR"

# Extrae el primer elemento DfuSe (addr + payload) a BIN.
readarray -t EXTRACT_INFO < <(python3 - <<'PY' "$DFU" "$OUT_DIR"
import struct, sys
from pathlib import Path
dfu=Path(sys.argv[1]); out_dir=Path(sys.argv[2])
b=dfu.read_bytes()
if len(b) < 11 or b[:5] != b'DfuSe':
    raise SystemExit("DFU inválido o no DfuSe")
o=11
_,_,_,targets=struct.unpack_from('<5sBIB', b, 0)
if targets < 1:
    raise SystemExit("DFU sin targets")
if len(b) < o+274:
    raise SystemExit("DFU truncado (target)")
o += 274
if len(b) < o+8:
    raise SystemExit("DFU truncado (element)")
addr,esize=struct.unpack_from('<II', b, o); o+=8
if len(b) < o+esize:
    raise SystemExit("DFU truncado (payload)")
payload=b[o:o+esize]
bin_path=out_dir / (dfu.stem + ".bin")
bin_path.write_bytes(payload)
print(str(bin_path))
print(hex(addr))
print(str(len(payload)))
PY
)

BIN_PATH="${EXTRACT_INFO[0]}"
BASE_ADDR="${EXTRACT_INFO[1]}"
BIN_SIZE="${EXTRACT_INFO[2]}"

echo "==> BIN:    $BIN_PATH ($BIN_SIZE bytes)"
echo "==> Base:   $BASE_ADDR"

# Limpia C previo para evitar mezclar corridas.
rm -f "$OUT_DIR"/*.c "$OUT_DIR/index.txt"

"$ANALYZE" "$PROJECT_DIR" "$PROJECT_NAME" \
  -import "$BIN_PATH" \
  -loader BinaryLoader \
  -loader-baseAddr "$BASE_ADDR" \
  -processor ARM:LE:32:Cortex \
  -scriptPath "$SCRIPTS" \
  -postScript RenameFromVectorTable.java "$BASE_ADDR" \
  -postScript ExportAllDecompiled.java "$OUT_DIR" \
  -analysisTimeoutPerFile "$ANALYSIS_TIMEOUT" \
  -deleteProject

python3 - <<'PY' "$OUT_DIR"
from pathlib import Path
out=Path(__import__('sys').argv[1])
files=sorted(p.name for p in out.glob("*.c"))
idx=out/"index.txt"
idx.write_text("\n".join(files) + ("\n" if files else ""), encoding="utf-8")
print(f"==> index:  {idx} ({len(files)} entradas)")
PY

echo "==> Hecho."
