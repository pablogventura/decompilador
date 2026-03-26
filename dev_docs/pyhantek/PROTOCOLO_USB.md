# Protocolo USB — Hantek 2xx2 (2D42, 2D72, …) a partir de `HTHardDll` descompilado

Este documento resume lo que se deduce de **`HTHardDll.dll`** descompilado, del **INF del driver** y de las DLL de ST, para orientar una **herramienta Python (libusb/pyusb)** en Linux/macOS/Windows.

**Artefactos en el repo:** el binario PE suele estar en **`../../hantek/HTHardDll.dll`** (carpeta de decompilación). Los `.c` exportados por Ghidra viven en la carpeta **`decompiled_hantek/HTHardDll.dll/`** (no es un segundo DLL; es pseudocódigo derivado del primero).

**En este repo**, la CLI usa por defecto **`VID=0x0483`** y **`PID=0x2D42`** (coincide con el INF del 2D42). Otros modelos (p. ej. **2D72** como **`0483:2d72`**): `--pid 0x2d72`.

---

## 1. Identidad USB

Del archivo `Driver/Win10/Hantek2D42.inf` (referencia del modelo **2D42** en el paquete de drivers):

| Campo | Valor |
|--------|--------|
| **VID** | `0x0483` (STMicroelectronics) |
| **PID** | `0x2D42` |
| Cadena HW | `USB\VID_0483&PID_2D42` |
| Clase en INF | USB (GUID estándar de dispositivos USB) |

El **2D72** suele aparecer como **`0483:2d72`** en `lsusb` (mismo VID, otro PID).

El **firmware** suele ir en un MCU ST; el **driver kernel** `Hantek2D42.sys` (Cypress en el copyright del INF) expone el dispositivo a modo usuario.

---

## 2. Cómo habla Windows el software oficial

### 2.1 Apertura del dispositivo

En **`FUN_10001860`** (`HTHardDll.dll`):

- `SetupDiGetClassDevsA` / `SetupDiEnumDeviceInterfaces` / `SetupDiGetDeviceInterfaceDetailA`.
- Se filtra la ruta del interfaz que contiene la subcadena **`vid_0483&pid_2d42`** (literal en el binario).
- La ruta resultante (típico `\\?\usb#vid_0483&pid_2d42#...`) se guarda por “canal” y se usa en **`CreateFileA`** (**`FUN_10001b90`**).

### 2.2 Transporte de datos

- **`FUN_10001c60`**: `WriteFile` al *handle* del dispositivo.
- **`FUN_10001e00`**: `ReadFile` al mismo *handle*.
- Los transferencias grandes se trocean en bloques de **64 bytes (`0x40`)**, con I/O superpuesto (`OVERLAPPED` + `WaitForSingleObject` + `GetOverlappedResult`).

Eso encaja con **USB full speed** y **paquetes de 64 B** en un endpoint **BULK** (habitual en ST).

### 2.3 Capa ST (opcional en el kit)

`STTubeDevice30.dll` usa **`DeviceIoControl`** con códigos tipo `0x2220xx` y también **`ReadFile`/`WriteFile`**. En muchos productos ST el acceso “directo” al tubo USB termina siendo bulk IN/OUT; en tu árbol, **`HTHardDll`** es el que implementa el **protocolo del osciloscopio** (`dsoHT*`, `dso*`).

---

## 3. Capa de aplicación (comandos)

La función común de **envío** es **`FUN_10002060`**, que acaba en **`FUN_10001c60`** (modo normal) o en **`FUN_10001fc0`** (otro modo interno cuando un flag por dispositivo está activo).

La de **recepción** típica es **`FUN_10002020`** (lecturas de `0x40` bytes, coherente con el troceo anterior).

### 3.1 Cabecera habitual (10 bytes)

Varias rutas montan un buffer de **10 bytes** antes de `FUN_10002060`. Patrones observados:

- **`dsoHTReadAllSet`** (`dsoHTReadAllSet_10002230.c`):  
  - Bytes iniciales del bloque de 4 + siguiente región: **`0x00`, `0x0A`, …** y **`0x15`** como “subcomando” en la zona siguiente (lectura de ajustes / estado).
