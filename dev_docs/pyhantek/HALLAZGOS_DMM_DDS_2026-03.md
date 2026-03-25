# Hallazgos prácticos DMM + DDS (2026-03)

Registro de descubrimientos validados con hardware real Hantek 2D42, usando la CLI de este repo.

## Alcance

- Equipo: Hantek 2D42.
- Comando de lectura DMM: `dsoGetDMMData` (`00 05 01 01`), con respuestas observadas de 14 bytes.
- Modo generador: `dsoWorkType = 2` (DDS).

## DMM: formato de 14 bytes observado

Trazado de funciones del firmware (mapeo modo, bytes `[6]`/`[11]`/`[12]`, pipeline de dígitos LCD): ver **`DMM_FIRMWARE_DECODIFICACION.md`**.

Trama base:

```text
55 0B ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? 55
```

### Caso voltaje DC (validado)

Subformatos observados:

- `[6] = 0x02`: formato principal (0..99.99 V).
- `[6] = 0x03`: subformato de rango bajo (casos concretos validados).

Reglas validadas para `[6] = 0x02`:

- Si `[7] == 0`: `V = [8] + ([9]*10 + [10]) / 100`
- Si `[7] >= 1`: `V = ([7]*10 + [8]) + ([9]*10 + [10]) / 100`

Ejemplos validados:

- `... 02 00 04 09 09 ...` -> 4.99 V
- `... 02 00 05 00 00 ...` -> 5.00 V
- `... 02 01 02 03 04 ...` -> 12.34 V

Para `[6] = 0x03`, se validaron estos patrones:

- `... 03 00 00 00 00 ...` -> 0.00 V
- `... 03 00 09 09 08 ...` -> 1.00 V (empírico, fórmula general pendiente)
- `... 03 02 05 00 00 ...` -> 2.50 V
- `... 03 03 03 03 01 ...` -> 3.33 V

### Caso continuidad / ohms (validado)

Firma observada:

- `[6] = 0x01` y `[12] = 0x02`

Patrones validados:

- Abierto (pantalla `OL`): `[7:10] = FF 00 4C FF` (0x4C = 'L')
- Corto con pitido y pantalla `000.5`: `[7:10] = 00 00 00 05`

Regla actual usada para caso numérico en continuidad:

- `R(ohm) = (([7]*100 + [8]*10 + [9]) / 1000) + ([10] / 10)`

Ejemplo:

- `00 00 00 05` -> 0.5000 ohm

## Comandos útiles de la CLI

Lectura humana DMM:

```bash
python hantek_cli.py dmm-read --parse --ensure-dmm --sample-delay-ms 80
```

Listar modos DMM:

```bash
python hantek_cli.py dmm-modes
```

## DDS: tipos de onda confirmados

Mapeo validado de `dds-wave N`:

- `0` square
- `1` triangular
- `2` sine
- `3` trapezoid
- `4` arb1
- `5` arb2
- `6` arb3
- `7` arb4

Listar desde la CLI:

```bash
python hantek_cli.py dds-waves
```

Configurar seno 440 Hz:

```bash
python hantek_cli.py set-mode dds
python hantek_cli.py dds-wave 2 --write-only
python hantek_cli.py dds-fre 440 --write-only
python hantek_cli.py dds-offset 0 --write-only
python hantek_cli.py dds-amp 1000 --write-only
python hantek_cli.py dds-onoff --on --write-only
```

Calibración observada en pantalla:

- `dds-amp 1000` -> 1.00 V (equipo del usuario, configuración actual)

### Duty (ciclo de trabajo)

En onda **cuadrada**, el *duty* es la fracción del período en nivel alto.

- En la pantalla del 2D42 suele mostrarse como **decimal 0.00–1.00** (ej. **0.50** = **50%** alto / 50% bajo).
- Eso **no** es el mismo parámetro que `dds-amp` ni `dds-offset`.

El comando CLI es `dds-square-duty <uint32>`; la escala exacta del valor enviado frente al LCD **no está resuelta** en este repo (hace falta correlación hex + pantalla o el `.c` del DLL).

Actualización validada en hardware (2026-03):

- En cuadrada, el LCD parece usar **el byte bajo** del `uint32`:
  - `duty_display ~= (value & 0xFF) / 100`
- Evidencia empírica:
  - `value=0x0027AA20` (`2600000`) -> `0.64` (0x40/100)
  - `value=0x0027D130` (`2610000`) -> `0.80` (0x50/100)
  - `value=0x0027AC14` (`2600500`) -> `0.52` (0x34/100)
  - `value=65` (`0x41`) -> `0.65` (confirmado)

