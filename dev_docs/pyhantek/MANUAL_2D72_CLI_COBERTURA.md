# Manual Hantek 2D72 (serie 2000) vs CLI `hantek_usb`

Referencia del manual: [`../Hantek_2D72_2D42_Manual.txt`](../Hantek_2D72_2D42_Manual.txt) (v1.3). El fabricante documenta **2D72** (70 MHz, AWG + DMM). La CLI abre por **VID:PID** (`--pid 0x2d72` o `0x2d42` según `lsusb`).

## Metodología de la columna «% CLI»

| % | Significado |
|---|-------------|
| **100** | Hay subcomando (o flujo estable documentado) que cubre la función; en scope/DDS a veces con **índices firmware** en lugar de V/div o s/div en SI (ver `read-settings --parse`, JSON empíricos, [`PROTOCOLO_USB.md`](PROTOCOLO_USB.md)). |
| **75–90** | Operativo en hardware con validación parcial o matices (eco IN, formatos DMM `[6]==0x03`, etc.). |
| **50** | Implementado pero poco fiable, solo lectura, o requiere `raw` / ensayo. |
| **25** | Solo vía bajo nivel (`bulk-send`, `cmd04440`) sin flujo de usuario claro. |
| **0** | No expuesto / depende solo de la UI del equipo o de DLL fuera de alcance (`HTSoftDll`, etc.). |

Fuentes internas: [`../../pyhantek/hantek_usb/cli.py`](../../pyhantek/hantek_usb/cli.py), [`IMPLEMENTACION_CHECKLIST.md`](IMPLEMENTACION_CHECKLIST.md), [`../hantek/MANUAL_FIRMWARE_GAPS.md`](../hantek/MANUAL_FIRMWARE_GAPS.md), [`HALLAZGOS_DMM_DDS_2026-03.md`](HALLAZGOS_DMM_DDS_2026-03.md).

---

## Resumen porcentual (aprox., sobre ~52 filas de la tabla)

| Ámbito | % medio «CLI» | Comentario breve |
|--------|----------------|------------------|
| **Osciloscopio** (modo Scope: ajustes + captura) | **~62%** | Falta REF, guardar traza ×6, cursores, medidas automáticas en pantalla, Force Trigger real; invert por USB (`0x18`) rompe disparo (no usar); Y-T a veces discordante con lectura USB. |
| **Multímetro (DMM)** | **~84%** | `dmm-type`, `dmm-read --parse` cubren modos y decodificación validada en varios rangos; **Hold** es acción física, no USB. |
| **Generador (AWG/DDS)** | **~86%** | Tipos, frecuencia, amplitud, duty, arb, on/off; **offset** con limitaciones de eco/LCD documentadas. |
| **Utilidad / ergonomía manual** | **~14%** | Idioma, sonido, retroiluminación, apagado automático, atajos: no hay comandos dedicados; parte de «info sistema» sí (`arm-version`, etc.). |
| **Global (promedio simple de las filas)** | **~60%** | — |

Desglose cualitativo del catálogo manual:

- **~44%** de ítems con **100%** de cobertura CLI para el uso previsto.
- **~33%** entre **50% y 90%** (usable con matices).
- **~23%** en **0–25%** (solo equipo, PC otra DLL, o no mapeado).

---

## Tabla: función manual → CLI → %

### Modos y diagnóstico

| Función (manual) | CLI / estado | % CLI |
|-------------------|--------------|------|
| Modo osciloscopio | `set-mode osc` / `work-type 0` | 100 |
| Modo multímetro | `set-mode dmm` / `work-type 1` | 100 |
| Modo generador | `set-mode dds` / `work-type 2` | 100 |
| Conexión USB / listado | `list`, `endpoints`, `doctor` | 100 |

### Osciloscopio — ajustes principales

| Función (manual) | CLI / estado | % CLI |
|-------------------|--------------|------|
| Auto (autoset) | `scope-autoset` | 100 |
| SEC/DIV (base de tiempos) | `set-time-div` (índice) + `read-settings --parse` | 100 |
| Posición horizontal | `set-trig-hpos` | 100 |
| Formato Y-T / Roll / Scan | `set-yt-format`; eco en `read-settings` a veces inestable (ver checklist) | 65 |
| Canal encendido/apagado | `ch-onoff` | 100 |
| Acoplamiento DC/AC/GND | `ch-couple` | 100 |
| Atenuación sonda 1×/10×/100×/1000× | `ch-probe` | 100 |
| Límite de banda 20 MHz | `ch-bw` | 100 |
| VOLTS/DIV | `ch-volt` (índice; mapa `ch_volt_map_empirico.json`) | 100 |
| Posición vertical canal | `ch-pos` | 100 |
| Inversión de trazo | Menú equipo; `ch-invert` solo RE (rompe trigger en 2D42) | 45 |
| Fuente de disparo CH1/CH2 | `set-trig-source` | 100 |
| Pendiente flanco (subida/bajada/ambos) | `set-trig-slope` | 100 |
| Modo disparo Auto / Normal / Single | `set-trig-sweep` | 100 |
| Nivel de disparo | `set-trig-vpos` | 100 |
| Force Trigger (manual) | **No** por USB; `trig-force` / `scope-zero-cali` son **calibración** (0x17), no Force Trigger. **Panel 2D42:** Force en **Normal** puede verse como onda “corriendo” (tipo free-run/Auto); **Single** se acerca más a “una captura” como describe el PDF — ver [`../tools/PROCEDIMIENTO_force_trigger.txt`](../tools/PROCEDIMIENTO_force_trigger.txt). | 0 |
| Run/Stop adquisición | `run-stop --run` / `--stop` | 100 |