- **Adquisición de trazas** (`FUN_10005010_10005010.c`):  
  - Primer byte **`'U'` (`0x55`)**, segundo **`0x0A`**, más campos fijos como **`0x01`**, **`0x16`**, y un **uint16** de extensión / contador, y **`0x14`** al final del bloque de 10 bytes — antes de enviar y luego leer múltiples bloques de **0x40** bytes.

Interpretación práctica (para seguir investigando):

| Offset (aprox.) | Rol probable |
|------------------|--------------|
| 0 | `0x00` o `0x55` — tipo de trama / “magic” |
| 1 | `0x0A` (10) — longitud o versión de cabecera |
| 2–3 | flags / reservado |
| 4+ | **código de orden** (p. ej. `0x15` lectura config, `0x16` captura muestras) y parámetros |

Los **`dsoHTSet*`** (p. ej. `dsoHTSetRunStop`) pasan por **`FUN_10004440`**, que empaqueta **`param_3` como código de orden** (ejemplo: **run/stop** usa **`0x0C`**) y hasta **4 bytes** de carga útil en el paquete de 10 bytes, luego lee **0x40** bytes y valida la respuesta.

### 3.2 API exportada útil para mapear órdenes

`strings HTHardDll.dll` muestra exports como:

`dsoHTDeviceConnect`, `dsoHTReadAllSet`, `dsoHTGetSourceData`, `dsoHTGetRealData`, `dsoHTSetTimeDiv`, `dsoHTSetRunStop`, `dsoHTSetTriggerSource`, …

Cada una acaba construyendo buffers y llamando a **`FUN_10002060`** / **`FUN_10002020`**. Para documentar **todas** las órdenes, conviene **seguir cada `dsoHTSet*` / `dsoHTGet*`** en `decompiled_hantek/HTHardDll.dll/` y anotar el **payload de 5–10 bytes** (y la longitud de lectura).

### 3.2.1 Tabla rápida `FUN_10004440` (opcodes scope) y riesgos

Referencia canónica en código: clase **`Opcodes04440`** en [`../../pyhantek/hantek_usb/protocol.py`](../../pyhantek/hantek_usb/protocol.py). Relación con exports del DLL: [`../hantek/EXPORTS_HTHardDll.md`](../hantek/EXPORTS_HTHardDll.md).

| Opcode (hex) | Export / uso típico | Notas / riesgo |
|----------------|---------------------|----------------|
| `0x0C` | `dsoHTSetRunStop` | En STM32 la ruta que **aplica** RUN/STOP suele ser `scope_run_stop_stm32`, no solo este opcode sobre `FUN_08032140` (ver §5 tabla y nota RUN/STOP). |
| `0x0D` | `dsoHTSetYTFormat` | Escritura USB **no** actualiza de forma fiable el byte horizontal que refleja `ram98_byte0` en `0x15` (ver `MANUAL_FIRMWARE_GAPS.md`). |
| `0x0E` | `dsoHTSetTimeDiv` | Índice empírico ↔ etiqueta pantalla: `parse_resp.TIME_DIV_LABELS` / `time_div_map_empirico.json`. |
| `0x0F`–`0x14` | Disparo (HPos, fuente, flanco, barrido, VPos) | `ram9c_byte*` en respuesta `0x15`. |
| `0x13` | `dsoHTScopeAutoSet` | Autoset por USB; validar frente al botón *Auto* del manual. |
| `0x17` | `dsoHTScopeZeroCali` | **No** es “Force trigger” del PDF: en 2D42 muestra calibración. |
| `0x18` | (sin export en `HTHardDll`) | Mueve `ram9c_byte9_plus_d`; en 2D42 puede **inestabilizar el disparo** — no usar como invert operativo. |

**Force trigger (manual PDF):** no aparece como export dedicado en `HTHardDll`; la hipótesis del proyecto es acción de **UI/firmware** o ruta distinta a `0x17`. Procedimiento sin sniff: [`../tools/PROCEDIMIENTO_force_trigger.txt`](../tools/PROCEDIMIENTO_force_trigger.txt).

### 3.3 Captura `0x16` y dos canales (entrelazado)

