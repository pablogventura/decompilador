#!/usr/bin/env python3
"""
Captura de osciloscopio **después** de ``dsoHTScopeAutoSet`` (``scope-autoset`` en el CLI).

Orden (alineado con uso en pantalla con “autoset”):

1. ``dsoWorkType`` → osciloscopio
2. ``FUN_04440`` opcode **0x13** (scope autoset), sin esperar IN
3. Pausa (el equipo ajusta V/div, time/div, etc.)
4. ``read_all_settings`` + ``scope_run_stop`` RUN + captura **0x16**

Así la lectura USB suele tener **más rango útil** que pedir ``get-real-data`` sin autoset.

Ejemplo:

  python tools/capture_scope_after_autoset.py -o /tmp/cap.bin --bus 1 --address 9
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.capture import smart_source_data_capture
from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE
from hantek_usb.osc_decode import flatten_chunks, split_interleaved_u8, trim_to_expected
from hantek_usb.protocol import Opcodes04440, fun_04440, read_all_settings, scope_run_stop_stm32
from hantek_usb.protocol import work_type_packet
from hantek_usb.transport import HantekLink
from hantek_usb.dds_scope_helpers import tx_wait_ack


def main() -> int:
    p = argparse.ArgumentParser(description="Captura scope tras scope-autoset (0x13).")
    p.add_argument("--bus", type=int, default=None)
    p.add_argument("--address", type=int, default=None)
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x1000)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument("--autoset-sleep", type=float, default=0.6, help="Segundos tras autoset (default 0.6)")
    p.add_argument("--scope-settle", type=float, default=0.25, help="Tras RUN, antes de 0x16 (default 0.25)")
    p.add_argument("--timeout-ms", type=int, default=5000)
    p.add_argument("-o", "--output", required=True, help="Fichero binario: muestras (count_a+count_b bytes)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    link = HantekLink(
        bus=args.bus,
        address=args.address,
        timeout_ms=args.timeout_ms,
    )
    try:
        link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
        pkt_as = fun_04440(Opcodes04440.SCOPE_AUTOSET, 0, 1, False)
        if args.verbose:
            print(">> autoset", pkt_as.hex(), file=sys.stderr)
        link.write(pkt_as)
        time.sleep(max(0.0, args.autoset_sleep))

        _ = tx_wait_ack(link, read_all_settings(), retries=3, sleep_s=0.25)
        link.write(scope_run_stop_stm32(True))
        time.sleep(max(0.0, args.scope_settle))

        def _emit(s: str) -> None:
            if args.verbose:
                print(s, file=sys.stderr)

        chunks = smart_source_data_capture(
            link,
            args.count_a,
            args.count_b,
            blocks_fixed=64,
            smart=True,
            retry_max=80,
            sleep_ms=20,
            max_total_blocks=256,
            verbose=args.verbose,
            emit=_emit,
            hex_fmt=lambda b: b.hex(),
        )
        expected = (int(args.count_a) & 0xFFFF) + (int(args.count_b) & 0xFFFF)
        raw = trim_to_expected(flatten_chunks(chunks), expected)
        out_path = os.path.abspath(args.output)
        with open(out_path, "wb") as f:
            f.write(raw)

        ch1, ch2 = split_interleaved_u8(raw)
        if ch1:
            pp = max(ch1) - min(ch1)
            print(
                f"CH1 u8: min={min(ch1)} max={max(ch1)} pp={pp}  |  "
                f"CH2: min={min(ch2) if ch2 else '-'} max={max(ch2) if ch2 else '-'}  |  "
                f"{len(raw)} B → {out_path}",
                file=sys.stderr,
            )
        print(len(raw))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
