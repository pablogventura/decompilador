#!/usr/bin/env python3
"""
Grafica CH1 de dos capturas binarias (4096 B, entrelazado CH1/CH2 como ``get-real-data``).

  python tools/plot_scope_ch1_compare.py /tmp/cap_internal_sine.bin /tmp/cap_arb_sine.bin -o /tmp/fig.png
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = argparse.ArgumentParser()
    p.add_argument("capture_a", help="Binario 4096 B (primera traza, CH1)")
    p.add_argument("capture_b", help="Binario 4096 B (segunda traza, CH1)")
    p.add_argument("-o", "--output", default="scope_ch1_compare.png", help="PNG de salida")
    p.add_argument("--title-a", default="CH1 — A")
    p.add_argument("--title-b", default="CH1 — B")
    args = p.parse_args()

    def ch1(path: str) -> list[int]:
        raw = open(path, "rb").read()[:4096]
        return list(raw[0::2])

    y1 = ch1(args.capture_a)
    y2 = ch1(args.capture_b)
    x = range(len(y1))

    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    axes[0].plot(x, y1, color="#1f77b4", lw=0.8)
    axes[0].set_title(args.title_a)
    axes[0].set_ylabel("u8")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(x, y2, color="#d62728", lw=0.8)
    axes[1].set_title(args.title_b)
    axes[1].set_xlabel("muestra CH1")
    axes[1].set_ylabel("u8")
    axes[1].grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.output, dpi=150)
    print(args.output, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
