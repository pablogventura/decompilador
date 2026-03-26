# Brechas: manual 2D72/2D42 + firmware vs CLI (`pyhantek/`)

Fuente del manual: `Hantek_2D72_2D42_Manual.txt` (extracto de PDF).  
Firmware de referencia: `firmware/decompilado/` (p. ej. `FUN_08031a9e`, `FUN_08032140`).  
DLL: `EXPORTS_HTHardDll.md`, binario `hantek/HTHardDll.dll` y pseudocódigo en `decompiled_hantek/HTHardDll.dll/`.

Este archivo lista qué **falta implementar, probar en hardware o confirmar** respecto de lo que describe el manual y lo que ya existe en el CLI `hantek_usb`. Los huecos de **multímetro y generador** están resumidos en **§8** (checklist); el detalle validado sigue en [`../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md`](../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md).

---

## 1. Bien cubierto (CLI + pruebas + documentación)

- Modos **Scope / DMM / AWG**: `set-mode`, comandos DMM, DDS.
- **TIME_DIV**, **RUN/STOP** (trama STM32 + legado `0x0C` donde aplica).
- **Disparo**: fuente, flanco (índices 0/1/2), barrido Auto / Normal / Single, posición horizontal (`T->…`), nivel vertical (`set-trig-vpos`).
- **Canales**: on/off, acople AC/DC (índices probados), sonda 1×/10×, BW limit, V/div (tabla empírica en [`../pyhantek/ch_volt_map_empirico.json`](../pyhantek/ch_volt_map_empirico.json), matiz CH2), posición vertical.
- Captura **`0x16`**, **`read-settings`** (`0x15`) con `--parse`: `TIME_DIV` en `ram98_byte3`; flanco y barrido en `ram9c_byte3` / `ram9c_byte6` (ver [`../pyhantek/hantek_usb/parse_resp.py`](../pyhantek/hantek_usb/parse_resp.py) y [`../pyhantek/docs/PROTOCOLO_USB.md`](../pyhantek/docs/PROTOCOLO_USB.md)).
- Opcode **`0x17`**: empíricamente **calibración** (mensaje “Calibrating”), alineado con `dsoHTScopeZeroCali`; **no** es el “Force trigger” del texto del manual.

---

## 2. Implementado en CLI; falta confirmar en hardware o cerrar matriz