En el firmware (`FUN_08032140`), la respuesta de **adquisición** entrega bytes **consecutivos** desde la RAM de muestras. En **2xx2** con **dos canales activos**, el contenido encaja con **CH1, CH2, CH1, CH2…** (un byte ADC por canal e instante). Dibujar ese buffer como una sola curva **u8** mezcla ambos canales y deforma métricas.

En este repo, **`hantek_usb.osc_decode.split_interleaved_u8`** separa pares (CH1) e impares (CH2); es el **comportamiento por defecto** en `--export-csv`, `--parse` / `--analyze`, y en **[`../../pyhantek/tools/scope_live_view.py`](../../pyhantek/tools/scope_live_view.py)**. Para tratar el payload como **un solo canal** (depuración), usá **`--no-interleaved`** en `get-source-data` / `get-real-data`.

### 3.4 Respuesta `dsoHTReadAllSet` (firmware STM32)

Petición PC/DLL: `00 0A 00 01` + byte 5 = **`0x15`**. En el firmware, **`FUN_08032140`** (archivo `firmware/decompilado/FUN_08032140_08032140.c`, rama `else if (bVar1 < 0x16)` con `puVar5[3]=0x15` cuando el opcode del paquete entrante es **`0x15`**) arma la salida:

- **`[0]=0x55`**, **`[1]=0x19`** (longitud total **25** bytes), **`[2]=0`**, **`[3]=0x15`**.
- **`[4:25]`**: 21 bytes copiados desde RAM (`DAT_08032694`, `DAT_08032690`, `DAT_08032698`, `DAT_0803269c`): en cada caso el firmware suele tomar el **byte bajo** de un `ushort` en esa RAM, y en algunos índices suma **`'d'`** (100 decimal) para dos campos.

El DLL en Windows lee **64 B** y se queda con al menos **10** útiles; el bloque de **21 B** es el que interesa para “estado” compacto. **No** interpretes `[4:8]` como un único `uint32` LE: son **campos independientes** (ver `decode_read_all_set_firmware25` en `hantek_usb/parse_resp.py` y `read-settings --parse`).

#### 3.4.1 RAM del bloque `ram98` (modo horizontal, time/div, …)

En el binario STM32, el único literal **32-bit** igual a la base del bloque que alimenta `FUN_08032140` para esos campos está en el pool de flash **`0x08032624`**: valor **`0x2000cc4c`** (SRAM). El primer byte de esa estructura es el que el CLI etiqueta como **`ram98_byte0`**. Coincide con **`0x2000ca4c + 0x200`** (512 bytes por encima de la base del pool time/div usada en `ghidra_scripts/ReportPoolTableXrefs.java`). Ghidra puede no mostrar **xref de escritura** directa a `0x2000cc4c` (solo una referencia desde el pool): los stores suelen ser **base + desplazamiento**.

Reproducible con **`dev_scripts/ram98_sram_address.py`** (raíz del repo `decompilador/`).

#### 3.4.2 Escritura `dsoHTReadAllSet` (DLL) vs paquete USB de 10 bytes

Si el tercer argumento de **`dsoHTReadAllSet`** es **≠ 0** (modo escritura), el DLL prepara hasta **21 bytes** desde el buffer de la aplicación y los copia también a **`DAT_100e20de`** (estado por dispositivo), pero **`FUN_10002060` sigue enviando solo 10 bytes** al tubo USB. Por eso el CLI **`write-settings --tail`** solo admite **5 bytes** en posiciones **[5:9]**: no existe en esa API un “write de 21 B” hacia el firmware en un solo OUT de 10. Parchear **`ram98_byte0`** (índice **13** del payload de respuesta) **no** queda cubierto por ese write corto; habría que encontrar otra orden o confirmar con captura si otro binario del kit usa más tráfico.

---

## 4. Enfoque recomendado para Python (CLI)

### 4.0 Herramienta incluida en este repo