Recomendación práctica:

- Para fijar duty `D` en rango `0.00..2.55`, enviar `value = int(round(D * 100))`.
- Ejemplo: `0.65` -> `65`.

### Trapecio (`trapezoid`, índice `3`)

En la pantalla del equipo, la onda trapecio suele permitir **tres** ajustes de *duty* (porcentaje o fracción del período asignada a cada tramo):

- **rise duty** (subida),
- **high duty** (meseta alta),
- **fall duty** (bajada).

En **HTHardDll** aparecen **`ddsSDKRampDuty`** (subcódigo **0x05**) y **`ddsSDKTrapDuty`** (**0x06**) como envíos de 10 B con “un parámetro”; el DLL empaqueta un `uint32` en bytes 5–8. Eso **no** basta para el trapecio de tres sliders.

En el **firmware** del instrumento (`FUN_080326b8`), el subcódigo **0x06** se interpreta con **tres bytes independientes** en el payload: `+5`, `+6`, `+7` (cada uno pasa por la misma cadena de conversión que el duty de un solo byte). Orden coherente con la UI: **rise / high / fall**.

**Validado en hardware (2D42):** un solo envío con bytes `10`, `20`, `30` en `[5:8]` del opcode **0x06** dejó en pantalla **0.10 / 0.20 / 0.30** en rise / high / fall (misma regla práctica que la cuadrada: `entero ≈ duty_LCD × 100`).

CLI: `dds-trapezoid-duty RISE HIGH FALL` (tres `uint8`, p. ej. `dds-trapezoid-duty 10 20 30`). El comando `dds-trap-duty` (un solo `uint32`) solo rellena el byte bajo del valor como primer byte del trapecio; para los tres parámetros usar `dds-trapezoid-duty`.

**Ramp (0x05):** sigue siendo un solo byte efectivo en el mismo handler (`+5`); útil para rampa/triángulo; no sustituye al trapecio de tres bytes.

### Arb1–arb4 (índices `4`–`7`)

No hay “parámetros enteros” aparte para dar forma a cada arb: el **contenido** de la onda es una **tabla de muestras**.

**Firmware (`FUN_080326b8`):** con byte de suborden **`[4] == 0x07`** y **`[5]` ∈ {1,2,3,4}**, el firmware acumula datos hasta tener **`0x400` bytes** y llama `FUN_0801c9a4(slot, 0x400, …)` con **slot 1…4** → **arb1…arb4**. Esas **`0x400` bytes** son **512 muestras × 16 bits** (little-endian por pares de bytes en el buffer intermedio).

**PC / CLI:** `ddsSDKDownload` envía **una** escritura bulk de **`0x406`** o **`0x46C`** bytes (`dds-download --short` / `--long`). Por aritmética:

- `0x406 = 0x400 + 6` → **6 bytes** de cabecera + **1024 B** de muestras.
- `0x46C = 0x400 + 0x6C` → **108 bytes** de cabecera + **1024 B** de muestras.

El **layout exacto** de la cabecera (magic, índice de slot, CRC, etc.) **no está** en este repo; hace falta ingeniería inversa del `HTHardDll` / firmware y pruebas con `dds-download` (sin depender de captura USB en el PC).

En código Python, `hantek_usb.protocol.build_dds_download_blob` arma el tamaño correcto (**6 + 0x400** o **0x6C + 0x400**) con cabecera reemplazable (por defecto ceros) y bloque de muestras; `dds_arb_samples_int16_le` empaqueta **512×int16 LE**.

**Rama larga (`0x46C`, `dds_download_long_chunked_blob`):** el DLL rellena **18×64 B** (cabecera **6 B** + **29×int16** por bloque) y `FUN_10002060` envía solo **0x46C** bytes en total (**17×64 + 44**). Los **últimos 44 B** del wire son cabecera del bloque 18 + **19×int16** — es decir las muestras con índice **493…511**; los **últimos 20 B** del bloque 18 **no** se transmiten. `dds_long_chunked_blob_to_samples` invierte ese layout para tests.

**Float → int16 como Scope/DLL:** `ddsSDKDownload` usa `float*` y `__ftol` + saturación a **±0x7FFF** (signo del float si hace falta). En Python: `dll_float_to_int16` y `float_samples_to_dds_int16` en `hantek_usb.protocol`; [`../../pyhantek/tools/gen_arb1_waveform.py`](../../pyhantek/tools/gen_arb1_waveform.py) usa ese pipeline por defecto en presets **sine** y **chirp** (`--no-dll-float-pipeline` para el truncado entero antiguo).

