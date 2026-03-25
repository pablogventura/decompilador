# Hantek — decompilación y notas de firmware

Esta carpeta agrupa **artefactos de ingeniería inversa** (DLL descompilada, pseudocódigo Ghidra en el repo), **no** el código Python del cliente USB.

## Cliente USB (Python)

La CLI y la librería **`hantek_usb`** están en **`../pyhantek/`**. Instalación con pipx:

```bash
pipx install ./pyhantek
```

## Documentación de desarrollo

Toda la documentación en Markdown y textos de apoyo vive en **`../dev_docs/`**:

- **`../dev_docs/hantek/`** — `EXPORTS_HTHardDll.md`, `MANUAL_FIRMWARE_GAPS.md`
- **`../dev_docs/pyhantek/`** — `PROTOCOLO_USB.md`, hallazgos DMM/DDS, checklist de implementación, cobertura manual vs CLI, etc.
- **`../dev_docs/tools/`** — procedimientos (p. ej. Force trigger)
- **`../dev_docs/firmware/`** — informes Ghidra (`.txt`)
- **`../dev_docs/udev/`** — notas udev
- **`../dev_docs/Hantek_2D72_2D42_Manual.txt`** — extracto del manual

## Contenido en esta carpeta

- `decompilado_HTHardDll/` — fuentes exportadas desde Ghidra (referencia cruzada con el DLL del kit).
- `udev/README.txt` — puntero a las notas en `dev_docs/udev/`.
