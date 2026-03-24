# DMM: decodificación según firmware (HantekHTX2021090901)

Este documento resume el **plan A**: trazado de funciones en el binario decompilado que construyen y rellenan la respuesta USB del multímetro (frame típico **14 bytes**: `55 0B … 55`).

## Cadena de datos

1. **`FUN_08027680`**  
   Lee el buffer “crudo” de segmentos / front-end (`DAT_08028154`) y rellena `DAT_08028158`:
   - Signo en `[0]`: `0x2B` (`+`) o `0x2D` (`-`) según el bit MSB de `pbVar2[1]`.
   - Cuatro posiciones de dígito en `[1]…[4]` mediante tablas 7 segmentos: valores `0–9`, `0x4C` (patrón “L”, p. ej. overload en pantalla), `0xFF` (apagado).
   - Posición del punto decimal codificada en `puVar3[6]` (0…3) según bits MSB de `pbVar2[3]`, `[5]`, `[7]`.

2. **`FUN_08031698`**  
   Convierte el estado interno de función `*DAT_080320e0` en el **byte USB `[3]`** (modo que ve el host). La correspondencia **no** es la identidad; ver tabla abajo.

3. **`FUN_0803170c`**  
   Al cambiar el selector físico (`*(DAT_080320e4 + 4)` en `0…10`), fija `*DAT_080320e0` y rutinas de medición (`FUN_08023f14`, `FUN_0802a66c`, etc.).  
   **Propiedad verificable:** para selector `s ∈ {0…10}`, la composición  
   `FUN_08031698(FUN_0803170c(s))` produce **`byte[3] = s`** (el índice de modo USB coincide con la posición del selector en este firmware).

4. **`FUN_0803190a`**  
   Ensambla el paquete de 14 B:
   - `[0]=0x55`, `[1]=0x0B`, `[2]=1`, `[3]=FUN_08031698()`.
   - `[4]`, `[5]`: dos bits derivados de `DAT_0803211c[0]` y `[1]` (tests de signo en MSB).
   - **`[6]`**: subformato de medición:
     - Si el **MSB** de `pbVar2[0xc]` está activo: rama que usa `FUN_0800cd7c` y copia **cuatro bytes** desde `DAT_0803212c` → `[7]…[10]`; `[6] ∈ {1,2,3}` según otro bit de `0xc` y el resultado intermedio.
     - Si no: **`[6]`** se elige por **prioridad fija** sobre bits MSB de `pbVar2[3]`, `[5]`, `[7]` (cada uno fuerza 3, 2 o 1; el último que aplique gana).
     - En la rama alternativa, `[7]…[10]` salen de un buffer formateado en `DAT_08032138` (vía `FUN_08017dcc`).
   - **`[11]`**: código `0…5` por **prioridad fija** sobre bits de `pbVar2[9]` y `pbVar2[10]` (no es el enum de modo LUG).
   - **`[12]`**: código `0…4` por **prioridad fija** sobre bits de `pbVar2[11]` y `pbVar2[12]`.
   - `[13]=0x55`, longitud total `0x0E`.

## Tabla `DAT_080320e0` → `byte[3]` (FUN_08031698)

| Estado interno `e0` | Byte USB `[3]` |
|---------------------|----------------|
| 1 | 1 |
| 2 | 0 |
| 3 | 3 |
| 4 | 2 |
| 5 | 7 |
| 6 | 8 |
| 7 | 9 |
| 8 | 10 |
| 9 | 4 |
| 10 | 5 |
| 11 | 6 |

## Implicación para “valor físico exacto”

- Los bytes **`[7]…[10]` no son un float IEEE** empacado: son **dígitos/símbolos de display** (o buffer intermedio ya convertido) acordes con el LCD.
- El significado físico (V, A, Ω, F, Hz, °C, contaje, diodo) lo da el **modo `[3]`** más el **subformato `[6]`** y las reglas de dígitos/decimales de cada rama —exactamente lo que hace el firmware antes de empaquetar.
- Por eso la lectura “correcta” en software host es: **interpretar dígitos + punto + modo**, no buscar un único escalado flotante universal en el bloque.

## Implementación en este repo

- Tablas y funciones replicables: `hantek_usb/dmm_firmware_map.py`.
- Decodificación del paquete 14 B: `hantek_usb/dmm_decode.py` → `decode_dmm_packet_14`:
  - modo y unidad lógica según `[3]` (A, mA, mV, V, F, Ω, conteos, diodo en V);
  - `[6]=01` + `[12]=02`: continuidad / Ω (incluye OL `FF 00 4C FF`);
  - mismo patrón de dígitos `[6]=02/03` que en DC(V) calibrado, aplicado a todos los modos con dígitos BCD válidos;
  - OL genérico si el patrón aparece con otro `[6]` (p. ej. conteo).