**Escala de la tabla vs vista del AWG:** la pantalla suele dibujar la forma en el rango **±32767** (o normalizado a todo el alto). Si la tabla solo usa **p. ej. ±2800**, la onda **se ve achatada** en el propio gráfico del generador aunque el USB sea correcto. Para “llenar” la vista previa, usar **`--peak 32767`** en `gen_arb1_waveform.py` (valor por defecto). La tensión de salida sigue gobernada por **`dds-amp`**.

**Discontinuidad vertical al repetir el buffer:** si la forma es **periódica** y las fases usan `2π·i/N` con **i=0..N−1**, el último punto **no** coincide con el primero al hacer **wrap** 511→0 ⇒ **salto** cada período (muy visible en seno). En `gen_arb1_waveform` el seno/chirp usan **`fase ∝ i/(N−1)`** para que **muestra 0** y **muestra N−1** cierren el mismo ángulo (p. ej. `sin(0)` y `sin(2π)` en ciclo entero).

**Tramos “planos” o escalera en arb (esperable, no es bug de carga):** la tabla tiene solo **512** puntos por período; el hardware suele **mantener** cada valor hasta la siguiente muestra (**retención de orden cero, ZOH**). Entre punto y punto la salida es **constante** → en el dibujo se ven **segmentos horizontales** (escalera). Con **`--peak` alto** esos tramos ocupan **más píxeles en vertical** y la curva parece “con mesetas”. Además, **tabla casi a ±32767** más **`dds-amp` alto** puede **recortar** en la cadena analógica: la **cresta** del seno se ve **plana** (saturación). Prueba: bajar **`dds-amp`**, o generar con **`--peak 28000`**–**30000** para dejar margen, o subir **`dds-fre`** (misma forma en menos tiempo ⇒ tramos horizontales más cortos en segundos).

**Seno interno vs arb1:** el modo tabla (**arb**) puede verse más “escalonado” o distinto del **seno interno** (`dds-wave` índice 2) porque la síntesis por hardware no tiene por qué ser la misma (p. ej. **512 puntos** en ZOH frente a otra ruta DDS). Una **baja correlación** entre capturas no demuestra por sí sola un error de carga si el blob coincide con el del DLL.

**Prueba de referencia (opcional):** con el software oficial en Windows, generar una arb equivalente y comparar el **bulk OUT** byte a byte con un `.bin` producido por `gen_arb1_waveform.py` (misma `dds-amp` / slot). Si el payload de muestras coincide y la salida sigue distinta, el desvío está en escala analógica o en la cadena DDS, no en el empaquetado USB.

**Secuencia tipo Scope / `verify_arb_sine_scope.py`:** antes de cargar la tabla conviene poner el equipo en **modo generador** (`set-mode dds` o `work-type 2 --write`). Orden de referencia: **modo DDS** → **`dds-download`** (bulk) → **`dds-wave` 4…7** (arb) → **`dds-fre`** / **`dds-amp`** → **`dds-onoff --on`**. Si solo se envía `dds-download` + `dds-wave` estando en **osciloscopio** o **multímetro**, la salida puede verse **rota** o **cortada**; no es un fallo del `.bin` en sí.

