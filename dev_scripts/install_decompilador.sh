#!/usr/bin/env bash
# Instala lo necesario para el descompilador: JDK y Ghidra (descarga oficial).
# Ghidra NO va en el repositorio: queda en ghidra_*_PUBLIC/ (ignorado por git).
#
# Variables opcionales:
#   GHIDRA_ROOT  — si ya tienes Ghidra en otra ruta, no se descarga nada aquí.
#   GHIDRA_SKIP_DOWNLOAD=1 — solo JDK + permisos (falla si no existe Ghidra).

set -euo pipefail

# Release fijada (coincide con lo probado en dev_scripts/decompile_ls_headless.sh)
readonly GHIDRA_TAG="Ghidra_12.0.4_build"
readonly GHIDRA_ZIP="ghidra_12.0.4_PUBLIC_20260303.zip"
readonly GHIDRA_URL="https://github.com/NationalSecurityAgency/ghidra/releases/download/${GHIDRA_TAG}/${GHIDRA_ZIP}"
readonly GHIDRA_SHA256="c3b458661d69e26e203d739c0c82d143cc8a4a29d9e571f099c2cf4bda62a120"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$ROOT/tmp"

die() { echo "error: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "hace falta el comando: $1 (instálalo e inténtalo de nuevo)"; }

resolve_ghidra_home() {
  if [[ -n "${GHIDRA_ROOT:-}" && -f "$GHIDRA_ROOT/support/analyzeHeadless" ]]; then
    echo "$GHIDRA_ROOT"
    return
  fi
  ls -d "$ROOT"/ghidra_*_PUBLIC 2>/dev/null | head -1 || true
}

echo "==> Raíz del proyecto: $ROOT"

install_java() {
  if command -v java >/dev/null 2>&1; then
    echo "==> Java ya instalado:"
    java -version 2>&1 | head -1 || true
    return
  fi
  echo "==> Instalando JDK (Ghidra 12 recomienda Java 17–21; usamos 21 si existe en el gestor)…"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    if apt-cache show openjdk-21-jdk-headless &>/dev/null; then
      sudo apt-get install -y openjdk-21-jdk-headless curl unzip
    else
      sudo apt-get install -y openjdk-17-jdk-headless curl unzip
    fi
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y java-21-openjdk-headless curl unzip \
      || sudo dnf install -y java-17-openjdk-headless curl unzip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed jdk21-openjdk curl unzip 2>/dev/null \
      || sudo pacman -S --needed jdk17-openjdk curl unzip
  else
    die "instala JDK 17+ o 21, curl y unzip, y vuelve a ejecutar este script"
  fi
}

install_java
need_cmd java

GHIDRA_HOME="$(resolve_ghidra_home)"
GHIDRA_SUPPORT="${GHIDRA_HOME:+$GHIDRA_HOME/support}"

if [[ -f "${GHIDRA_SUPPORT:-}/analyzeHeadless" ]]; then
  echo "==> Ghidra ya presente: $GHIDRA_HOME"
else
  if [[ "${GHIDRA_SKIP_DOWNLOAD:-}" == "1" ]]; then
    die "GHIDRA_SKIP_DOWNLOAD=1 pero no hay Ghidra en $ROOT (ghidra_*_PUBLIC) ni GHIDRA_ROOT"
  fi
  ensure_curl_unzip() {
    command -v curl >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 && return
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update -qq && sudo apt-get install -y curl unzip
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y curl unzip
    elif command -v pacman >/dev/null 2>&1; then
      sudo pacman -S --needed curl unzip
    else
      die "instala curl y unzip para poder descargar Ghidra"
    fi
  }
  ensure_curl_unzip
  need_cmd curl
  need_cmd unzip
  need_cmd sha256sum
  echo "==> Descargando Ghidra (${GHIDRA_ZIP})…"
  mkdir -p "$TMP_DIR"
  ZIP_PATH="$TMP_DIR/$GHIDRA_ZIP"
  curl -fsSL -o "$ZIP_PATH.part" "$GHIDRA_URL"
  mv -f "$ZIP_PATH.part" "$ZIP_PATH"
  echo "$GHIDRA_SHA256  $ZIP_PATH" | sha256sum -c
  echo "==> Descomprimiendo en $ROOT …"
  unzip -q -o "$ZIP_PATH" -d "$ROOT"
  rm -f "$ZIP_PATH"
  GHIDRA_HOME="$(resolve_ghidra_home)"
  GHIDRA_SUPPORT="${GHIDRA_HOME:+$GHIDRA_HOME/support}"
  [[ -f "${GHIDRA_SUPPORT:-}/analyzeHeadless" ]] || die "descompresión incompleta: no aparece analyzeHeadless"
fi

chmod +x "$GHIDRA_SUPPORT/analyzeHeadless" "$GHIDRA_SUPPORT/launch.sh" 2>/dev/null || true

echo "==> Ghidra: $GHIDRA_HOME"
java -version 2>&1 | head -1
echo "==> Listo. Prueba: dev_scripts/decompile_ls_headless.sh"
