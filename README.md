# Decompilador / cliente USB — Hantek 2xx2

Repositorio de **ingeniería inversa** y **herramientas libusb** para osciloscopios Hantek serie **2D42 / 2D72** (y familia con el mismo protocolo): descompilados del DLL del fabricante, documentación de protocolo y la CLI Python **`pyhantek`** (`hantek_usb`).

## Enlaces

- **Índice de documentación:** [`dev_docs/INDICE.md`](dev_docs/INDICE.md)
- **CLI e instalación:** [`pyhantek/README.md`](pyhantek/README.md)
- **Protocolo USB y limitaciones:** [`dev_docs/pyhantek/PROTOCOLO_USB.md`](dev_docs/pyhantek/PROTOCOLO_USB.md)

## Requisitos mínimos (CLI)

- **Python 3** + **libusb-1.0** y **PyUSB**
- En Linux: permisos USB (p. ej. reglas **udev** — ver [`dev_docs/udev/README.txt`](dev_docs/udev/README.txt))

## Instalación rápida

```bash
cd pyhantek
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m hantek_usb doctor
```

## Estructura

- `pyhantek/` — paquete instalable y scripts en `tools/`
- `dev_docs/` — protocolo, checklist, manual, procedimientos
- `hantek/` — decompilado Ghidra de `HTHardDll` y notas

---

*English (short):* This repo contains Hantek 2xx2 **USB protocol notes**, **decompiled DLL** references, and a **Python/libusb CLI** (`pyhantek`). Start from [`dev_docs/INDICE.md`](dev_docs/INDICE.md) and [`pyhantek/README.md`](pyhantek/README.md).