**App Windows “this model has not awg” con el mismo hardware:** el mensaje **no** viene del Python del repo; suele ser el **Scope.exe** + **`ddsSDKExist`** / estado interno. Las tramas que usamos (`set-mode`, `dds-*`, `dds-download`) **no** están documentadas aquí como cambio de **PID** o “modelo” permanente; lo más plausible es **RAM**/**flags** incoherentes tras muchos cambios de modo o un **bug** de la app. Prueba: **apagar** el Hantek **varios segundos**, **cerrar y reabrir** el software en PC, **no** usar `--pid` distinto en la CLI. Evitar **`write-settings --tail`** y **`factory-pulse`** salvo saber qué hacen. Si tras **cold boot** el mensaje sigue, comparar **`read-settings --parse`** con una captura guardada cuando todo iba bien.

**Cambiar AWG ↔ osciloscopio en el mismo aparato:** se ha observado que la forma **se ve bien** en la pantalla del generador y **después** de pasar a **modo osciloscopio** (y a veces al **volver** al AWG) la onda **vuelve a verse cortada** o como **antes de corregir** el cierre de período. Eso puede ser **estado interno** / **vista** al cambiar de modo, no el fichero en el PC. **Workaround:** al regresar al generador, **volver a ejecutar** la secuencia completa (`set-mode dds` → `dds-download` → `dds-wave` → `dds-fre` / `dds-amp` → `dds-onoff --on`). Para medir sin tantos cambios de modo, conviene **osciloscopio externo** en la salida del AWG.

**Uso práctico:** cargar el fichero generado/capturado del software oficial con `dds-download --short|--long --file …`, luego `dds-wave 4`…`7` para seleccionar arb1…arb4. Frecuencia, amplitud y offset siguen siendo `dds-fre` / `dds-amp` / `dds-offset` como en cualquier onda.

### Respuesta IN tras comandos DDS (~10 B)

Patrón frecuente observado:

```text
55 07 02 SS xx xx xx xx 55
```

Donde `SS` parece un subcódigo y los 4 bytes siguientes un `uint32` LE.

**Importante:** en pruebas con 2D42, ese bloque **no** se comportó como un “eco” fiable:

- Tras distintos `dds-amp` / `dds-offset` / `dds-fre`, el `u32` en `[4:8]` **puede repetirse** o **no coincidir** con el valor enviado en el TX.
- Tras `dds-onoff`, el byte `[3]` de la respuesta **puede no** coincidir con el subcomando `SET_ONOFF (0x08)`.

Conclusión práctica: **usar la pantalla del equipo o medición física** para validar amplitud/frecuencia/offset; la IN no es hoy un registro de estado confiable.

La CLI puede mostrar una interpretación estructural con:

```bash
python hantek_cli.py dds-fre 440 --parse
python hantek_cli.py dds-amp 1000 --parse
```

### Offset: discrepancia USB vs LCD (observado 2026-03)

En el firmware (`FUN_080326b8`), el subcomando DDS `0x03` (offset) usa:

- **`[5:6]`**: magnitud `uint16` little-endian.
- **`[7]`**: signo (`0` positivo/cero, `1` negativo).

No coincide con una interpretación de `u32` plano en `[5:8]`.

Al enviar `dds-offset N` **con lectura** (`sin --write-only`), el bloque IN devuelto puede ser **corto (~10 B)** y **repetir el mismo patrón** (`… 88 13 00 00 …`) **independientemente** de `N` en pruebas locales.

Eso implica:

1. **No uses** la línea hex de respuesta del comando como “eco” fiable del offset escrito.
2. El **LCD puede seguir mostrando `0.00 V` de offset** aunque el protocolo acepte el paquete: el firmware puede mapear el offset a otro registro, ignorarlo en cierto rango, o la UI no estar enlazada al mismo campo que la trama USB.
3. Para comprobar si el offset **afecta la salida real**, lo más directo es **medir con multímetro / osciloscopio** el nivel DC medio de la salida DDS (no solo mirar el LCD).

Recomendación operativa:

- Preferí `dds-offset` **sin** `--write-only` si querés el camino “DLL-like” (escritura + lectura IN).
- Si necesitás offset visible en pantalla y el USB no lo refleja, medir salida AWG con DMM/scope y seguir RE del DLL/firmware; **no** asumir captura Wireshark/usbmon en el host.

## Osciloscopio: buffer entrelazado (validado)

En captura `0x16` con **dos canales activos**, el stream de bytes USB encaja con **CH1, CH2, CH1, CH2…** (un byte ADC por canal e instante). Tratar el buffer como una sola secuencia `u8` mezcla ambos canales.

En este repo, `hantek_usb.osc_decode.split_interleaved_u8` y el **CSV por defecto** (`index,time_s,ch1_u8,ch2_u8`) asumen ese layout. Para un flujo crudo sin separar canales (depuración), usar **`--no-interleaved`** en `get-source-data` / `get-real-data`. Detalle en [`PROTOCOLO_USB.md`](PROTOCOLO_USB.md) §3.3.

## Notas de validez

- El valor de `[11]` aparece en múltiples modos y no siempre identifica directamente la magnitud física.
- En continuidad/ohms no se deben usar heurísticas float/int32 genéricas.
- Estos hallazgos son empíricos y están en evolución; si cambian con otro firmware/modelo, guardar nuevas capturas hex + pantalla.

## Pendientes (checklist viva)

Lista canónica y casillas **\[ \]** para no olvidar trabajo futuro: **[`../hantek/MANUAL_FIRMWARE_GAPS.md`](../hantek/MANUAL_FIRMWARE_GAPS.md) §8 — DMM y AWG/DDS**. Allí están: matriz de modos DMM, formato `0x03`, `dmm-modes`/tipos, hold/rango, eco IN DDS, offset, cabecera `dds-download`, arbs, stubs DLL, rampa.
