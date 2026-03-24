#!/usr/bin/env python3
"""
Vista en vivo de la captura del osciloscopio (ADC u8) en una ventana Tkinter + matplotlib.

Con dos canales, el firmware entrega muestras **entrelazadas** (CH1, CH2, CH1, CH2…).
Por defecto se decodifica y se dibujan **dos trazos** (ver ``--decode``; ``interleaved`` es el default).

Por defecto intenta el máximo ritmo que permita el USB (sin pausa entre capturas;
reintentos cortos). El límite real son los ~N lecturas 64 B por frame + matplotlib.

Requisitos: pyusb, matplotlib (ver requirements.txt en hantek/).

Ejemplos:
  cd hantek && .venv/bin/python tools/scope_live_view.py
  .venv/bin/python tools/scope_live_view.py --count-a 0x200
  .venv/bin/python tools/scope_live_view.py --safe-capture
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time

# Añadir raíz del paquete al path si se ejecuta como script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hantek_usb.capture import smart_source_data_capture
from hantek_usb.constants import WORK_TYPE_OSCILLOSCOPE
from hantek_usb.osc_decode import flatten_chunks, split_interleaved_u8, trim_to_expected
from hantek_usb.protocol import (
    Opcodes04440,
    fun_04440,
    read_all_settings,
    scope_run_stop_stm32,
    work_type_packet,
)
from hantek_usb.transport import HantekLink


def _put_latest(q: "queue.Queue[bytes]", payload: bytes) -> None:
    """Mantén solo el último frame si la GUI va lenta."""
    try:
        q.put_nowait(payload)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def _scope_init(
    link: HantekLink,
    *,
    slow: bool,
    time_div: int,
) -> None:
    """Modo osciloscopio, ajustes básicos y RUN (misma idea que scope_read_enhanced)."""
    pre = 1.2 if slow else 0.35
    post = 0.6 if slow else 0.12
    link.write(work_type_packet(WORK_TYPE_OSCILLOSCOPE, read=False))
    time.sleep(pre)
    link.write(read_all_settings())
    link.read64()
    link.write(fun_04440(Opcodes04440.TIME_DIV, time_div & 0xFFFF, 2, True))
    link.read64()
    time.sleep(0.2 if slow else 0.08)
    link.write(fun_04440(Opcodes04440.TRIGGER_SOURCE, 0, 2, True))
    link.read64()
    time.sleep(0.2 if slow else 0.08)
    link.write(fun_04440(Opcodes04440.TRIGGER_SWEEP, 0, 2, True))
    link.read64()
    time.sleep(0.2 if slow else 0.08)
    link.write(scope_run_stop_stm32(True))
    time.sleep(0.15 if slow else 0.08)
    time.sleep(post)


def _capture_worker(
    *,
    vid: int,
    pid: int,
    bus: int | None,
    address: int | None,
    timeout_ms: int,
    count_a: int,
    count_b: int,
    interval_s: float,
    init_scope: bool,
    slow: bool,
    time_div: int,
    clear_in: bool,
    retry_max: int,
    sleep_ms: int,
    stop: threading.Event,
    out_q: "queue.Queue[bytes | BaseException]",
    status_q: "queue.Queue[tuple[str, str]]",
) -> None:
    link: HantekLink | None = None
    try:
        link = HantekLink(
            vid=vid,
            pid=pid,
            bus=bus,
            address=address,
            timeout_ms=timeout_ms,
        )
        if init_scope:
            status_q.put(("info", "Inicializando osciloscopio…"))
            _scope_init(link, slow=slow, time_div=time_div)
            status_q.put(("ok", "Listo — capturando"))
        else:
            status_q.put(("ok", "Capturando (sin init USB; modo OSC ya configurado)"))

        def emit(_s: str) -> None:
            return

        expected = (int(count_a) & 0xFFFF) + (int(count_b) & 0xFFFF)

        while not stop.is_set():
            if clear_in:
                try:
                    link.read64()
                except OSError:
                    pass
            chunks = smart_source_data_capture(
                link,
                count_a,
                count_b,
                blocks_fixed=64,
                smart=True,
                retry_max=retry_max,
                sleep_ms=sleep_ms,
                max_total_blocks=256,
                verbose=False,
                emit=emit,
                hex_fmt=lambda b: b.hex(),
            )
            payload = trim_to_expected(flatten_chunks(chunks), expected)
            _put_latest(out_q, payload)
            stop.wait(interval_s)
    except BaseException as e:
        out_q.put(e)
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:
                pass


def main() -> int:
    from hantek_usb import constants

    p = argparse.ArgumentParser(description="Vista en vivo ADC (Tkinter + matplotlib)")
    p.add_argument("--vid", type=lambda x: int(x, 0), default=constants.VID_HANTEK_2XX2)
    p.add_argument("--pid", type=lambda x: int(x, 0), default=constants.DEFAULT_PID_HANTEK)
    p.add_argument("--bus", type=int, default=None)
    p.add_argument("--address", type=int, default=None)
    p.add_argument("--timeout", type=int, default=1500, metavar="MS", help="USB por lectura (ms); bajar acelera fallos")
    p.add_argument("--count-a", type=lambda x: int(x, 0), default=0x400)
    p.add_argument("--count-b", type=lambda x: int(x, 0), default=0)
    p.add_argument(
        "--interval-ms",
        type=float,
        default=0.0,
        help="Pausa extra tras cada captura (0 = en bucle tan rápido como permita USB; default 0)",
    )
    p.add_argument(
        "--safe-capture",
        action="store_true",
        help="Reintentos más lentos si el buffer a veces sale vacío (menos fps, más fiable)",
    )
    p.add_argument(
        "--retry-max",
        type=int,
        default=None,
        metavar="N",
        help="Reintentos 1.er bloque si «no listo» (default: 8 rápido / 40 con --safe-capture)",
    )
    p.add_argument(
        "--retry-sleep-ms",
        type=int,
        default=None,
        metavar="MS",
        help="Pausa entre reintentos (default: 3 ms rápido / 20 ms con --safe-capture)",
    )
    p.add_argument(
        "--poll-ms",
        type=int,
        default=8,
        metavar="MS",
        help="Frecuencia con la que la ventana mira nuevos frames (default 8 ≈ 125 Hz)",
    )
    p.add_argument(
        "--no-init-scope",
        action="store_true",
        help="No enviar modo OSC / time-div / RUN (el equipo ya en marcha)",
    )
    p.add_argument("--slow", action="store_true", help="Tiempos de espera largos al iniciar")
    p.add_argument("--time-div", type=int, default=8, help="Valor ushort p. dsoHTSetTimeDiv")
    p.add_argument(
        "--clear-in",
        action="store_true",
        help="Drenar un bloque IN antes de cada captura (a veces estabiliza)",
    )
    p.add_argument(
        "--decode",
        choices=("raw", "interleaved"),
        default="interleaved",
        help="interleaved=CH1/CH2 por bytes pares/impares (default, validado en 2xx2); raw=stream único",
    )
    args = p.parse_args()

    if args.safe_capture:
        rm = 40 if args.slow else 28
        sm = 20 if args.slow else 15
    else:
        rm = 12 if args.slow else 8
        sm = 6 if args.slow else 3
    if args.retry_max is not None:
        rm = args.retry_max
    if args.retry_sleep_ms is not None:
        sm = args.retry_sleep_ms

    interval_s = max(0.0, args.interval_ms / 1000.0)

    try:
        import tkinter as tk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
    except ImportError as e:
        print("Falta matplotlib o Tk. Instalá: pip install matplotlib", file=sys.stderr)
        print(e, file=sys.stderr)
        return 1

    frame_q: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)
    status_q: queue.Queue[tuple[str, str]] = queue.Queue()

    stop = threading.Event()

    worker = threading.Thread(
        target=_capture_worker,
        kwargs=dict(
            vid=args.vid,
            pid=args.pid,
            bus=args.bus,
            address=args.address,
            timeout_ms=args.timeout,
            count_a=args.count_a,
            count_b=args.count_b,
            interval_s=interval_s,
            init_scope=not args.no_init_scope,
            slow=args.slow,
            time_div=args.time_div,
            clear_in=args.clear_in,
            retry_max=rm,
            sleep_ms=sm,
            stop=stop,
            out_q=frame_q,
            status_q=status_q,
        ),
        daemon=True,
    )

    root = tk.Tk()
    root.title("Hantek OSC — vista en vivo (ADC u8)")
    root.minsize(640, 400)

    poll_ms = max(1, int(args.poll_ms))

    fig = Figure(figsize=(9, 4.5), dpi=90)
    ax = fig.add_subplot(111)
    if args.decode == "interleaved":
        line_ch0, = ax.plot([], [], lw=0.8, color="C0", label="CH1 (bytes pares)")
        line_ch1, = ax.plot([], [], lw=0.8, color="C1", label="CH2 (bytes impares)")
        plot_lines = (line_ch0, line_ch1)
        ax.legend(loc="upper right", fontsize=8)
    else:
        line0, = ax.plot([], [], lw=0.8, color="C0")
        plot_lines = (line0,)
    ax.set_xlabel("Muestra (por canal)")
    ax.set_ylabel("ADC (0–255)")
    ax.set_ylim(-5, 260)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    status_var = tk.StringVar(value="Conectando…")
    lbl = tk.Label(root, textvariable=status_var, anchor="w", justify=tk.LEFT)
    lbl.pack(side=tk.BOTTOM, fill=tk.X)

    btn_frame = tk.Frame(root)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
    running = {"on": True}

    def stop_capture() -> None:
        running["on"] = False
        stop.set()
        status_var.set("Deteniendo…")

    tk.Button(btn_frame, text="Salir", command=lambda: (stop_capture(), root.after(400, root.destroy))).pack(
        side=tk.RIGHT, padx=4, pady=4
    )

    t0 = time.perf_counter()
    n_frames = [0]

    def poll() -> None:
        while True:
            try:
                kind, msg = status_q.get_nowait()
                if kind == "ok":
                    status_var.set(msg)
                else:
                    status_var.set(msg)
            except queue.Empty:
                break

        try:
            item = frame_q.get_nowait()
        except queue.Empty:
            root.after(poll_ms, poll)
            return

        if isinstance(item, BaseException):
            status_var.set(f"Error: {item!r}")
            running["on"] = False
            return

        ya: list[int] | None = None
        yb: list[int] | None = None
        if args.decode == "interleaved":
            ya, yb = split_interleaved_u8(item)
            if not ya and not yb:
                root.after(poll_ms, poll)
                return
            plot_lines[0].set_data(range(len(ya)), ya)
            plot_lines[1].set_data(range(len(yb)), yb)
            n = max(len(ya), len(yb))
            lows = [x for x in (min(ya) if ya else None, min(yb) if yb else None) if x is not None]
            his = [x for x in (max(ya) if ya else None, max(yb) if yb else None) if x is not None]
            lo, hi = min(lows), max(his)
        else:
            y = list(item)
            n = len(y)
            if n == 0:
                root.after(poll_ms, poll)
                return
            plot_lines[0].set_data(range(n), y)
            lo, hi = min(y), max(y)
        ax.set_xlim(0, max(1, n - 1))
        pad = max(4, (hi - lo) // 8)
        ax.set_ylim(lo - pad, hi + pad)
        canvas.draw_idle()
        n_frames[0] += 1
        elapsed = time.perf_counter() - t0
        fps = n_frames[0] / elapsed if elapsed > 0 else 0
        if args.decode == "interleaved" and ya is not None and yb is not None:
            status_var.set(
                f"CH1 n={len(ya)} [{min(ya) if ya else '-'}..{max(ya) if ya else '-'}]  "
                f"CH2 n={len(yb)} [{min(yb) if yb else '-'}..{max(yb) if yb else '-'}]  "
                f"~{fps:.1f} fps  |  hipótesis entrelazado"
            )
        else:
            status_var.set(
                f"Muestras: {n}  |  min={lo}  max={hi}  |  ~{fps:.1f} fps  |  ADC crudo (sin V)"
            )
        if running["on"]:
            root.after(poll_ms, poll)

    worker.start()
    root.after(16, poll)

    def on_close() -> None:
        stop_capture()
        root.after(300, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    stop.set()
    worker.join(timeout=3.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
