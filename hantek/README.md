# Hantek 2xx2 — CLI USB (`hantek_usb`)

Herramienta en Python (pyusb + libusb) alineada con `PROTOCOLO_USB.md` y `EXPORTS_HTHardDll.md`.

## Instalación

```bash
cd hantek
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

En Linux hacen falta permisos udev (o root) para `0483:2d42` (por defecto) u otro PID si tu modelo difiere (p. ej. `0483:2d72`).

## Uso

```bash
.venv/bin/python hantek_cli.py list
.venv/bin/python -m hantek_usb read-settings --parse
.venv/bin/python -m hantek_usb factory-pulse --wait-read --parse
.venv/bin/python -m hantek_usb get-real-data --parse --count-a 0x400 --count-b 0
.venv/bin/python -m hantek_usb get-real-data --dump-bin captura.bin --count-a 0x400 --count-b 0
# CSV (por defecto dos canales): index,time_s,ch1_u8,ch2_u8 — ver PROTOCOLO_USB.md §3.3
.venv/bin/python -m hantek_usb get-real-data --parse --export-csv captura.csv --count-a 0x400 --count-b 0
# Un solo flujo u8 (sin separar CH1/CH2): añadí --no-interleaved
# gnuplot dos trazos:  plot 'captura.csv' using 2:3 title 'CH1', '' using 2:4 title 'CH2'
.venv/bin/python -m hantek_usb decode-hex "55 05 00 0c 01"
# Vista en vivo (Tkinter + matplotlib), CH1/CH2 por defecto
.venv/bin/python tools/scope_live_view.py
```

Opcional: `--csv-dt 1e-6` fija el paso de tiempo entre muestras en segundos (`time_s = index * csv-dt`) si conocés el muestreo; si no, el eje X es índice×1 s (solo referencia).

Para **entender** una línea hex que ya copiaste, usa `decode-hex` (sin USB) o los subcomandos con `--parse`.

**Modo** (osciloscopio / multímetro / generador): `set-mode osc|dmm|dds` o `work-type 0|1|2 --write`.

Tras comandos DDS con lectura (`dds-fre`, `dds-amp`, … **sin** `--write-only`), podés usar **`--parse`** para ver la forma del bloque IN (ver `HALLAZGOS_DMM_DDS_2026-03.md`: en 2D42 **no** es un eco fiable del valor escrito).

Regla práctica validada para duty en cuadrada (2D42): `dds-square-duty N` con `N≈duty*100`.
Ejemplo: duty `0.65` -> `dds-square-duty 65`.

Los subcódigos por defecto en `constants.py` (calibración, nombre, botón, zero-cali) son **heurísticos**: confírmalos en el `.c` de `HTHardDll` o con Wireshark.

## Hallazgos recientes (DMM + DDS)

Resumen práctico de descubrimientos validados en hardware real:

- `HALLAZGOS_DMM_DDS_2026-03.md`

## `fpga-update` (JSON)

Ejemplo mínimo (`script.json`):

```json
{
  "steps": [
    { "hex": "000a0300010000000000" },
    { "file": "blobs.bin", "chunk_size": 48, "repeat": 3 }
  ]
}
```

Rutas en `file` son relativas a `base_dir` (carpeta del JSON si no pasas `--base-dir`). Cada `hex` o trozo de `chunk_size` bytes se envía con un `write` USB (troceado a 64 B en el transporte).

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/ -q
```

## Prueba DDS -> OSC (coherencia)

Para validar rápidamente que la captura USB del osciloscopio reacciona a distintos modos del generador:

```bash
.venv/bin/python tools/dds_osc_coherence.py --waves 0,1,2,3 --reps 2 --freq 50 --amp 1200
```

El script marca `CLIPPED` si detecta saturación (por defecto: `min<=5` o `max>=250`).
Para equipos lentos, usa:

```bash
.venv/bin/python tools/dds_osc_coherence.py --waves 0,1,2,3 --reps 1 --slow-profile --exercise-scope-options
```

