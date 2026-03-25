#!/usr/bin/env bash
# Extrae el BIN del DfuSe y ejecuta Ghidra headless con ReportPoolTableXrefs.java.
# Salida: dev_docs/firmware/ghidra_pool_table_report.txt (o OUT=…)
#
# Uso:
#   dev_scripts/ghidra_pool_report.sh
#   DFU=firmware/HantekHTX2021090901.dfu OUT=/tmp/report.txt dev_scripts/ghidra_pool_report.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DFU="${DFU:-$ROOT/firmware/HantekHTX2021090901.dfu}"
OUT="${OUT:-$ROOT/dev_docs/firmware/ghidra_pool_table_report.txt}"
PROJECT_DIR="${PROJECT_DIR:-$ROOT/ghidra_headless_projects}"
PROJECT_NAME="${PROJECT_NAME:-hantek_pool_report}"
ANALYSIS_TIMEOUT="${ANALYSIS_TIMEOUT:-900}"

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
[[ -f "$SCRIPTS/ReportPoolTableXrefs.java" ]] || die "falta ReportPoolTableXrefs.java"
[[ -x "$ANALYZE" ]] || chmod +x "$ANALYZE" 2>/dev/null || true

readarray -t EXTRACT_INFO < <(python3 - <<'PY' "$DFU" "$ROOT"
import struct, sys
from pathlib import Path
dfu = Path(sys.argv[1])
root = Path(sys.argv[2])
b = dfu.read_bytes()
if len(b) < 11 or b[:5] != b"DfuSe":
    raise SystemExit("DFU inválido")
o = 11
if len(b) < o + 274:
    raise SystemExit("DFU truncado")
o += 274
addr, esize = struct.unpack_from("<II", b, o)
o += 8
payload = b[o:o+esize]
bin_path = root / "firmware" / (dfu.stem + ".bin")
bin_path.parent.mkdir(parents=True, exist_ok=True)
bin_path.write_bytes(payload)
print(str(bin_path))
print(f"0x{addr:08x}")
PY
)

BIN_PATH="${EXTRACT_INFO[0]}"
BASE_ADDR="${EXTRACT_INFO[1]}"

mkdir -p "$PROJECT_DIR"
echo "==> DFU:    $DFU"
echo "==> BIN:    $BIN_PATH  base $BASE_ADDR"
echo "==> Informe: $OUT"

rm -f "$OUT"
"$ANALYZE" "$PROJECT_DIR" "$PROJECT_NAME" \
  -import "$BIN_PATH" \
  -loader BinaryLoader \
  -loader-baseAddr "$BASE_ADDR" \
  -processor ARM:LE:32:Cortex \
  -scriptPath "$SCRIPTS" \
  -postScript RenameFromVectorTable.java "$BASE_ADDR" \
  -postScript ReportPoolTableXrefs.java "$OUT" \
  -analysisTimeoutPerFile "$ANALYSIS_TIMEOUT" \
  -deleteProject

[[ -f "$OUT" ]] || die "no se generó el informe"
echo "==> Hecho."
wc -l "$OUT"