| Tema | Qué falta |
|------|-----------|
| **`scope-autoset`** (`0x13`) | Validar con señal conocida (p. ej. DDS) si el resultado equivale al botón **Auto** del manual. |
| **CH1 con generador externo** | Script **[`../pyhantek/tools/external_ch1_smoke.py`](../pyhantek/tools/external_ch1_smoke.py)** + módulo [`../pyhantek/hantek_usb/scope_signal_metrics.py`](../pyhantek/hantek_usb/scope_signal_metrics.py): métricas y frecuencia **estimada** (heurística; ver [`../dev_docs/pyhantek/PROTOCOLO_USB.md`](../dev_docs/pyhantek/PROTOCOLO_USB.md) §6.2). |
| **`set-yt-format`** (`0x0D`) | **Lectura:** `ram98_byte0` @ SRAM **`0x2000cc4c`** (literal pool `0x08032624`; **`0x2000ca4c+0x200`**). Valores empíricos: **`0x00`** Y-T, **`0x01`** Roll, **`0x02`** X-Y; **Scan** pendiente. **Firmware** `FUN_08031a9e`: opcode `0x0D` no escribe ese byte. **DLL**: solo `dsoHTSetYTFormat`; API `param_2`≥2 → mismo ushort **2** en el bus. **Escritura** USB no movió modo en prueba; `write-settings` no alcanza byte 13 del bloque 0x15. Ver [`../pyhantek/docs/PROTOCOLO_USB.md`](../pyhantek/docs/PROTOCOLO_USB.md). |
| **Acople GND** | **Hecho (2D42):** `ch-couple N 2` → GND; `0`→AC, `1`→DC (ver [`../pyhantek/docs/PROTOCOLO_USB.md`](../pyhantek/docs/PROTOCOLO_USB.md)). |
| **Sonda 100×** | **Hecho:** `ch-probe N 2` → 100× ([`../pyhantek/docs/PROTOCOLO_USB.md`](../pyhantek/docs/PROTOCOLO_USB.md)). |
| **Invert canal** | **Lectura:** último byte 0x15; parejas **0x97/0x95** (XOR 0x02) y **0x9d/0x8f** (XOR 0x12). **USB `0x18` / `ch-invert`:** mueve el byte en `read-settings` pero en 2D42 **rompe estabilidad del trigger** (empírico); **invert operativo = menú**. Cerrar con **RE** (`FUN_08031a9e` / menú) o diff estado; **sin** depender de captura USB en PC. **CH2:** pendiente. |
| **V/div índices 10–11** | En [`../pyhantek/ch_volt_map_empirico.json`](../pyhantek/ch_volt_map_empirico.json) hubo repetición / UI rara; repetir en **CH1** (`--channel 0`) y/o correlacionar con bytes de `0x15` cuando se conozca el offset del índice V/div. |
| **Pulse width trigger** | El manual menciona nivel para **Edge o Pulse width**; en `HTHardDll` domina el disparo tipo **edge** (`0x10`–`0x14`…). Falta: ¿hay opcode / trama para **PW** en este stack o es solo UI? |
| **Force trigger (manual)** | Acción de UI para capturar sin disparo válido. **Trama USB desconocida** (≠ `0x17`). Procedimiento: `tools/PROCEDIMIENTO_force_trigger.txt` + `snapshot_scope_state.py` / `compare_scope_snapshots.py`. **UX 2D42 (empírico):** con disparo en **Normal**, Force en panel → sensación de **onda en movimiento** / poco respeto al trigger (parecido a **Auto** en el manual); con modo **Single**, el comportamiento encaja mejor con “una adquisición” del texto del PDF. |

---

## 3. Firmware: opcodes / ramas sin comando CLI documentado

- En **`FUN_08031a9e`**, rama **`bVar1 == 0x18`**: usa bytes adicionales y `FUN_0801ef70` — **sin equivalente** en `Opcodes04440` / tabla EXPORTS del repo. Identificar significado (posible ajuste fino de disparo u otra función).
- Revisar si existe tratamiento explícito de **`0x16`** como *setter* en el mismo handler frente a la ruta de **captura** `0x55 0x0A … 0x16` (no mezclar).

---

## 4. Manual: funciones probablemente fuera de `HTHardDll` + pyusb actual

Gestión en **pantalla / flash interna**; no suelen mapearse 1:1 a `dsoHTSetCH*`:

- **Default settings** (menú de atajos largos, F1/F4).
- **Guardar / recuperar** trazas en memoria interna; canal **REF**.
- **Cursores** y **mediciones** en UI; exports tipo **`dsoHTSetMeasureItem`** / resultados en RAM según EXPORTS (sin flujo pyusb documentado en este repo).
- **Utilidad**: idioma, retroiluminación, apagado automático, atajos.
- **Probe check** / compensación: procedimiento en el instrumento.

Pregunta abierta: si algún estado aparece reflejado en **`read-settings`** (payload 21 B) habría que **tabular byte a byte** frente a la UI.

---

## 5. DLL con CLI pero poco validado en el hilo 2D42

- `zero-cali` (varias ramas), `factory-pulse`, `button-test`, `write-banner`, `write-cali` / `get-device-cali`, `fpga-update`, `clear-buffer`, `automotive`, etc.: **existen comandos**; falta matriz **“qué hace en un 2D42 concreto”** si se busca paridad con el software oficial.

---

## 6. Prioridades sugeridas

