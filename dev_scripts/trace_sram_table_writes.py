#!/usr/bin/env python3
"""
Rastreo estático (Capstone): LDR (literal PC) que cargan punteros de tabla en SRAM
y STR posteriores con el mismo registro base (posible escritura en la tabla).

Uso:
  python3 dev_scripts/trace_sram_table_writes.py
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone import arm

BASE = 0x08005000
TARGETS = {
    0x20001BFC: "uint32[] A (pool fee4)",
    0x20001B74: "uint32[] B (pool fee8)",
    0x20001CA8: "bytes[] A (fed8)",
    0x20001C84: "bytes[] B (fedc)",
}


def thumb_ldr_literal_addr(insn_addr: int, disp: int) -> int:
    pc = (insn_addr + 4) & ~3
    return pc + disp


def reg_name(md: Cs, n: int) -> str:
    try:
        return md.reg_name(n)
    except Exception:
        return f"r{n}"


def str_mem_base(ins) -> int | None:
    """Registro base de un str/strb/strh/str.w hacia memoria."""
    m = ins.mnemonic.lower()
    if not m.startswith("str"):
        return None
    for op in ins.operands:
        if op.type == arm.ARM_OP_MEM and op.mem.base != 0:
            return op.mem.base
    return None


def disasm_one(md: Cs, payload: bytes, addr: int):
    off = addr - BASE
    if off < 0 or off >= len(payload):
        return None
    for ins in md.disasm(payload[off : off + 4], addr):
        return ins
    return None


def scan_ldr_loads(md: Cs, payload: bytes) -> list[tuple[int, int, int, str]]:
    """Lista (instr_addr, reg_dst, valor_cargado, etiqueta)."""
    out: list[tuple[int, int, int, str]] = []
    addr = BASE
    while addr < BASE + len(payload) - 4:
        ins = disasm_one(md, payload, addr)
        if ins is None:
            addr += 2
            continue
        if ins.mnemonic.lower() not in ("ldr", "ldr.w"):
            addr += ins.size
            continue
        # LDR Rt, [PC, #imm]
        pc_disp = None
        dst_reg = None
        for op in ins.operands:
            if op.type == arm.ARM_OP_REG and dst_reg is None:
                dst_reg = op.reg
            if op.type == arm.ARM_OP_MEM and op.mem.base == arm.ARM_REG_PC:
                pc_disp = op.mem.disp
        if pc_disp is None or dst_reg is None:
            addr += ins.size
            continue
        lit_addr = thumb_ldr_literal_addr(ins.address, pc_disp)
        lo = lit_addr - BASE
        if lo < 0 or lo + 4 > len(payload):
            addr += ins.size
            continue
        val = struct.unpack_from("<I", payload, lo)[0]
        if val in TARGETS:
            out.append((ins.address, dst_reg, val, TARGETS[val]))
        addr += ins.size
    return out


def trace_str_after(
    md: Cs, payload: bytes, ldr_addr: int, base_reg: int, max_insns: int = 500
) -> list[tuple[int, str, str]]:
    """
    Busca STR cuyo registro base sea `base_reg` o un registro al que se haya
    movido el mismo puntero (mov/movs) desde base_reg.
    """
    hits: list[tuple[int, str, str]] = []
    table_regs: set[int] = {base_reg}
    addr = ldr_addr
    n = 0
    while n < max_insns and addr < BASE + len(payload):
        ins = disasm_one(md, payload, addr)
        if ins is None:
            addr += 2
            continue
        m = ins.mnemonic.lower()
        # mov / movs / mov.w Rd, Rm
        if m in ("mov", "movs", "mov.w") and len(ins.operands) >= 2:
            d0 = ins.operands[0]
            d1 = ins.operands[1]
            if d0.type == arm.ARM_OP_REG and d1.type == arm.ARM_OP_REG:
                if d1.reg in table_regs:
                    table_regs.add(d0.reg)
        # LDR que sobrescribe un registro "tabla" (salvo LDR literal PC que es otro tema)
        if m.startswith("ldr") and "pc" not in ins.op_str.lower():
            for op in ins.operands:
                if op.type == arm.ARM_OP_REG:
                    if op.reg in table_regs:
                        table_regs.discard(op.reg)
                    break
        br = str_mem_base(ins)
        if br is not None and br in table_regs:
            hits.append((ins.address, m, ins.op_str))
        if m == "bx" and "lr" in ins.op_str:
            break
        if m == "pop" and "pc" in ins.op_str:
            break
        addr += ins.size
        n += 1
    return hits


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "bin",
        nargs="?",
        default=str(root / "firmware" / "HantekHTX2021090901.bin"),
        type=Path,
    )
    args = ap.parse_args()
    if not args.bin.is_file():
        print(f"error: no existe {args.bin}", file=sys.stderr)
        sys.exit(1)

    payload = args.bin.read_bytes()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True

    print(f"BIN: {args.bin} ({len(payload)} bytes)\n")
    sites = scan_ldr_loads(md, payload)
    print("=== LDR [PC] que cargan punteros conocidos ===\n")
    for vma, reg, val, lab in sorted(sites, key=lambda x: (x[2], x[0])):
        print(f"  {vma:#010x}  {reg_name(md, reg)} <- {val:#010x}  {lab}")

    print("\n=== STR con ese registro como base (hasta bx lr / pop pc) ===\n")
    done: set[tuple[int, int]] = set()
    for vma, reg, val, lab in sites:
        key = (vma, reg)
        if key in done:
            continue
        done.add(key)
        hits = trace_str_after(md, payload, vma, reg)
        if not hits:
            print(f"  {vma:#010x} {reg_name(md, reg)} ({lab}): (sin STR)\n")
            continue
        print(f"  {vma:#010x} {reg_name(md, reg)} ({lab}):")
        for ha, hm, hop in hits:
            print(f"      {ha:#010x}  {hm:8} {hop}")
        print()


if __name__ == "__main__":
    main()
