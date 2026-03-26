# Checklist de implementación (2D42) — trazabilidad

Referencia viva derivada de [`../hantek/MANUAL_FIRMWARE_GAPS.md`](../hantek/MANUAL_FIRMWARE_GAPS.md) §2 y §8, y del plan *CLI Hantek profesional*.  
**Metodología:** primero evidencia en [`../../firmware/decompilado/`](../../firmware/decompilado/) y DLL ([`../hantek/EXPORTS_HTHardDll.md`](../hantek/EXPORTS_HTHardDll.md), pseudocódigo en repo); si no alcanza, comando de sonda en CLI + confirmación en pantalla/medición; resultado → [`PROTOCOLO_USB.md`](PROTOCOLO_USB.md), tests en [`../../pyhantek/tests/`](../../pyhantek/tests/) o este archivo.

**Política (proyecto):** no basar el flujo de trabajo en **captura USB en el PC** (p. ej. usbmon, Wireshark, app oficial solo en Windows). Para huecos de trama, usar **RE de firmware/DLL**, experimentos **solo con CLI/pyusb**, y **diff de `read-settings`** / [`../../pyhantek/tools/compare_read_settings.py`](../../pyhantek/tools/compare_read_settings.py) / [`../../pyhantek/tools/snapshot_scope_state.py`](../../pyhantek/tools/snapshot_scope_state.py) tras cambios hechos en el **panel del instrumento**.

**Lazos de validación:** el 2D42/2D72 tiene **scope + DMM + AWG** en el mismo aparato; conviene pedir al usuario **conexiones en lazo** (p. ej. AWG→CH1, AWG→DMM) y contrastar **valores medidos por USB** (`get-source-data`, `dmm-read --parse`) con **valores que el propio CLI fija** (`dds-fre`, `dds-amp`, etc.), además del LCD cuando aplique.

Leyenda columnas:

| Columna | Significado |
|--------|-------------|
| **Decomp / docs** | Archivo o símbolo que sustenta la hipótesis |
| **Código / CLI** | Módulo o subcomando |
| **Test** | Test automático o “manual documentado” |
| **Hardware** | Qué debe ver/confirmar el usuario en 2D42 |

---

## A. Osciloscopio y disparo (§2 MANUAL_FIRMWARE_GAPS)

| Ítem | Decomp / docs | Código / CLI | Test | Hardware |
|------|----------------|--------------|------|----------|
| Autoset vs botón Auto | `FUN_10004440` + opcode `0x13` | `scope-autoset` | prueba manual / criterio en doc | Señal conocida (p. ej. DDS), comparar resultado |
| Humo CH1 señal externa | `0x16` + `read-settings` | [`../../pyhantek/tools/external_ch1_smoke.py`](../../pyhantek/tools/external_ch1_smoke.py) / `external-ch1-smoke` | `pytest tests/test_scope_signal_metrics.py` | Gen. externo → CH1; `--scope-autoset` → JSON `settings_autoset_diff`; `--expect-hz` |
| Y-T / Roll / Scan escritura | `FUN_08031a9e`, `PROTOCOLO` §3.4.1–3.4.2 | `set-yt-format`, `read-settings --parse` | — | Anotar modo LCD tras ordenes |
| Invert canal escritura | `0x18` (experimental) | `ch-invert 0` | no operativo | **Trigger inestable**; falta RE firmware/DLL o diff estado |
| V/div índices 10–11 | `ch_volt_map_empirico.json` | `ch-volt`, `scope_label_walk.py` | JSON / walk | CH1, repetir barrido |
| Pulse width trigger | `HTHardDll` edge vs PW | — | — | ¿Solo UI? |
| Force trigger | ≠ `0x17` (calibración) | — | — | Trama USB desconocida; UX 2D42: Normal+Force ≈ free-run; **Single** más cercano a “una captura” — [`../tools/PROCEDIMIENTO_force_trigger.txt`](../tools/PROCEDIMIENTO_force_trigger.txt) |
| Opcode USB `0x18` | `FUN_08031a9e` rama `0x18` | — | — | Identificar y opcional CLI experimental |

