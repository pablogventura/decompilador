# Documentación de desarrollo (`dev_docs/`)

Markdown y textos de apoyo para protocolo USB, DLL, firmware y procedimientos de laboratorio. **No** forma parte del paquete instalable `pyhantek` (solo el `README.md` dentro de `pyhantek/` va al wheel por `pyproject.toml`).

| Ruta | Contenido |
|------|-----------|
| `pyhantek/` | Protocolo USB, hallazgos DMM/DDS, checklist de implementación, cobertura manual vs CLI, decodificación DMM |
| `hantek/` | Exports `HTHardDll`, brechas manual ↔ firmware ↔ implementación |
| `tools/` | Procedimientos (p. ej. Force trigger) |
| `firmware/` | Informes Ghidra (`ghidra_*.txt`) |
| `udev/` | Notas udev |
| `Hantek_2D72_2D42_Manual.txt` | Extracto del manual del fabricante |

Código Python y tests: directorio [`../pyhantek/`](../pyhantek/). Artefactos de decompilación C del DLL: [`../hantek/decompilado_HTHardDll/`](../hantek/decompilado_HTHardDll/).
