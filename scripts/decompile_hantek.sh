#!/usr/bin/env bash
# Descompila con Ghidra headless todos los PE (exe/dll/sys) bajo hantek/.
# Cada binario va a su propia carpeta para no mezclar símbolos FUN_* entre archivos.
#
# Uso:
#   scripts/decompile_hantek.sh
#   OUT_ROOT=/tmp/hantek_c scripts/decompile_hantek.sh
#   LIMIT=1 scripts/decompile_hantek.sh          # solo el primer archivo (prueba)
#   ANALYSIS_TIMEOUT=600 scripts/decompile_hantek.sh
#
# Requisitos: scripts/install_decompilador.sh (Ghidra + JDK)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HANTEK="${HANTEK:-$ROOT/hantek}"
OUT_ROOT="${OUT_ROOT:-$ROOT/decompiled_hantek}"
PROJECT_DIR="${PROJECT_DIR:-$ROOT/ghidra_headless_projects}"
ANALYSIS_TIMEOUT="${ANALYSIS_TIMEOUT:-1200}"
LIMIT="${LIMIT:-}"

if [[ -n "${GHIDRA_ROOT:-}" && -f "$GHIDRA_ROOT/support/analyzeHeadless" ]]; then
  GHIDRA_HOME="$GHIDRA_ROOT"
else
  GHIDRA_HOME="$(ls -d "$ROOT"/ghidra_*_PUBLIC 2>/dev/null | head -1 || true)"
fi
ANALYZE="${GHIDRA_HOME:+$GHIDRA_HOME/support/analyzeHeadless}"
SCRIPTS="$ROOT/ghidra_scripts"

die() { echo "error: $*" >&2; exit 1; }

[[ -d "$HANTEK" ]] || die "no existe el directorio hantek: $HANTEK"
[[ -n "$GHIDRA_HOME" && -f "$ANALYZE" ]] || die "no se encontró Ghidra (ghidra_*_PUBLIC o GHIDRA_ROOT)"
[[ -f "$SCRIPTS/ExportAllDecompiled.java" ]] || die "falta ghidra_scripts/ExportAllDecompiled.java"

[[ -x "$ANALYZE" ]] || chmod +x "$ANALYZE" 2>/dev/null || true

mkdir -p "$PROJECT_DIR" "$OUT_ROOT"

mapfile -t FILES < <(find "$HANTEK" -type f \( -iname '*.exe' -o -iname '*.dll' -o -iname '*.sys' \) | LC_ALL=C sort)
n=${#FILES[@]}
[[ $n -gt 0 ]] || die "no hay .exe/.dll/.sys en $HANTEK"

echo "==> Ghidra: $GHIDRA_HOME"
echo "==> Entrada: $HANTEK ($n binarios)"
echo "==> Salida:  $OUT_ROOT"
[[ -n "$LIMIT" ]] && echo "==> Límite:  solo los primeros $LIMIT archivos"

i=0
for f in "${FILES[@]}"; do
  i=$((i + 1))
  if [[ -n "$LIMIT" && "$i" -gt "$LIMIT" ]]; then
    break
  fi
  rel="${f#"$HANTEK"/}"
  out_sub=$(printf '%s' "$rel" | sed 's/[\/\\:*?"<>|]/_/g' | sed 's/ /_/g')
  out_dir="$OUT_ROOT/$out_sub"
  proj=$(printf '%s' "hk_${out_sub}" | tr -c 'a-zA-Z0-9_' '_' | cut -c1-120)
  mkdir -p "$out_dir"
  echo ""
  echo "==> [$i/$n] $(basename "$f") → $out_dir"
  "$ANALYZE" "$PROJECT_DIR" "$proj" \
    -import "$f" \
    -scriptPath "$SCRIPTS" \
    -postScript ExportAllDecompiled.java "$out_dir" \
    -analysisTimeoutPerFile "$ANALYSIS_TIMEOUT" \
    -deleteProject
done

echo ""
echo "==> Hecho. Salida bajo $OUT_ROOT"