---

## A2. Herramientas de estado (diff sin capturar el bus en PC)

| Ítem | Código | Uso |
|------|--------|-----|
| Diff **read-settings** campo a campo | [`../../pyhantek/tools/compare_read_settings.py`](../../pyhantek/tools/compare_read_settings.py) | Dos capturas `.txt` o hex → qué bytes del payload 21 B cambiaron (invert, menú, Force trigger, …) |
| Snapshot JSON | [`../../pyhantek/tools/snapshot_scope_state.py`](../../pyhantek/tools/snapshot_scope_state.py) | `-o estado.json` antes/después de una acción **solo en el panel**; luego diff de `fields_u8` o hex (sin usbmon/Wireshark) |
| Diff **dos JSON** de snapshot | [`../../pyhantek/tools/compare_scope_snapshots.py`](../../pyhantek/tools/compare_scope_snapshots.py) | `compare_scope_snapshots.py a.json b.json` → mismas claves que `fields_u8` |

---

## B. DMM (§8)

| Ítem | Decomp / docs | Código / CLI | Test | Hardware |
|------|----------------|--------------|------|----------|
| Matriz modo ↔ hex 14 B | `DMM_FIRMWARE_DECODIFICACION.md` | `dmm_decode.py`, `dmm-read --parse` | `test_parse_and_protocol.py` (vectores) | Todos los rangos manual |
| Subformato `[6]==0x03` | Hallazgos empíricos | `_decode_volt_fmt03` | tests hex | Cerrar fórmula general |
| `dmm-type` / `DMM_TYPE_FROM_BYTE` | strings 11040… | `dmm-modes`, `dmm-type` | — | Confirmar índices 0..10 |
| Hold / auto-range | — | `dmm-read` | — | ¿Cambian bytes fijos? |

---

## C. AWG / DDS (§8)

| Ítem | Decomp / docs | Código / CLI | Test | Hardware |
|------|----------------|--------------|------|----------|
| Eco IN tras `dds-*` | `HALLAZGOS_DMM_DDS_2026-03.md` | `dds-* --parse` | — | No fiarse del eco; validar LCD/medición |
| `dds-offset` | mismo | `dds-offset` | — | DC en salida vs LCD |
| Cabecera `dds-download` | `ddsSDKDownload`, `FUN_080326b8` | `dds-download`; `build_dds_download_blob` / `dds_arb_samples_int16_le` en `protocol.py` | tests tamaño + muestras | Layout cabecera exacto: captura DLL |
| Arb1–4 | firmware slot + 0x400 B | `dds-wave`, `dds-download --file` | — | — |
| Stubs burst/fase | DLL | — | — | Opcional |
| Rampa / triángulo `0x05` | `FUN_080326b8` | `dds-square-duty`, ramp | — | LCD |

---

## D. DLL “avanzadas” (§5) — riesgo

**Política:** primero **solo decompilado** (tabla riesgo en comentarios o doc); **no** ejecutar en 2D42 salvo decisión explícita.

| Ítem | Decomp / docs | Código / CLI | Test | Hardware |
|------|----------------|--------------|------|----------|
| zero-cali, factory, fpga-update, … | [`../hantek/EXPORTS_HTHardDll.md`](../hantek/EXPORTS_HTHardDll.md) | comandos existentes | — | Solo si hace falta |

---

## E. Scope.exe / HTSoftDll (Fase 7)

**Prerrequisito:** DLL y descompilados en el repo.

| Ítem | Decomp / docs | Código / CLI | Test | Hardware |
|------|----------------|--------------|------|----------|
| Medidas / cursores / REF / `.hantek` | HTSoftDll, MeasDll, … | futuro subpaquete | — | Según API |

---

## Resultados en vivo (2D42)

