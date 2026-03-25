# Mapeo de exports `HTHardDll.dll` → USB y bloques de respuesta

Binario de referencia en el repo: **`hantek/HTHardDll.dll`**. Pseudocódigo: carpeta **`decompiled_hantek/HTHardDll.dll/`**.

Fuente: `decompiled_hantek/HTHardDll.dll/*.c`. Convenciones:

- **`FUN_10002060(buf, n)`** = escribe **n** bytes al dispositivo (en Windows, `WriteFile`; troceo interno en múltiplos de **64** cuando aplica).
- **`FUN_10002020(buf, 0x40)`** = lee **exactamente un** intento de **64 bytes** (0x40) al buffer del usuario.
- **`FUN_10004440`** = plantilla de **10 bytes** + opcionalmente **una** lectura de **64 bytes**; el DLL comprueba que **`respuesta[3] == opcode`** (byte índice **3** del bloque leído = código de orden enviado en el byte **4** del paquete de 10, ver abajo).

## Paquete tipo `FUN_10004440` (10 bytes)

Layout reconstruido del descompilado:

| Offset | Significado habitual |
|--------|----------------------|
| 0 | `0x00` |
| 1 | `0x0A` (10) |
| 2 | `0x00` |
| 3 | `0x01` si el DLL va a **leer** respuesta tras escribir; `0x00` si solo escribe (tercer `short` ≠ 0 en varias `dsoHT*`) |
| 4 | **Opcode** (orden) |
| 5… | Carga útil **little-endian**, ancho 1–4 bytes según función |
| … | Relleno `0` hasta completar 10 bytes |

**Qué esperar en el primer bloque de 64 B (familia `FUN_10004440`, modo con lectura):**

- **`data[3] == opcode`** si no hay error; si no coincide, el DLL muestra error (no llega a parsear el valor).
- El **valor devuelto** al programa C se reconstruye con **little-endian** desde bytes del buffer **tras** la lectura (posiciones exactas dependen del opcode y del ancho `param_5`; en la práctica: inspeccionar los 8–16 primeros bytes del bloque en hex).
- Si el tercer argumento `short` de la `dsoHT*` correspondiente es **≠ 0**, a veces **no** se llama a `FUN_10002020`: solo se envían los 10 B.

---

## Exports **sin** tráfico USB (solo RAM / estado local)

| Export | Notas |
|--------|--------|
| `dsoHTDeviceConnect` | Abre handle / modo alterno interno; no siempre un único paquete fijo. |
| `dsoHTConnectType` | Lee/escribe flags en `DAT_*` (USB indirecto vía estado). |
| `dsoHTSetNetinfo` | Guarda IP/puerto en RAM (`DAT_100e1798`…). |
| `dsoGetDevPath` | Copia la ruta `\\?\usb#…` ya resuelta en memoria. |
| `dsoHTSetMeasureItem` | Máscaras en `DAT_100e2158`. |
| `dsoHTGetGetMeasure` | Copia desde `DAT_100ed920` (2× bloques). |
| `dsoHTGetMeasureResult` | Lee doubles en RAM tras mediciones previas. |
| `dsoGetSampleRate` | Cálculo en FPU desde estado en `DAT_100e20*`. |
| `dsoInitHard` | Llama `dsoHTReadAllSet(..., 0)` → **sí hay USB** (ver tabla siguiente). |
| `ddsSDKSetBurstNum` | Retorno constante `1` (stub). |
| `ddsSDKSetWavePhase` | Retorno constante `1.0` (stub). |

---

## Tabla por export (USB explícito)

Leyenda: **W** = escribe, **R64** = lee un bloque de 64 B, **(n)** = escribe n bytes.

