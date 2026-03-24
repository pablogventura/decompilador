# Protocolo USB — Hantek 2xx2 (2D42, 2D72, …) a partir de `HTHardDll` descompilado

Este documento resume lo que se deduce de **`decompiled_hantek/HTHardDll.dll`**, del **INF del driver** y de las DLL de ST, para orientar una **herramienta Python (libusb/pyusb)** en Linux/macOS/Windows.

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

---

## 4. Enfoque recomendado para Python (CLI)

### 4.0 Herramienta incluida en este repo

- `hantek/hantek_cli.py` — Entrada fina: delega en el paquete `hantek_usb`.
- `hantek/hantek_usb/` — Código modular: `constants`, `transport` (bulk 64 B), `protocol` (tramas), `cli` (subcomandos). Ejecución: `python -m hantek_usb` o `python -m hantek_usb.cli` desde `hantek/` (misma interfaz que `hantek_cli.py`).
- CLI con **pyusb**: comandos anteriores más `get-device-cali`, `device-name`, `button-test`, `zero-cali`, `fpga-update` (JSON), `windows-stub-info`; **`--parse`** en varias lecturas; captura con **`--smart` / reintentos**; **`factory-pulse --wait-read`**. Ver `hantek/README.md`. Instalación: `pip install -r hantek/requirements.txt`. No sustituye al software del fabricante; sirve como base y para pruebas.
- `hantek/EXPORTS_HTHardDll.md` — **Mapeo export por export** (`dso*` / `dds*`): bytes enviados, cuántos bloques de **64 B** se leen y qué comprueba el DLL en cada respuesta.

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
4. Validar con capturas **USBpcap** / **Wireshark** en Windows con el software oficial y comparar con lo que genera tu script.

### 4.3 Referencias externas

Busca proyectos abiertos tipo **OpenHantek** / drivers para modelos 6022/6xxx: muchos Hantek comparten ideas (aunque el **mapa de comandos puede cambiar** por familia). Tu descompilado de **esta** DLL sigue siendo la fuente más fiable para el **2D42 / 2xx2** concreto.

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
| `dsoHTReadAllSet_10002230.c` | Trama con **`0x15`** (config) |
| `FUN_10004440` | Plantilla genérica de set/get con opcode y hasta 4 B de datos |
| `dsoHTSetRunStop_10004e00.c` | Ejemplo: opcode **`0x0C`** para run/stop |

---

## 6. Limitaciones

- El descompilado **no sustituye** capturar tráfico USB real: los campos aún no descritos requieren **prueba en hardware**.
- En **Linux**, sin el `.sys` de Windows, el camino es **libusb directo**; permisos y **reclamación de interfaz** son el principal fricción operativa, no el análisis estático.

Con esto deberías poder plantear el CLI: **abrir dispositivo → bulk OUT comando 10 B → bulk IN bloques 64 B → interpretar** según vayas completando la tabla de opcodes desde el resto de `dsoHT*`.