- 2026-03-25 — `doctor`: USB OK (`0483:2d42`), `ARM=2021090901`, FPGA respuesta corta `0x07`.
- 2026-03-25 — `set-yt-format 0/1/2` + `read-settings`: sin cambio estable de estado por USB; en pantalla se observó cambio de trazo.
- 2026-03-25 — `scope-autoset`: reescalado visible confirmado por usuario y cambios en `read-settings` (time/div y otros campos).
- 2026-03-25 — DMM `dmm-read --parse` (modo DC V, puntas al aire): paquete 14 B con `[6]=0x03`, `[7:10]=00 00 00 00`, LCD en `~0.00 V`.
- 2026-03-25 — DMM `dmm-read --parse` (modo DC V, fuente laboratorio 2.5 V): paquete 14 B `55 0b 01 05 01 00 03 02 05 00 03 05 01 55`, LCD en `~2.50 V` (nuevo patrón `[6]=0x03`, `[7:10]=02 05 00 03`).
- 2026-03-25 — DMM `dmm-read --parse` (modo DC V, fuente laboratorio 1.0 V): paquete 14 B `55 0b 01 05 01 00 03 01 00 00 00 05 01 55`, LCD en `~1.00 V` (nuevo patrón `[6]=0x03`, `[7:10]=01 00 00 00`).
- 2026-03-25 — DMM `dmm-read --parse` (modo DC V, fuente laboratorio 5.0 V): paquete 14 B `55 0b 01 05 01 00 02 00 05 00 00 05 01 55`, LCD en `~5.00 V`; usa **`[6]=0x02`** (formato principal ya documentado en `HALLAZGOS_DMM_DDS_2026-03.md`, test `test_decode_dmm_packet_14_capturas`).
- 2026-03-25 — DMM `dmm-read --parse` (modo DC V, fuente ~12.34 V): paquete 14 B `55 0b 01 05 01 00 02 01 02 03 05 05 01 55`, LCD en `~12.35 V` (redondeo/display); `dmm_decode` → **12.35 V** (`[6]=0x02`, entero `12` + dec `35`).
- 2026-03-25 — DMM continuidad (`dmm-type 9`): abierto → trama `... ff 00 4c ff ...`, LCD **OL**; corto estable → `55 0b 01 09 00 00 01 00 00 00 02 05 02 55`, decode **~0.2 Ω**, LCD valor bajo similar en dos lecturas.
- 2026-03-25 — DDS `dds-offset` (modo generador): `dds-offset 0` → IN `u32=0`, LCD offset **~0.00 V**; `dds-offset 500` y `dds-offset 1000` → IN sigue `u32=0`, **LCD offset sigue ~0.00 V** (coherente con `HALLAZGOS_DMM_DDS_2026-03.md`: no fiarse del eco IN; validar salida real con DMM/osciloscopio si hace falta).
- 2026-03-25 — DDS **frecuencia/amplitud:** en 2D42 la ruta con `byte[3]=1` (lectura) **no aplicaba** cambios en LCD; con **`byte[3]=0`** (write puro, `raw` o CLI actualizado) sí. Tras cambiar el CLI: `dds-fre 1500` + `dds-amp 1200` → LCD **~1,5 kHz** y **~1,20 V** (validado por usuario). `dds-offset` sigue sin moverse en LCD con las pruebas hechas.
- 2026-03-25 — DMM **AC(V)** (`dmm-type 6`): trama 14 B `55 0b 01 06 02 00 03 02 08 09 03 05 01 55`, LCD **~0 V** (sin señal); `dmm_decode` patrón empírico `02 08 09 03` → **0 V** (`test_decode_dmm_packet_14_acv_near_zero`).
- 2026-03-25 — DMM **AC(V)** red: trama `55 0b 01 06 02 00 01 02 02 07 07 05 01 55`, LCD **~227 V**; decode **227,7 V** con `[6]=0x01` y fórmula `[7]*100+[8]*10+[9]+[10]/10` (`test_decode_dmm_packet_14_acv_mains`).
- 2026-03-25 — DMM **diodo** (`dmm-type 10`): trama `55 0b 01 0a 00 00 03 00 06 09 02 05 01 55`, LCD **~0,697 V**; decode **0,692 V** con `([8]*100+[9]*10+[10])/1000` en `[6]=0x03` (`test_decode_dmm_packet_14_diode_forward`).
- 2026-03-25 — DMM **diodo OL** (puntas al aire): `55 0b 01 0a 00 00 03 ff 00 4c ff 05 01 55` — patrón `FF 00 4C FF` en `[7:10]`; `dmm_decode` OL + `circuito_abierto` + nota diodo (`test_decode_dmm_packet_14_diode_ol`).
- 2026-03-25 — DMM **capacidad** (`dmm-type 7`): sin capacitor `55 0b 01 07 00 00 03 00 00 00 00 00 03 55` → **0 F** (`test_decode_dmm_packet_14_capacitance_zero`).
- 2026-03-25 — **DDS arb + scope (lazo):** `build_dds_download_blob` (seno 512 pts) + `dds-download --short` OK; `dds-wave 4`, `dds-fre`/`dds-amp`/`dds-onoff --on`; `set-mode osc` + `get-source-data` → muestras ADC no planas (validación burda AWG→CH1 por USB en esta sesión).
- 2026-03-25 — DMM **capacidad ~1 µF**: `55 0b 01 07 00 00 03 00 09 03 01 01 03 55` → **931 nF** (`nF=[7]*1000+…+[10]`, `F=nF·1e-9`); coherente con cap nominal 1 µF y tolerancia (`test_decode_dmm_packet_14_capacitance_1uf_nominal`).
- 2026-03-25 — **`external_ch1_smoke.py`** en 2D42 (`0483:2d42`): tras fijar scope por USB (TIME_DIV inicial 16, trig Auto, `tx_wait_ack` en time/trigger), captura `0x400` B, `pp≈41`, `mean_crossings=6`, `freq_hz_est≈1500` Hz con `ram98_byte3=14` (200 µs/div); salida **OK** (exit 0). `f_est` es heurística (10 divs × time/div); usar `--expect-hz` solo si el generador está en frecuencia conocida.
- 2026-03-25 — **`external_ch1_smoke.py --scope-autoset`** (2D42, señal en CH1): comando `python tools/external_ch1_smoke.py --scope-autoset --timeout-ms 8000 --autoset-wait-s 2` → **exit 0**; captura `0x400` B, `pp≈42`, `mean_crossings≈3`, `freq_hz_est≈750` Hz, `ram98_byte3=14`; JSON/capa diff: **`settings_autoset_diff` con 0 entradas** (ningún byte de `fields_u8` cambió entre lecturas antes/después del opcode `0x13` en ese estado). Si el timeout default (5 s) falla, subir `--timeout-ms` / `--autoset-wait-s`.

---

## Comandos útiles de diagnóstico

- `cd pyhantek && python hantek_cli.py doctor` — abre USB, endpoints, `read-settings --parse`, STM/FPGA/ARM en una pasada.
- `cd pyhantek && python hantek_cli.py list` — enumerar dispositivos.
- `cd pyhantek && python tools/compare_read_settings.py captures/A.txt captures/B.txt` — diff campo a campo del payload 0x15.
- `cd pyhantek && python tools/snapshot_scope_state.py -o captures/x.json --note "antes Force"` — JSON para comparar estados.
- `cd pyhantek && python tools/compare_scope_snapshots.py a.json b.json` — diff entre dos snapshots.
- `cd pyhantek && python tools/external_ch1_smoke.py --json` — humo con señal en CH1 (gen. externo); ver [`INDICE.md`](../INDICE.md) § flujos.
- Ver [`PROTOCOLO_USB.md`](PROTOCOLO_USB.md) §6.1 (advertencias DMM/DDS).
