# Índice de documentación — proyecto decompilador Hantek

Punto de entrada para **protocolo USB**, **DLL**, **CLI Python** y **procedimientos de banco**. Todo en **español** salvo citas de símbolos/API en inglés.

## Inicio rápido

| Objetivo | Dónde empezar |
|----------|----------------|
| **Pendientes, pruebas en banco y plan hacia paridad con el manual** | [`PENDIENTES_Y_PLAN_MANUAL_COMPLETO.md`](PENDIENTES_Y_PLAN_MANUAL_COMPLETO.md) |
| Instalar y usar la CLI | [`../pyhantek/README.md`](../pyhantek/README.md) |
| Entender tramas USB y opcodes | [`pyhantek/PROTOCOLO_USB.md`](pyhantek/PROTOCOLO_USB.md) §3–6 |
| Ver qué falta vs manual 2D72/2D42 | [`hantek/MANUAL_FIRMWARE_GAPS.md`](hantek/MANUAL_FIRMWARE_GAPS.md) |
| Trazabilidad implementación / resultados en vivo | [`pyhantek/IMPLEMENTACION_CHECKLIST.md`](pyhantek/IMPLEMENTACION_CHECKLIST.md) |
| Exports `HTHardDll` ↔ bytes USB | [`hantek/EXPORTS_HTHardDll.md`](hantek/EXPORTS_HTHardDll.md) |

## Flujos de trabajo

1. **Primer uso USB (Linux)**  
   `udev`: [`udev/README.txt`](udev/README.txt) y [`../hantek/udev/README.txt`](../hantek/udev/README.txt). Luego: `cd pyhantek && python -m hantek_usb doctor`.

2. **Validación CH1 con generador externo**  
   [`../pyhantek/tools/external_ch1_smoke.py`](../pyhantek/tools/external_ch1_smoke.py) o comando **`external-ch1-smoke`** (tras instalar el paquete) — disparo Auto, captura `0x16`, métricas y frecuencia heurística (`hantek_usb.scope_signal_metrics`). Con `--scope-autoset`, JSON con **`settings_autoset_diff`**. Códigos de salida: [`pyhantek/PROTOCOLO_USB.md`](pyhantek/PROTOCOLO_USB.md) §6.2.

3. **Lazo interno AWG → osciloscopio**  
   [`../pyhantek/tools/dds_osc_coherence.py`](../pyhantek/tools/dds_osc_coherence.py), [`../pyhantek/tools/verify_arb_sine_scope.py`](../pyhantek/tools/verify_arb_sine_scope.py) (según necesidad).

4. **Autoset / V-div por software (sin botón Auto)**  
   [`../pyhantek/tools/scope_autoset_soft.py`](../pyhantek/tools/scope_autoset_soft.py) (`--no-dds` si la señal es externa).

5. **Force trigger sin capturar el bus en el PC**  
   [`tools/PROCEDIMIENTO_force_trigger.txt`](tools/PROCEDIMIENTO_force_trigger.txt) + [`../pyhantek/tools/snapshot_scope_state.py`](../pyhantek/tools/snapshot_scope_state.py) + [`../pyhantek/tools/compare_scope_snapshots.py`](../pyhantek/tools/compare_scope_snapshots.py).

## Por carpeta (`dev_docs/`)

| Ruta | Contenido |
|------|-----------|
| [`pyhantek/`](pyhantek/) | Protocolo, checklist, cobertura manual vs CLI, hallazgos DMM/DDS, decodificación DMM |
| [`hantek/`](hantek/) | Exports DLL, brechas manual ↔ firmware |
| [`tools/`](tools/) | Procedimientos de laboratorio (texto) |
| [`firmware/`](firmware/) | Informes Ghidra |
| [`udev/`](udev/) | Reglas udev |
| [`Hantek_2D72_2D42_Manual.txt`](Hantek_2D72_2D42_Manual.txt) | Extracto del manual |

## Código y descompilados (fuera de `dev_docs/`)

| Ruta | Contenido |
|------|-----------|
| [`../pyhantek/hantek_usb/`](../pyhantek/hantek_usb/) | Paquete Python: `protocol`, `parse_resp`, `scope_signal_metrics`, … |
| [`../pyhantek/tools/`](../pyhantek/tools/) | Scripts de prueba y utilidades |
| [`../hantek/decompilado_HTHardDll/`](../hantek/decompilado_HTHardDll/) | Pseudocódigo Ghidra del DLL |
| [`../.cursor/rules/`](../.cursor/rules/) | Reglas del proyecto (sin sniff USB en PC; lazos instrumento) |

## Política del repo

No basar el trabajo en **usbmon / Wireshark / sniff** del tráfico USB en el PC; usar RE (firmware/DLL), CLI `pyhantek` y **diff de `read-settings`** / snapshots. Detalle: [`.cursor/rules/hantek-sin-sniff-host.mdc`](../.cursor/rules/hantek-sin-sniff-host.mdc).