- Comando **`hantek`** (instalación: `pipx install ./pyhantek` o `pip install ./pyhantek`) — delega en el paquete `hantek_usb`.
- Paquete **`hantek_usb/`** — Código modular: `constants`, `transport` (bulk 64 B), `protocol` (tramas), `cli` (subcomandos). Ejecución: `python -m hantek_usb` o `python -m hantek_usb.cli` desde el directorio del proyecto **`pyhantek/`** (o tras instalar el paquete, desde cualquier cwd).
- CLI con **pyusb**: comandos anteriores más `get-device-cali`, `device-name`, `button-test`, `zero-cali`, `fpga-update` (JSON), `windows-stub-info`; **`--parse`** en varias lecturas; captura con **`--smart` / reintentos**; **`factory-pulse --wait-read`**. Ver [`../../pyhantek/README.md`](../../pyhantek/README.md). Instalación: `pipx install ./pyhantek` o `pip install -e ./pyhantek`. No sustituye al software del fabricante; sirve como base y para pruebas.
- [`../hantek/EXPORTS_HTHardDll.md`](../hantek/EXPORTS_HTHardDll.md) — **Mapeo export por export** (`dso*` / `dds*`): bytes enviados, cuántos bloques de **64 B** se leen y qué comprueba el DLL en cada respuesta.

### 4.1 Librerías

- **`pyusb`** + backend **`libusb1`** (o `libusb-0.1`).
- En Linux: reglas **udev** para poder abrir el dispositivo sin root; puede hacer falta **desvincular** el driver del kernel si reclama la interfaz (depende de si cargas `Hantek2D42` o no).

### 4.2 Pasos concretos

1. **Enumerar** `idVendor=0x0483`, `idProduct=0x2D42`.
2. Con el hardware conectado, obtener **descriptores** (`lsusb -v` o PyUSB):  
   - **`bInterfaceClass`**, **`bInterfaceSubClass`**, **`bInterfaceProtocol`**.  
   - Direcciones de **BULK IN** y **BULK OUT** (`bEndpointAddress`).
3. Reproducir el protocolo:
   - **Escribir** el mismo orden de bytes que `FUN_10002060` (empezando por los casos de **10 B**).
   - **Leer** en bloques de **64 B** hasta completar el tamaño esperado (como `FUN_10005010` / `FUN_10001e00`).
4. Validar contrastando con **`HTHardDll`** descompilado y con **pruebas en hardware** (CLI/pyusb, `read-settings`, forma de onda en pantalla). Este proyecto **no** asume captura del bus USB en el PC (p. ej. Wireshark/usbmon).

### 4.3 Referencias externas

Busca proyectos abiertos tipo **OpenHantek** / drivers para modelos 6022/6xxx: muchos Hantek comparten ideas (aunque el **mapa de comandos puede cambiar** por familia). Tu descompilado de **esta** DLL sigue siendo la fuente más fiable para el **2D42 / 2xx2** concreto.

### 4.4 Correlación empírica (opciones de visualización)

Los opcodes `0x0D`–`0x14` (`Opcodes04440`: YT, TIME_DIV, disparo, etc.) se envían como `fun_04440` con **valor entero** y **ancho de payload** (1–4 bytes).  
En este repo quedó tabulado el caso **TIME_DIV** (ver abajo); otros (p. ej. V/div) siguen dependiendo del estado del equipo y de medición empírica.

Para **medir el efecto** de cada ajuste sobre la captura cruda `0x16`, podés usar **[`../../pyhantek/tools/scope_options_probe.py`](../../pyhantek/tools/scope_options_probe.py)**: fija DDS (señal conocida), barre un parámetro (`--sweep time-div`, `ch1-volt`, …) y compara **pp** y **cruces por la media** en CH1/CH2. Ver [`../../pyhantek/README.md`](../../pyhantek/README.md) (scripts en `pyhantek/tools/`).

#### TIME_DIV (0x0E) — hallazgo importante

- En firmware STM32, para **aplicar** un setter `FUN_04440` (incluyendo `TIME_DIV`) hay que enviar el frame con **`[3]=0`** (write).
- Con **`[3]=1`** se obtiene eco/lectura (`FUN_08032140`) y puede parecer “ACK ok” pero **no cambia** el estado.
- En este repo quedó corregido en CLI/scripts (`set-time-div`, `scope_options_probe.py`, `time_div_label_walk.py`).

#### Mapeo empírico TIME_DIV (índice USB `ram98_byte3`)