1. **`set-yt-format`** con base de tiempos lenta y anotación explícita de **Y-T / Roll / Scan** en pantalla.  
2. **`ch-couple` → GND** y **`ch-probe` → 100×** (un paso por valor).  
3. **`scope-autoset`** con DDS fijo y criterio ok/mal.  
4. **Pulse width**, **Force**, **opcode `0x18`**: investigación (USB + Ghidra), no solo prueba rápida.  
5. **Medición / cursores / REF / save**: decidir alcance del proyecto (solo hardware-scope vs acercarse a **HTSoftDll**).  
6. **DMM / DDS**: cerrar matriz de §8 (decodificación, eco IN, `dds-download`).  
7. **Diff de estado:** `tools/compare_read_settings.py` y `tools/snapshot_scope_state.py` para cerrar huecos (Force trigger, menús) sin adivinar bytes — **sin** usbmon/Wireshark (política del proyecto).

---

## 7. Índice del manual (Hantek 2000 series **V1.3**, `Hantek_2D72_2D42_Manual.txt`) → repo

Leyenda: **Sí** = hay comando o lectura documentada razonable; **Parcial** = algo implementado pero falta paridad o tablas; **No** = típicamente UI / flash / otro DLL, o aún sin trama.

### Getting Started (manual p. ~1–7)

| Sección manual | USB / CLI / notas |
|----------------|-------------------|
| General Inspection, bracket, front panel | N/A (físico). |
| Functional Check | Procedimiento en pantalla; podés apoyarte en `read-settings`, `run-stop`, `get-real-data` para comprobar respuesta. |
| **Probe Check** / compensación | Procedimiento en instrumento + sonda; **sin** comando dedicado en `hantek_usb`. |

### Function Introduction (manual p. ~8–18)

| Sección manual | USB / CLI / notas |
|----------------|-------------------|
| Menu and Control Keys | N/A (UI). |
| Connectors | N/A. |
| **Automatically set** | `scope-autoset` (`0x13`); falta validar = botón **Auto** del manual. |
| **Default Setting** | Atajos F1/F4 en equipo; **no** mapeado a un único opcode en el repo. |
| **Horizontal System** (Y-T, Roll, Scan, X-Y, TIME) | `set-time-div`; **modo horizontal**: lectura `read-settings --parse` → `ram98_byte0`; **escritura** PC abierta ([`../pyhantek/docs/PROTOCOLO_USB.md`](../pyhantek/docs/PROTOCOLO_USB.md)). |
| **Vertical System** | `ch-onoff`, `ch-couple`, `ch-probe`, `ch-bw`, `ch-volt`, `ch-pos`; GND/100× documentados; **invert:** menú; USB vía `0x18` no fiable (disparo). |
| **Trigger System** (Edge, nivel, modo, fuente, **Pulse width** en texto del manual) | `set-trig-source`, `set-trig-slope`, `set-trig-sweep`, `set-trig-hpos`, `set-trig-vpos`; **PW** y **Force trigger** sin trama clara. |
| **Save Waveform** | Memoria interna / USB host en manual; **no** en CLI como “guardar REF en flash”. |
| **Reference Waveform** | Canal REF en UI; **no** documentado por USB aquí. |
| **Measurement** (mediciones en pantalla) | En DLL: `dsoHTSetMeasureItem`, `dsoHTGetMeasureResult`, etc.; **sin** flujo pyusb/CLI en este repo. |
| **Utility** (idioma, backlight, apagado, …) | Casi todo **solo panel**; comprobar si algún byte del payload `0x15` refleja opciones (tabla abierta). |

### DMM (manual p. ~19–21)

| Sección | USB / CLI |
|---------|-----------|
| Interface / Measurement | **Parcial:** `set-mode dmm`, `dmm-read`, `dmm-type`, etc. Detalle validado y huecos: **[`../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md`](../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md)**, **[`../pyhantek/docs/DMM_FIRMWARE_DECODIFICACION.md`](../pyhantek/docs/DMM_FIRMWARE_DECODIFICACION.md)**. Lista de pendientes: **§8** abajo. |

### Generator / AWG (manual p. ~22–26)

| Sección | USB / CLI |
|---------|-----------|
| Interface, sine, arb | **Parcial:** `set-mode dds`, `dds-wave`, `dds-fre`, `dds-amp`, …, `dds-download`. Eco IN poco fiable; cabecera download incompleta — **§8** y [`../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md`](../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md). |

### Carga, batería, troubleshooting, anexos (manual p. ≥27)