### Osciloscopio — captura y datos

| Función (manual) | CLI / estado | % CLI |
|-------------------|--------------|------|
| Visualizar forma de onda (adquisición) | `get-real-data`, `get-source-data` (+ `--parse`, CSV, bin) | 100 |
| Medición por retícula | Manual del usuario sobre CSV/muestras | N/A |
| Medición automática frecuencia/amplitud (como en LCD) | DLL `dsoHTGetMeasureResult` / no en esta CLI | 0 |
| Cursores ΔV / ΔT | Solo UI; sin flujo USB documentado aquí | 0 |
| Guardar forma de onda (6 posiciones) | No en CLI | 0 |
| Referencia REF-A / REF-B | No en CLI | 0 |
| Valores por defecto / atajos de tecla | No en CLI | 0 |

### Multímetro (DMM)

| Función (manual) | CLI / estado | % CLI |
|-------------------|--------------|------|
| DC V / DC mV | `dmm-type` + `dmm-read --parse` | 90 |
| AC V | Idem; formatos validados (ej. red) | 90 |
| DC A / AC A | `dmm-type`; menos evidencia en checklist que V | 80 |
| DC mA / AC mA | Idem | 80 |
| Resistencia (Ω) | Idem | 90 |
| Capacidad | Idem | 90 |
| Diodo | Idem | 90 |
| Continuidad (buzzer, &lt;50 Ω) | Modo `COUNT` / continuidad en decode | 90 |
| Lista de modos índice | `dmm-modes` (sin USB) | 100 |
| Hold de lectura | Botón físico; no comando USB dedicado | 0 |

### Generador (AWG) — solo 2D72/2D42 en manual

| Función (manual) | CLI / estado | % CLI |
|-------------------|--------------|------|
| Tipo: cuadrada, triangular, seno, trapecio | `dds-wave`; `dds-waves` lista | 100 |
| Arb 1–4 | `dds-wave 4..7` + `dds-download` | 90 |
| Frecuencia | `dds-fre` (write-only por defecto en 2D42; ajustar si hace falta) | 95 |
| Amplitud | `dds-amp` | 95 |
| Offset | `dds-offset`; eco/LCD pueden no reflejar (ver hallazgos) | 50 |
| Duty ciclo (cuadrada) | `dds-square-duty` | 95 |
| Duty rampa / trapecio | `dds-ramp-duty`, `dds-trap-duty`, `dds-trapezoid-duty` | 80 |
| Salida on/off | `dds-onoff --on` / `--off` | 100 |
| Opciones mágicas DLL | `dds-options f12f|f13f` | 60 |
| Edición arb en PC + descarga | `dds-download` + software fabricante (manual) | 90 |

### Utilidad, carga y mantenimiento (manual)

| Función (manual) | CLI / estado | % CLI |
|-------------------|--------------|------|
| Idioma menú | No CLI | 0 |
| Sonido de teclas | No CLI | 0 |
| Brillo pantalla | No CLI | 0 |
| Tiempo retroiluminación / apagado auto | No CLI (USB conectado afecta comportamiento, manual) | 0 |
| Información de sistema (versiones) | `arm-version`, `stm-id`, `fpga-version`, `query-31`, `read-settings` | 85 |
| Autocalibración / cero | `scope-zero-cali`, `zero-cali`, `utility` menú equivalente parcial | 55 |
| Actualización FPGA | `fpga-update` (riesgo; avanzado) | 40 |
| Carga de batería / estado batería | Indicador en LCD; no CLI | 0 |
| Calibración de fábrica | `factory-pulse` (experimental) | 25 |

### Comandos extra CLI (no son «función del manual» pero cubren protocolo)

| Función | CLI | % CLI |
|---------|-----|------|
| Trama scope genérica | `cmd04440`, `raw` | 75 |
| Cualquier bulk | `bulk-send` | 50 |
| Decodificar hex pegado | `decode-hex` / `decode-hex --dmm` | 100 |
| Diff dos **read-settings** (21 B con nombres) | [`../../pyhantek/tools/compare_read_settings.py`](../../pyhantek/tools/compare_read_settings.py) | 100 |
| Snapshot **read-settings** en JSON | [`../../pyhantek/tools/snapshot_scope_state.py`](../../pyhantek/tools/snapshot_scope_state.py) | 100 |
| Diff dos snapshots JSON | [`../../pyhantek/tools/compare_scope_snapshots.py`](../../pyhantek/tools/compare_scope_snapshots.py) | 100 |
| Escribir calibración / banner / SN | `write-cali`, `write-banner`, `device-sn` | 25–50 |

---

## Cómo reproducir el «promedio global ~60%»

1. Asignar a cada fila de la tabla principal (excl. «N/A» y la tabla extra) un número en {0, 25, 45, 50, …, 100} como en la columna **% CLI**.
2. Promediar aritméticamente → cae cercano a **60%** con el conjunto de filas anterior (~52 filas con valor numérico).

Si solo contás **100%** como «plenamente usable»: **~23–24 filas / ~52 ≈ 44–46%**.

---

## Limitaciones explícitas

- **HTSoftDll / MeasDll** (mediciones avanzadas, cursores como en PC del fabricante): **fuera** del alcance habitual de `hantek_usb`; ver [`../hantek/MANUAL_FIRMWARE_GAPS.md`](../hantek/MANUAL_FIRMWARE_GAPS.md) §5–7.
- Los porcentajes son **estimación de proyecto**; cambian al añadir subcomandos o al validar más modos DMM/A en hardware.