Se midió en hardware y se guardó en [`../../pyhantek/time_div_map_empirico.json`](../../pyhantek/time_div_map_empirico.json):

- Rango **válido de UI** confirmado: `0..33` (`5ns/div` → `500s/div`, progresión 2-5-10).
- `34` aplica por USB pero en pantalla entra en estado inválido (`T->-0.000ns`, `Time ns`).

Resumen rápido:

| idx | tiempo/div | idx | tiempo/div |
|-----|------------|-----|------------|
| 0 | 5.000ns | 17 | 2.000ms |
| 1 | 10.000ns | 18 | 5.000ms |
| 2 | 20.00ns | 19 | 10.00ms |
| 3 | 50.00ns | 20 | 20.00ms |
| 4 | 100.0ns | 21 | 50.00ms |
| 5 | 200.0ns | 22 | 100.0ms |
| 6 | 500.0ns | 23 | 200.0ms |
| 7 | 1.000us | 24 | 500.0ms |
| 8 | 2.000us | 25 | 1.000s |
| 9 | 5.000us | 26 | 2.000s |
| 10 | 10.00us | 27 | 5.000s |
| 11 | 20.00us | 28 | 10.00s |
| 12 | 50.00us | 29 | 20.00s |
| 13 | 100.0us | 30 | 50.00s |
| 14 | 200.0us | 31 | 100.0s |
| 15 | 500.0us | 32 | 200.0s |
| 16 | 1.000ms | 33 | 500.0s |

#### TRIGGER_SWEEP (0x12) — empírico 2D42

| índice USB | texto en pantalla |
|------------|-------------------|
| 0 | Auto |
| 1 | Normal |
| 2 | Single |

#### Opcode 0x17 (`dsoHTScopeZeroCali` / `scope-zero-cali`)

- **DLL:** `dsoHTScopeZeroCali` usa opcode **0x17** (`EXPORTS_HTHardDll.md`).
- **Empírico (2D42):** al enviar esta orden por USB, la pantalla muestra **«Calibrating»** — es **calibración / cero de canal**, no sustituir sin más por el **«Force Trigger»** descrito en el manual PDF (ese texto habla de completar una adquisición sin disparo válido; por cable, **0x17** coincide con la rutina de calibración del export del DLL).
- En el CLI, **`trig-force`** es solo un **alias** de **`scope-zero-cali`**; el nombre puede confundir: preferí **`scope-zero-cali`** para este opcode.

#### Pendiente de cerrar en hardware (checklist)

| Tarea | Cómo |
|-------|------|
| Tabla **V/div** índice→pantalla | [`../../pyhantek/tools/scope_label_walk.py`](../../pyhantek/tools/scope_label_walk.py) `--kind ch-volt` (y `--channel 1` para CH2) |
| **YT format** (0x0D) | `scope_label_walk.py --kind yt` |
| **Slope** tercer valor (manual: rising & falling) | `scope_label_walk.py --kind slope --values 0,1,2` |

##### CH_VOLT (índice USB → V/div) — `ch_volt_map_empirico.json`

Barrido con **`scope_label_walk` en canal 1 (CH2)**; suele coincidir con CH1.

| idx | V/div en pantalla |
|-----|-------------------|
| 0 | 10 mV |
| 1 | 20 mV |
| 2 | 50 mV |
| 3 | 100 mV |
| 4 | 200 mV |
| 5 | 500 mV |
| 6 | 1 V |
| 7 | 2 V |
| 8 | 5 V |
| 9 | 10 V |
| 10–11 | Repitió **100 mV / 200 mV** (UI ambigua; confirmar en otro canal o firmware). |

En **`read-settings --parse`** aún **no** enlazamos un byte fijo del payload 0x15 al índice V/div (el setter usa `DAT_08032694+0x21` por canal, distinto del mapeo trivial en los 21 B); la tabla sirve para **`ch-volt`** por USB y para scripts.

##### CH_COUPLING (`ch-couple`) — empírico 2D42

Comando: `ch-couple <canal> <idx>` (opcode `ch×6+1`). Validado en CH1 (2026-03-25).