`--exercise-scope-options` prueba autoset y varios comandos de modo osciloscopio (trigger/canal/time-div) con pausas entre comandos. Para la misma secuencia sin autoajuste (`dsoHTScopeAutoSet` / 0x13), usá `--no-autoset`.

## Barrido de opciones de osciloscopio (DDS fijo)

Con el DDS en una señal conocida (p. ej. seno 50 Hz), **`tools/scope_options_probe.py`** aplica **un opcode distinto por paso** (base de tiempos, V/div CH1, modo de barrido del disparo, etc.), captura `0x16` y muestra **pp**, **cruces respecto de la media** (`xings`, proxy de “cuánto oscila” la ventana) y clipping en el canal elegido. Sirve para correlacionar **valor USB** con **forma de la captura**; los números son **índices firmware**, no V/div ni s/div en unidades SI.

```bash
.venv/bin/python tools/scope_options_probe.py --explain
.venv/bin/python tools/scope_options_probe.py --sweep time-div --values 4,8,12,16
.venv/bin/python tools/scope_options_probe.py --sweep ch1-volt --values 4,7,11
```

Lógica compartida con la prueba de coherencia: `hantek_usb/dds_scope_helpers.py`.

## Autoset por software (sin 0x13)

**`tools/scope_autoset_soft.py`** itera **V/div** (índice firmware) según pp y clipping en CH1/CH2, sin llamar a `SCOPE_AUTOSET`. Opcionalmente ajusta **TIME_DIV** si los cruces por la media salen del rango. Con DDS interno:

```bash
.venv/bin/python tools/scope_autoset_soft.py --wave 2 --freq 50 --amp 1200
```

Solo señal externa (`--no-dds`): ajustá `--volt-min` / `--volt-max` y el canal (`--metrics-ch`).

La **primera captura** no toca V/div (mismo camino que `dds_osc_coherence`); si la señal es casi plana (`pp<8`), el script sale con un aviso. Si el índice V/div en tu equipo reacciona al revés al esperado para “subir ganancia”, probá `--invert-volt-heuristic`.

## Barrido anti-clipping (V/div, sonda, amplitud DDS)

Para buscar combinaciones de `ch-volt`, `ch-probe` y `dds-amp` sin saturar el ADC:

```bash
.venv/bin/python tools/dds_osc_sweep.py --slow-profile --wave 2 --volts 0:11 --probes 0,1 --amps 400,800,1200,2000
```

Al final sugiere una línea de comandos `hantek_cli.py` con los valores que mejor `pp` dieron sin clipping.

Si ninguna combinación evita `min=0`/`max=255`, prueba `--also-rank-margin` para ver qué ajustes dejan **más margen** respecto a los rieles.

## Lectura de osciloscopio (secuencia lenta + análisis)

- Tras una captura, **`--parse --analyze`** en `get-source-data` / `get-real-data` resume saturación y una **calidad heurística** del buffer (basado en rango ADC y patrón «buffer no listo» del firmware en `osc_decode.py`).
- Script opcional con pausas largas, `read-settings`, `time-div`, disparo CH1 y RUN antes del `0x16`:

```bash
.venv/bin/python tools/scope_read_enhanced.py --slow --analyze
.venv/bin/python tools/scope_read_enhanced.py --slow --dds --wave 2 --freq 50 --dds-amp 800 --analyze
```

## Limitaciones

- No reproduce la app oficial ni `HTSoftDll`: medición en pantalla, `dsoGetSampleRate`, etc., no aplican a pyusb (`windows-stub-info`).
- Captura de osciloscopio: se leen **muestras crudas** (bytes ADC) por USB; la escala a voltios/tiempo depende de configuración (`ch-volt`, `ch-probe`, `set-time-div`, etc.) y de lógica de `HTSoftDll`.
- Captura “inteligente” (`--smart`) usa heurísticas de bloques; con firmware actual, conviene pasar `--count-a/--count-b` explícitos (p. ej. `0x400` y `0`).
