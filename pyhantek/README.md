# Hantek 2xx2 — CLI USB (`hantek_usb`)

Herramienta en Python (pyusb + libusb). Documentación de protocolo, DLL y trabajo de ingeniería inversa está en **[`../dev_docs/`](../dev_docs/)** (no en este directorio). Resumen de rutas útiles:

- **[`../dev_docs/pyhantek/PROTOCOLO_USB.md`](../dev_docs/pyhantek/PROTOCOLO_USB.md)** — protocolo USB
- **[`../dev_docs/hantek/EXPORTS_HTHardDll.md`](../dev_docs/hantek/EXPORTS_HTHardDll.md)** — exports del DLL
- **[`../dev_docs/hantek/MANUAL_FIRMWARE_GAPS.md`](../dev_docs/hantek/MANUAL_FIRMWARE_GAPS.md)** — manual ↔ firmware ↔ USB

El binario PE de referencia suele estar en **`../hantek/HTHardDll.dll`**; pseudocódigo Ghidra en **`../decompiled_hantek/HTHardDll.dll/`** (si existe en tu clon).

## Instalación con pipx (recomendado)

Desde la raíz del repositorio:

```bash
pipx install ./pyhantek
```

Se instala el comando global **`hantek`** (equivalente a `python -m hantek_usb`). Actualizar tras cambios locales:

```bash
pipx install --force ./pyhantek
```

Requisitos de sistema: **libusb-1.0** y, en Linux, reglas **udev** (notas en [`../dev_docs/udev/README.txt`](../dev_docs/udev/README.txt)).

### Entorno virtual (desarrollo)

```bash
cd pyhantek
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

También podés usar `pip install -r requirements.txt` (mismas dependencias runtime que el paquete).

### PID USB vs nombre comercial (2D42 / 2D72 / …)

La CLI **no** usa el nombre del modelo en la carcasa: abre el dispositivo por **VID:PID** (`lsusb` / administrador de Windows). Si el bus muestra **`0483:2d42`**, usá **`--pid 0x2d42`** (default). Si muestra **`0483:2d72`**, usá **`--pid 0x2d72`**. Un aparato vendido como **“2D72”** puede seguir enumerando **2d42** (misma familia / firmware); forzar un PID que **no** está en el bus hace que **no** se conecte.

## Uso

```bash
hantek list
python -m hantek_usb read-settings --parse
python -m hantek_usb factory-pulse --wait-read --parse
python -m hantek_usb get-real-data --parse --count-a 0x400 --count-b 0
python -m hantek_usb get-real-data --dump-bin captura.bin --count-a 0x400 --count-b 0
# CSV (por defecto dos canales): index,time_s,ch1_u8,ch2_u8 — ver dev_docs/pyhantek/PROTOCOLO_USB.md §3.3
python -m hantek_usb get-real-data --parse --export-csv captura.csv --count-a 0x400 --count-b 0
python -m hantek_usb decode-hex "55 05 00 0c 01"
python tools/scope_live_view.py
```

`read-settings --parse` muestra etiquetas empíricas: `ram98_byte3` → **TIME_DIV**; `ram9c_byte3` / `ram9c_byte6` → **flanco** y **modo de barrido** (tablas en **PROTOCOLO_USB** y `hantek_usb/parse_resp.py`).

**Modo** (osciloscopio / multímetro / generador): `set-mode osc|dmm|dds` o `work-type 0|1|2 --write`.

En 2D42, `dds-fre` y `dds-amp` usan por defecto **write puro** (sin lectura IN). Detalles DMM/DDS: [`../dev_docs/pyhantek/HALLAZGOS_DMM_DDS_2026-03.md`](../dev_docs/pyhantek/HALLAZGOS_DMM_DDS_2026-03.md).

Regla práctica para duty en cuadrada (2D42): `dds-square-duty N` con `N≈duty*100`.

Los subcódigos por defecto en `hantek_usb/constants.py` son **heurísticos**: confírmalos en el `.c` de `HTHardDll` y con el CLI en hardware.

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

Rutas en `file` son relativas a `base_dir` (carpeta del JSON si no pasás `--base-dir`).

## Tests

```bash
cd pyhantek
.venv/bin/pytest tests/ -q
```

## Scripts en `tools/`

Ejecutar desde **`pyhantek/`** con el venv activado: `tools/dds_osc_coherence.py`, `tools/scope_options_probe.py`, `tools/scope_label_walk.py`, etc.

Los JSON empíricos (`ch_volt_map_empirico.json`, `time_div_map_empirico.json`, …) están en la raíz de **`pyhantek/`**.

## Limitaciones

- No reproduce la app oficial ni `HTSoftDll`: medición en pantalla, `dsoGetSampleRate`, etc., no aplican a pyusb (`windows-stub-info`).
- Captura de osciloscopio: muestras crudas por USB; la escala a voltios/tiempo depende de la configuración del equipo y de lógica no replicada aquí.