| idx | Pantalla |
|-----|----------|
| 0 | AC |
| 1 | DC |
| 2 | GND (traza plana / referencia a masa) |

##### CH_PROBE (`ch-probe`) — empírico 2D42

Comando: `ch-probe <canal> <idx>` (opcode `ch×6+2`). Validado CH1 (2026-03-25).

| idx | Pantalla |
|-----|----------|
| 0 | 1× |
| 1 | 10× |
| 2 | 100× |
| 3 | 1000× |
| 4 | **Evitar:** en un 2D42 la UI mostró **«coupling»** en la zona de sonda (estado incoherente; no usar en operación normal). |

**Invert** (menú del canal): **no** sale de `ch-probe` **3** ni **4** (3 = 1000×; 4 = UI rara). No hay `dsoHTSetCHInvert` en la tabla típica del DLL.

**Lectura `0x15` (invert CH1 en menú):** suele cambiar **solo el último byte** del payload de 21 B (`ram9c_byte9_plus_d`, índice **20**). El valor **no** es fijo entre sesiones: en una pareja (capturas 2026-03) **no invertido `0x97`** vs **invertido `0x95`** (**XOR `0x02`**); en otra prueba **no invertido `0x9d`** vs **invertido `0x8f`** (**XOR `0x12`**). Ver `captures/COMPARACION_invert_CH1.txt`.

**Escritura USB (opcode `0x18`):** `FUN_04440` write, 1 B en `[5]`, **sí** mueve el valor que luego devuelve **`read-settings`** en `ram9c_byte9_plus_d`. En **2D42** (2026-03) **no** debe usarse como invert “de producción”: en prueba de campo **degradó el disparo** (traza inestable / señal que se mueve). La correlación menú ↔ byte queda útil para **lectura** y para **RE**; falta la secuencia o el payload que el firmware trate como el menú (**Ghidra** / diff estado panel ↔ `read-settings`). CLI **`ch-invert`** queda como **experimental** con aviso. Payloads **3 B** distintos pueden poner `ram9c` en `0x00` (riesgo).

##### TRIGGER_SLOPE — `trig_slope_labels.json`

| idx | Pantalla |
|-----|----------|
| 0 | rising |
| 1 | falling |
| 2 | double (rising & falling) |

En respuesta **0x15**, `ram9c_byte3` lleva este índice; `parse_resp` añade `trigger_slope_label` en `--parse`.

##### TRIGGER_SWEEP — ya tabulado arriba

`ram9c_byte6` → `trigger_sweep_label` (Auto / Normal / Single).

##### YT format (`set-yt-format`, opcode **0x0D**)

Empírico **2D42** con **`TIME_DIV` índice 22** (≈**100 ms/div** en pantalla) y **RUN**:

| idx USB | Texto en pantalla | Comportamiento |
|---------|-------------------|----------------|
| 0 | Y-T | Trazo que se **dibuja de izquierda a derecha** (similar a **Scan** a base lenta según manual). |
| 1 | Y-T | **Igual** que idx 0 (sin cambio visible de etiqueta ni movimiento). |
| 2 | Y-T | **Igual** que idx 0. |
| 3 | Y-T | **Igual** que idx 0. |

**Conclusión USB `0x0D`:** índices **0–3** no cambian modo visible a **100 ms/div**; **Roll / Scan** se eligen en el menú **Time** del equipo.

**Cruce firmware:** en **`FUN_08031a9e`**, para opcode **13** (`0x0D`) la cadena `else if (bVar1 < 0x0E)` tras `0x0C` solo ejecuta **`*DAT_080326b0 = 0`**; **no** asigna el primer byte de **`DAT_08032698`** (el que se refleja como **`ram98_byte0`** en la lectura `0x15`). Coherente con que **`set-yt-format`** no mueva ese byte en hardware.

**Cruce HTHardDll:** **`dsoHTSetYTFormat`** es el **único** export que llama a **`FUN_10004440`** con opcode **`'\r'`** (`0x0D`). No aparece en el descompilado otro `dsoHTSet*` distinto dedicado a Y-T / Roll / X-Y. La API Win32 recibe un **`short param_2`** y el DLL reduce el valor enviado en los **2 bytes** del paquete así (ver `dsoHTSetYTFormat_10004d00.c`):