| Export | Enviado | Leído | Notas / opcode (byte 4 del paquete de 10 si aplica) |
|--------|---------|--------|------------------------------------------------------|
| `dsoHTReadAllSet` | W(10) | R64 si lectura (`param_3==0`) | Bytes iniciales `00 0A 00 01`; byte 5º = **`0x15`**. Respuesta: al menos **10** bytes útiles según DLL; copia **21 B** a estado + byte extra en offset 0x15 del struct destino. **Escritura** (`param_3≠0`): el DLL copia hasta **21 B** desde el buffer de app a **`DAT_100e20de`**, pero **`FUN_10002060` solo envía 10 B** al USB — no amplía el OUT; ver `PROTOCOLO_USB.md` §3.4.2. |
| `dsoWorkType` | W(10) | R64 si consulta | Familia `00 0A 03 …`; byte 6 del paquete de 10 (índice 5) = **modo**: `0` osciloscopio, `1` multímetro, `2` generador (2xx2). Respuesta: `ushort` en zona `local_3c` del buffer. |
| `dsoGetDeviceCali` | W(10) | R64 | Similar a otras consultas “tipo 3”. |
| `dsoWriteDeviceCali` | W(**5 + n**) | — | Longitud **variable** (`uVar3 + 5`). |
| `dsoGetSTMID` | W(10) | R64 | `00 0A 03 01` + byte 5 = **`0x01`**. Respuesta: formateo vía `FUN_10007e02` (texto); inspeccionar 64 B en hex. |
| `dsoGetFPGAVersion` | W(10) | R64 | Byte 5 = **`0x0C`**. DLL usa `ushort` desde buffer (posición depende del layout local). |
| `dsoGetArmVersion` | W(10) | R64 | Byte 5 = **`0x0A`**. Respuesta: string en zona tras cabecera; mín. **3** bytes reportados por DLL. |
| `dsoDeviceName` | W(10) | R64 si lectura | Patrón “nombre”; payload opcional si magic `0x7789`. |
| `dsoDeviceSN` | W(**10 o 0x25**) | R64 si lectura | Longitud **10** o **37** (0x25) según rama; serial en buffer. |
| `dsoClearBuffer` | — | **R64 solo** | **Sin** `FUN_10002060` previo en el descompilado: solo `FUN_10002020`. Ajusta timeout interno 200↔1000 ms. |
| `dsoZeroCali` | W(10) / W(var) | R64 en ramas | Varias tramas; envío largo `uVar5+6` en una rama. |
| `dsoFactorySetup` | W(10) | — luego `dsoHTReadAllSet` | Trama `00 0A 03 00` + byte 5 = **`0x0A`**; `Sleep(3000)`; después lectura de settings. |
| `dsoSetButtonTest` | W(10) | R64 opcional | Según rama. |
| `dsoWriteBanner` | W(**0x1E**) | — | **30 bytes** de payload. |
| `dsoSetDMMType` | W(**5**) | — | `00 05 01 00` + byte 4 = tipo. |
| `dsoGetDMMData` | W(**5**) | R64 | `00 05 01 01` + …; parsea dígitos/escala en bytes del bloque (ver `dsoGetDMMData_10003510.c`). |
| `dsoIsAutomotive` | W(10) | R64 | Igual patrón que `ddsSDKExist` pero interpretación distinta (byte 5 = **`0x07`**, familia `00 0A 03 01`). |
| `dsoUpdateFPGA` | W(10) repetido + W(**variable**) | — | Secuencia larga (magic `0x567…`); trozos **0x30** bytes típicos; **no** es un solo comando simple. |
| `dsoHTSetRunStop` | vía `FUN_10004440` | R64 si `param_3==0` | Opcode **`0x0C`**, **2** bytes valor (run/stop). |
| `dsoHTSetTimeDiv` | idem | idem | Opcode **`0x0E`**, 2 B. |
| `dsoHTSetYTFormat` | idem | idem | Opcode **`0x0D`**, 2 B. El **`short` de la API** se reduce antes de empaquetar: `0→0`, `1→1`, **cualquier otro valor → `2`** (`dsoHTSetYTFormat_10004d00.c`). Único export con `0x0D`; no hay otro `dsoHTSet*` para modo horizontal en el descompilado. |
| `dsoHTSetTriggerSlope` | idem | idem | Opcode **`0x11`**, 2 B. |
| `dsoHTSetTriggerSweep` | idem | idem | Opcode **`0x12`**, 2 B. |
| `dsoHTSetTriggerSource` | idem | idem | Opcode **`0x10`**, 2 B. |
| `dsoHTSetTriggerHPos` | idem | idem | Opcode **`0x0F`**, **3** B (posición horizontal). |
| `dsoHTSetTriggerVPos` | idem | idem | Opcode **`0x14`**, **1** B. |
| `dsoHTSetCHOnOff` | idem | idem | Opcode **`ch*6 + 0`**, 1 B (`ch` = 0/1/…). |
| `dsoHTSetCHCouple` | idem | idem | Opcode **`ch*6 + 1`**, 1 B. |
| `dsoHTSetCHProbe` | idem | idem | Opcode **`ch*6 + 2`**, 1 B. |
| `dsoHTSetCHBWLimit` | idem | idem | Opcode **`ch*6 + 3`**, 1 B. |
| `dsoHTSetCHVolt` | idem | idem | Opcode **`ch*6 + 4`**, 1 B. |
| `dsoHTSetCHPos` | idem | idem | Opcode **`ch*6 + 5`**, 1 B. |
| `dsoHTScopeAutoSet` | `FUN_10004440` sin lectura típica | — | Opcode **`0x13`**, tercer arg **1** → solo escribe. |
| `dsoHTScopeZeroCali` | idem | — | Opcode **`0x17`**, tercer arg **1**. |
| `dsoHTGetSourceData` | **W(10)** trama **`0x55 0x0A … 0x16`** + **muchos R64** | Bucle | Descarga de muestras: el DLL lee **varios** bloques de **64 B** hasta completar el tamaño calculado; cabecera distinta a `FUN_10004440` (ver `FUN_10005010_10005010.c`). |
| `dsoHTGetRealData` | — | — | Orquesta buffers y llama `dsoHTGetSourceData`; mismo patrón de **múltiples 64 B**. |
| `ddsSDKExist` | W(10) | R64 | `00 0A 03 01`, byte 5 = **`0x07`**. |
| `ddsSDKSetOnOff` | W(10) | R64 | Byte 2 = **`2`** (familia DDS), byte 5 = **`0x08`**. |
| `ddsSDKFre` | W(10) | R64 | Byte 2 = **`2`**, byte 5 = **`0x01`**; cuerpo incluye **4 B** de parámetro. |
| `ddsSDKAmp` | W(10) | R64 | Byte 5 = **`0x02`**. |
| `ddsSDKOffset` | W(10) | R64 | Byte 5 = **`0x03`**. |
| `ddsSDKWaveType` | W(10) | R64 | Byte 5 = **`0x00`**. |
| `ddsSDKSquareDuty` | W(10) | R64 | Byte 5 = **`0x04`**. |
| `ddsSDKRampDuty` | W(10) | R64 | Byte 5 = **`0x05`**. |
| `ddsSDKTrapDuty` | W(10) | R64 | Byte 5 = **`0x06`**. |
| `ddsSDKSetOptions` | W(10) | — | Byte 5 = **`0x0D`**; **no** lee en esta función. |
| `ddsSDKDownload` | W(**0x46C**) / W(**0x406**) | — | Carga masiva DDS (bloques grandes; el transporte sigue troceando a 64 B en el driver). En firmware, **0x400** B por slot arb son muestras; el resto es cabecera (ver `HALLAZGOS_DMM_DDS_2026-03.md` § arb). |

