#!/usr/bin/env bash
# Ejemplo: descompilar ls.bin con Ghidra headless y ExportAllDecompiled.java
#
# Uso:
#   scripts/decompile_ls_headless.sh
#   OUT_DIR=/ruta/salida scripts/decompile_ls_headless.sh
#   BIN=/otro/ejecutable scripts/decompile_ls_headless.sh
#
# Requisitos: scripts/install_decompilador.sh (JDK + descarga de Ghidra en ghidra_*_PUBLIC/)
# Opcional: GHIDRA_ROOT=/ruta/ghidra_12.0.4_PUBLIC (debe contener support/analyzeHeadless)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${GHIDRA_ROOT:-}" && -f "$GHIDRA_ROOT/support/analyzeHeadless" ]]; then
  GHIDRA_HOME="$GHIDRA_ROOT"
else
  GHIDRA_HOME="$(ls -d "$ROOT"/ghidra_*_PUBLIC 2>/dev/null | head -1 || true)"
fi
ANALYZE="${GHIDRA_HOME:+$GHIDRA_HOME/support/analyzeHeadless}"
SCRIPTS="$ROOT/ghidra_scripts"
PROJECT_DIR="${PROJECT_DIR:-$ROOT/ghidra_headless_projects}"
PROJECT_NAME="${PROJECT_NAME:-ls_headless}"
BIN="${BIN:-$ROOT/ls.bin}"
OUT_DIR="${OUT_DIR:-$ROOT/decompiled_c}"
ANALYSIS_TIMEOUT="${ANALYSIS_TIMEOUT:-1200}"

die() { echo "error: $*" >&2; exit 1; }

[[ -x "$ANALYZE" ]] || chmod +x "$ANALYZE" 2>/dev/null || true
[[ -n "$GHIDRA_HOME" && -f "$ANALYZE" ]] || die "no se encontró Ghidra (carpeta ghidra_*_PUBLIC bajo $ROOT o variable GHIDRA_ROOT)"
[[ -f "$ROOT/ghidra_scripts/ExportAllDecompiled.java" ]] || die "falta ExportAllDecompiled.java en ghidra_scripts/"
[[ -f "$BIN" ]] || die "no existe el binario: $BIN (copia uno a ls.bin o define BIN=...)"

mkdir -p "$PROJECT_DIR" "$OUT_DIR"

echo "==> Binario:  $BIN"
echo "==> Salida C: $OUT_DIR"
echo "==> Proyecto Ghidra (efímero): $PROJECT_DIR / $PROJECT_NAME"

# -deleteProject: borra el proyecto local al terminar (solo queda la carpeta C).
exec "$ANALYZE" "$PROJECT_DIR" "$PROJECT_NAME" \
  -import "$BIN" \
  -scriptPath "$SCRIPTS" \
  -postScript ExportAllDecompiled.java "$OUT_DIR" \
  -analysisTimeoutPerFile "$ANALYSIS_TIMEOUT" \
  -deleteProject