| `param_2` (API) | `uint` pasado a `FUN_10004440` (ushort LE en [5:6]) |
|-----------------|-----------------------------------------------------|
| `0` | `0` |
| `1` | `1` |
| cualquier otro | `2` (`(param_2 != 1) + 1`) |

Así, los índices **2 y 3** de la API colapsan al **mismo** valor **2** en el bus; no explican por sí solos cuatro modos distintos en el firmware.

**Lectura `0x15` (empírico, togglear modo en Time / horizontal, resto igual):** suele cambiar solo **`ram98_byte0`** (índice **13** en `data[4:25]`):

| Valor | Modo en pantalla (2D42) |
|-------|-------------------------|
| `0x00` | Y-T |
| `0x01` | Roll |
| `0x02` | X-Y |

**Scan** (si el menú lo distingue de estos) queda por capturar con otro hex; podría ser **`0x03`** o compartir valor con otro modo según firmware. `read-settings --parse` muestra `horiz=…` en ese campo.

Para **escribir** Y-T/Roll/Scan desde PC sigue abierto: ni **`set-yt-format`** ni **`write-settings`** (5 B de cola) cubren el byte de modo horizontal según firmware + DLL; hace falta **otra orden** o más **reversing** (stores hacia **`0x2000ca4c+0x200`** / `0x2000cc4c`), más diff de `read-settings` tras cambiar solo el menú Time.

| Tarea | Cómo |
|-------|------|
| **Autoset** | `python -m hantek_usb scope-autoset` (efecto global, manual) |
| **Force trigger** (manual PDF, ≠ 0x17) | Sin trama USB conocida: **RE** + snapshots/diff `read-settings` tras Force en panel (sin capturar el bus en PC). **Nota de uso (2D42):** Force con **Normal** en menú puede dar sensación de barrido continuo; **Single** suele coincidir mejor con “una adquisición” del manual — detalle en [`../tools/PROCEDIMIENTO_force_trigger.txt`](../tools/PROCEDIMIENTO_force_trigger.txt). |

Los comandos **`ch-*`**, **`set-trig-hpos`** y **`set-trig-vpos`** en el CLI usan **`[3]=0`** (escritura) por defecto, igual que `set-time-div`.

---

## 5. Archivos clave en `decompiled_hantek/HTHardDll.dll`

| Archivo / símbolo | Qué mirar |
|-------------------|-----------|
| `FUN_10001860` | Enumeración SetupAPI + filtro `vid_0483&pid_2d42` |
| `FUN_10001b90` | `CreateFileA` sobre la ruta del interfaz |
| `FUN_10001c60` / `FUN_10001e00` | `WriteFile` / `ReadFile`, troceo **0x40** |
| `FUN_10002060` / `FUN_10002020` | Envío / recepción lógica |
| `FUN_10005010` | Trama con **`0x55 0x0A … 0x16`** y lectura de muestras |

**Nota (firmware STM32, `FUN_080326b8` / `FUN_08034184`):** el **RUN/STOP** de hardware no coincide con la trama “DLL” `FUN_04440` opcode `0x0C` sobre la ruta `FUN_08032140` (ahí `0x0C` solo hace eco de estado). La orden que **escribe** marcha/paro usa **`00 0A 02 00 08`** y byte `[5]=0|1` (ver `scope_run_stop_stm32` en `hantek_usb/protocol.py`).
| `dsoHTReadAllSet_10002230.c` | Trama con **`0x15`** (config); rama escritura: ver §3.4.2 |
| `FUN_10004440` | Plantilla genérica de set/get con opcode y hasta 4 B de datos |
| `dsoHTSetYTFormat_10004d00.c` | Opcode **`0x0D`**; mapa `param_2` → ushort (tabla arriba) |
| `dsoHTSetRunStop_10004e00.c` | Ejemplo: opcode **`0x0C`** para run/stop |

---

## 6. Limitaciones