---

## Qué esperar en **cada bloque de 64 B** (resumen)

1. **Tras un comando `FUN_10004440` con lectura**  
   - Un solo `read(64)`.  
   - **Validación en DLL:** `buf[3] == opcode`.  
   - Datos útiles: normalmente a partir de **byte 4–8** según ancho 1–4 B del parámetro; el resto puede ser basura o padding.

2. **Tras `dsoHTReadAllSet` (lectura)**  
   - Un `read(64)`; el DLL exige **≥ 10** bytes reportados para seguir; interpreta **21 B** como bloque de configuración.

3. **Tras consultas “familia 3”** (`dsoGetSTMID`, `dsoGetFPGAVersion`, `dsoIsAutomotive`, `ddsSDK*`, etc.)  
   - Un `read(64)`; muchas comprueban **≥ 3** o **≥ 9** bytes devueltos por la API de lectura (no necesariamente “payload lleno”).

4. **`dsoHTGetSourceData` / captura**  
   - **Muchos** `read(64)` consecutivos; el primero puede contener cabecera/estado (`FUN_10005010` comprueba un patrón de bytes iniciales para “not ready” y reintenta).  
   - Los siguientes bloques son **muestras** (interpretación depende de canales, división de tiempo, etc., en `HTSoftDll` / `MeasDll`).

5. **`dsoClearBuffer`**  
   - Solo **un** `read(64)`; propósito: vaciar/drenar buffer del lado firmware/driver según implementación.

6. **Escrituras largas** (`dsoWriteBanner` 30 B, `ddsSDKDownload` 1132/1030 B, `dsoUpdateFPGA` variable)  
   - A nivel USB siguen siendo transferencias; en Windows el DLL las parte en **64 B** internamente (`FUN_10001c60`).

---

## Coherencia con el CLI (`hantek` vía pipx / `hantek_cli.py` / `hantek_usb.cli`)

- Los subcomandos coinciden con filas de esta tabla cuando hay trama fija conocida (`read-settings`, `write-settings`, `stm-id`, `fpga-version`, `run-stop`, DDS, `cmd04440`, `raw`, etc.).
- Consultas `00 0A 03 01` + byte 5: además de los alias (`stm-id`, `arm-version`, …), existe **`query-31 SUB`** para cualquier subcódigo documentado en el `.c` (p. ej. `dsoGetDeviceCali` cuando conozcas el byte).
- **`get-source-data`** / **`get-real-data`**: primer write con cabecera **`0x55 0x0A`**, `opcode 0x16` en byte `[4]`, y dos `ushort` LE en `[5:7]` y `[7:9]`; firmware usa `total = ushort@5 + ushort@7` para enviar muestras en bloques de 64 B.
- **Escrituras largas / variables**: `bulk-send` (hex o `--file`, opcional `--reads`); **`write-banner`** (30 B); **`dds-download --short|--long`** (0x406 / 0x46C B); **`device-sn`** (10 o 37 B + 1×R64); **`write-cali`** (≥5 B, trama completa según DLL).
- **Consultas / utilidades añadidas**: `get-device-cali`, `device-name`, `button-test`, `zero-cali`, `fpga-update` (JSON), `windows-stub-info`; **`--parse`** en lecturas habituales; **`get-source-data` / `get-real-data`** con `--smart`, reintentos y tope de bloques; **`factory-pulse --wait-read`**.
- Para añadir un comando nuevo, localiza la fila aquí, copia los **10 bytes** (o la longitud) del `.c` y el número de **R64** esperados.

Si algo no cuadra en hardware, prioriza el **.c** concreto en `decompiled_hantek/HTHardDll.dll/` sobre esta tabla (el descompilado puede tener offsets ambiguos en structs locales).