| Sección | Notas |
|---------|--------|
| Charge / battery / troubleshooting / specs / accessories | N/A protocolo `hantek_usb`; mantenimiento y especificaciones comerciales. |

### Apéndice implícito: software PC (Scope.exe)

Funciones que el manual atribuye al **uso del instrumento** pero que en PC pueden pasar por **HTSoftDll / MeasDll / HTDisplayDll**: cursores, FFT en PC, lista de medidas, archivo .hantek, etc. Este repo se centra en **HTHardDll + firmware**; ampliar alcance = documentar esas DLL aparte.

---

## 8. DMM y AWG/DDS: pendientes para recordar

Los comandos CLI existen; **no** dar por cerrada la paridad manual + pantalla + decodificación. Detalle ampliado en [`../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md`](../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md) (y DMM en [`../pyhantek/docs/DMM_FIRMWARE_DECODIFICACION.md`](../pyhantek/docs/DMM_FIRMWARE_DECODIFICACION.md)).

### DMM (`dsoGetDMMData` / `dsoSetDMMType`)

- [ ] **Matriz modo ↔ hex:** validar **todos** los rangos del manual (AC/DC A, mA, mV, V, Ω, C, diodo, count, …) con **pantalla + trama 14 B**; ampliar `dmm_decode` / reglas en `dmm_decode.py` donde falte.
- [ ] **Subformato `[6]==0x03`:** cerrar **fórmula general** (caso `09 09 08` → 1,00 V y variantes).
- [ ] **`dmm-modes` / índice `dmm-type`:** confirmar contra equipo que **0..10** = lista `DMM_MODE_NAMES_ORDERED`; rellenar **`DMM_TYPE_FROM_BYTE`** si el firmware usa otros códigos.
- [ ] **Hold / auto-range / subtítulos del manual:** comprobar si solo UI o si cambian bytes fijos en `dmm-read`.
- [ ] **Otros modelos / firmware:** repetir matriz si cambia PID o DFU.

### AWG / DDS (`ddsSDK*`)

- [ ] **Lectura IN tras `dds-*`:** no usar como **eco** del valor escrito; documentar si algún subcódigo devuelve estado útil (pruebas CLI + LCD/medición).
- [ ] **`dds-offset`:** discrepancia **USB vs LCD** y efecto en **salida real** (medir con DMM/scope); ver § offset en [`../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md`](../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md).
- [ ] **`dds-download`:** **layout completo** de cabecera (variantes `0x406` / `0x46C`) — captura frente a Scope.exe o reversing `HTHardDll` / firmware.
- [ ] **Arb1–arb4:** flujo probado con **`--file`**; falta plantilla/documentar generación de muestras alineada al oficial.
- [ ] **Stubs DLL** (`ddsSDKSetBurstNum`, `ddsSDKSetWavePhase`, etc.): confirmar si el 2D42 los ignora o hay otra vía.
- [ ] **Triángulo / rampa (`0x05`):** mapeo fino LCD ↔ valor si hace falta más allá de duty único.

---

## Referencias en el repo

- [`../pyhantek/docs/PROTOCOLO_USB.md`](../pyhantek/docs/PROTOCOLO_USB.md) — protocolo USB y tablas empíricas.  
- `EXPORTS_HTHardDll.md` — mapeo DLL → opcodes.  
- [`../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md`](../pyhantek/docs/HALLAZGOS_DMM_DDS_2026-03.md) — validado DMM/DDS + **pendientes enlazados desde §8**.  
- [`../pyhantek/docs/DMM_FIRMWARE_DECODIFICACION.md`](../pyhantek/docs/DMM_FIRMWARE_DECODIFICACION.md) — pipeline DMM en firmware.  
- `IMPLEMENTACION_CHECKLIST.md` — checklist de pendientes con trazabilidad (decomp → código → test → hardware).  
- `tools/scope_label_walk.py` — barridos interactivos para nuevas tablas.  
- [`../pyhantek/hantek_usb/parse_resp.py`](../pyhantek/hantek_usb/parse_resp.py) — etiquetas en `read-settings --parse`.