- Lista explícita **manual + firmware vs implementación**: [`../hantek/MANUAL_FIRMWARE_GAPS.md`](../hantek/MANUAL_FIRMWARE_GAPS.md).
- Checklist de trabajo e ítems pendientes con trazabilidad: [`IMPLEMENTACION_CHECKLIST.md`](IMPLEMENTACION_CHECKLIST.md).
- El descompilado **no sustituye** capturar tráfico USB real: los campos aún no descritos requieren **prueba en hardware**.
- En **Linux**, sin el `.sys` de Windows, el camino es **libusb directo**; permisos y **reclamación de interfaz** son el principal fricción operativa, no el análisis estático.

### 6.1 DMM y DDS: no fiarse del eco IN

Resumen alineado con [`HALLAZGOS_DMM_DDS_2026-03.md`](HALLAZGOS_DMM_DDS_2026-03.md):

- **Captura `0x16` con dos canales:** el stream es **entrelazado** CH1, CH2, CH1, CH2…; usar `split_interleaved_u8` / CSV por defecto (`get-source-data` / `get-real-data`); para depuración, `--no-interleaved`.
- **Autoset antes de capturar:** en pantalla suele usarse *Auto Fit* / autoset para que V/div y tiempo dejen bien la traza. Por USB, el equivalente es **`scope-autoset`** (`FUN_04440`, opcode `0x13`) **antes** de `read_all_settings` + RUN + petición `0x16`. El script **[`../../pyhantek/tools/capture_scope_after_autoset.py`](../../pyhantek/tools/capture_scope_after_autoset.py)** ejecuta esa secuencia y escribe el binario de muestras (misma idea que `get-real-data` pero con autoset previo).
- **Respuestas IN cortas (~10 B) tras comandos DDS:** patrón `55 07 02 …`; el `uint32` en la respuesta **no** es un eco fiable del valor enviado (amplitud, frecuencia, offset). Validar **LCD o medición física**.
- **`dds-offset`:** la respuesta IN puede repetirse o no reflejar el offset; el LCD puede no coincidir con lo que interpreta el PC; la comprobación definitiva de la salida es **medir DC** en la salida del generador.
- **`dds-offset` layout (firmware `FUN_080326b8`):** subcódigo `0x03` consume **magnitud `u16` en `[5:6]`** y **signo en `[7]`** (`0` positivo/cero, `1` negativo); no tratarlo como `u32` plano.
- **`dds-fre` / `dds-amp` (2D42):** por defecto el CLI envía **write puro** (`byte[3]=0`), que en hardware suele ser la ruta que **sí aplica** frecuencia y amplitud; la ruta con lectura IN (tipo DLL) queda detrás de **`--readback`** para depuración/comparación.

### 6.2 Métricas en PC, frecuencia estimada y `external_ch1_smoke`

- Módulo **[`../../pyhantek/hantek_usb/scope_signal_metrics.py`](../../pyhantek/hantek_usb/scope_signal_metrics.py)**: cruces por la media sobre muestras u8; estimación de **frecuencia en Hz** usando `ram98_byte3` + tabla empírica de time/div y una ventana horizontal asumida (**10 divisiones** por defecto, configurable). Es **heurística**: la memoria de captura no tiene por qué coincidir exactamente con el grid de 10 divs en todos los modos.
- Script **[`../../pyhantek/tools/external_ch1_smoke.py`](../../pyhantek/tools/external_ch1_smoke.py)** (señal **externa** en CH1): pone scope en marcha, disparo **Auto**, opcionalmente `scope-autoset` (`0x13`), captura `0x16` y devuelve métricas + `freq_hz_est`. Con `--scope-autoset`, el JSON incluye **`settings_autoset_diff`**: lista `{field, old, new}` sobre `fields_u8` (misma idea que `compare_scope_snapshots --json`), vía **`diff_read_settings_summaries`** en `scope_signal_metrics`. Tras `pipx install ./pyhantek` también existe el comando **`external-ch1-smoke`**. **Códigos de salida:** `0` OK; `1` USB/parse; `2` señal plana / pocos cruces / clipping; `3` `--expect-hz` fuera de tolerancia.

Con esto deberías poder plantear el CLI: **abrir dispositivo → bulk OUT comando 10 B → bulk IN bloques 64 B → interpretar** según vayas completando la tabla de opcodes desde el resto de `dsoHT*`.
