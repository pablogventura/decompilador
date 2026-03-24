#!/usr/bin/env python3
"""
CLI USB para Hantek 2xx2 (p. ej. 2D42; 2D72 con --pid 0x2d72) según hantek/PROTOCOLO_USB.md y HTHardDll descompilado.

Ejecutar desde este directorio:
  python hantek_cli.py COMANDO ...
  python -m hantek_usb COMANDO ...
  python -m hantek_usb.cli COMANDO ...

Requisitos:
  - pip install -r requirements.txt
  - libusb-1.0 en el sistema (p. ej. paquete libusb-1.0-0 en Debian/Ubuntu)
  - En Linux: permisos udev para 0483:2d42 (u otro PID), o ejecutar con privilegios (no recomendado).

Limitación: no reproduce todo Scope.exe; solo órdenes inferidas con claridad del DLL.
"""

from __future__ import annotations

import sys

try:
    from hantek_usb.cli import main
except ImportError as e:
    print(
        "No se pudo cargar hantek_usb (¿pip install -r requirements.txt?).",
        file=sys.stderr,
    )
    print(e, file=sys.stderr)
    raise SystemExit(1) from e

if __name__ == "__main__":
    raise SystemExit(main())
