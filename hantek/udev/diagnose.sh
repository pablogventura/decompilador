#!/usr/bin/env bash
# Ejecutar con el Hantek conectado: bash diagnose.sh
set -e
echo "=== lsusb (Hantek / STM 0483) ==="
lsusb | grep -i 0483 || echo "(no aparece 0483 — cable o alimentación)"

echo
echo "=== Nodos /dev/bus/usb (permisos) ==="
ls -l /dev/bus/usb/*/* 2>/dev/null | head -40 || true

echo
echo "=== Buscar 0483:2d42 en sysfs ==="
for d in /sys/bus/usb/devices/*; do
  [[ -r "$d/idVendor" ]] || continue
  v=$(cat "$d/idVendor" 2>/dev/null || true)
  p=$(cat "$d/idProduct" 2>/dev/null || true)
  if [[ "$v" == "0483" && "$p" == "2d42" ]]; then
    echo "Encontrado: $d  VID=$v PID=$p"
    if [[ -e "$d/dev" ]]; then
      MA=$(cut -d: -f1 <"$d/dev")
      MI=$(cut -d: -f2 <"$d/dev")
      DEVNODE="/dev/bus/usb/$(printf '%03d' "$MA")/$(printf '%03d' "$MI")"
      echo "  Nodo esperado: $DEVNODE"
      ls -l "$DEVNODE" 2>/dev/null || echo "  (nodo no existe aún)"
      echo "  udevadm test (simulación):"
      udevadm test-builtin uaccess "$d" 2>/dev/null || true
    fi
  fi
done

echo
echo "Si el nodo es root:root y crw-rw-r-- o crw-------, la regla udev no se aplicó."
echo "Copia de nuevo 99-hantek-2d42.rules, reload, y DESENCHUFA/ENCHUFA el cable."
