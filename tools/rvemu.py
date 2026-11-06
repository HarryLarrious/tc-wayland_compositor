#!/usr/bin/env python3
"""Reference RV32IM emulator for the programs in rv/.

    python3 tools/rvemu.py build/rv/hello.bin      # run a flat image, print its stdout

It follows the RISC-V spec with Python integers, so it is the yardstick for
the DF interpreter (src/rv.tc): tools/rv2tc.py runs each program here and
stores its output as the expected output of the join tests. The machine is
the runner's: a flat image at address 0, RAM_BYTES of RAM, sp at the top,
and the runner's system calls (rv/rv.h). The Wayland calls are not
emulated here; a program that makes one stops with an error.
"""

from __future__ import annotations

import sys

RAM_BYTES = 40000
MASK = 0xFFFFFFFF


def sx(v: int, bits: int) -> int:
    """Sign-extends the low `bits` bits of v."""
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def signed(v: int) -> int:
    return sx(v, 32)


class Machine:
    def __init__(self, image: bytes):
        if len(image) > RAM_BYTES:
            raise ValueError(f"image is {len(image)} bytes; RAM is {RAM_BYTES}")
        self.mem = bytearray(RAM_BYTES)
        self.mem[: len(image)] = image
        self.x = [0] * 32
        self.x[2] = RAM_BYTES
        self.pc = 0
        self.instret = 0
        self.out = bytearray()
        self.exit_code: int | None = None

    def load(self, addr: int, n: int) -> int:
        if addr < 0 or addr + n > RAM_BYTES:
            raise IndexError(f"load {addr:#x} outside RAM at pc {self.pc:#x}")
        return int.from_bytes(self.mem[addr : addr + n], "little")

    def store(self, addr: int, n: int, v: int) -> None:
        if addr < 0 or addr + n > RAM_BYTES:
            raise IndexError(f"store {addr:#x} outside RAM at pc {self.pc:#x}")
        self.mem[addr : addr + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    def ecall(self) -> None:
        n, a0, a1, a2 = self.x[17], self.x[10], self.x[11], self.x[12]
        if n == 64:
            self.out += self.mem[a1 : a1 + a2]
            self.x[10] = a2
        elif n == 93:
            self.exit_code = signed(a0)
        elif n == 124:
            self.x[10] = 0
        elif n == 4096:
            self.x[10] = 0
        elif n == 4102:
            self.x[10] = self.instret & MASK
        else:
            raise RuntimeError(f"system call {n} is not emulated (pc {self.pc:#x})")

    def step(self) -> None:
        inst = self.load(self.pc, 4)
        op = inst & 0x7F
        rd = (inst >> 7) & 31
        f3 = (inst >> 12) & 7
        rs1 = (inst >> 15) & 31
        rs2 = (inst >> 20) & 31
        f7 = inst >> 25
        a, b = self.x[rs1], self.x[rs2]
        sa, sb = signed(a), signed(b)
        imm_i = sx(inst >> 20, 12)
        nxt = self.pc + 4
        val = None
        if op == 0x37:  # LUI
            val = inst & 0xFFFFF000
        elif op == 0x17:  # AUIPC
            val = self.pc + (inst & 0xFFFFF000)
        elif op == 0x6F:  # JAL
            imm = sx(((inst >> 31) << 20) | (((inst >> 12) & 255) << 12) | (((inst >> 20) & 1) << 11) | (((inst >> 21) & 1023) << 1), 21)
            val, nxt = nxt, self.pc + imm
        elif op == 0x67:  # JALR
            val, nxt = nxt, (a + imm_i) & ~1
        elif op == 0x63:  # branches
            imm = sx(((inst >> 31) << 12) | (((inst >> 7) & 1) << 11) | (((inst >> 25) & 63) << 5) | (((inst >> 8) & 15) << 1), 13)
            take = {0: a == b, 1: a != b, 4: sa < sb, 5: sa >= sb, 6: a < b, 7: a >= b}[f3]
            if take:
                nxt = self.pc + imm
        elif op == 0x03:  # loads
            addr = (a + imm_i) & MASK
            val = {0: lambda: sx(self.load(addr, 1), 8), 1: lambda: sx(self.load(addr, 2), 16),
                   2: lambda: self.load(addr, 4), 4: lambda: self.load(addr, 1),
                   5: lambda: self.load(addr, 2)}[f3]()
        elif op == 0x23:  # stores
            addr = (a + sx(((inst >> 25) << 5) | ((inst >> 7) & 31), 12)) & MASK
            self.store(addr, {0: 1, 1: 2, 2: 4}[f3], b)
        elif op == 0x13:  # ALU immediate
            sh = rs2
            val = {0: lambda: a + imm_i, 2: lambda: int(sa < imm_i), 3: lambda: int(a < (imm_i & MASK)),
                   4: lambda: a ^ imm_i, 6: lambda: a | imm_i, 7: lambda: a & imm_i,
                   1: lambda: a << sh,
                   5: lambda: (sa >> sh) if f7 & 0x20 else (a >> sh)}[f3]()
        elif op == 0x33 and f7 == 1:  # M extension
            if f3 == 0:
                val = sa * sb
            elif f3 == 1:
                val = (sa * sb) >> 32
            elif f3 == 2:
                val = (sa * b) >> 32
            elif f3 == 3:
                val = (a * b) >> 32
            elif f3 == 4:
                # Overflow (-2^31 / -1) gives 2^31, which wraps to -2^31 as the spec says.
                val = -1 if sb == 0 else _tdiv(sa, sb)
            elif f3 == 5:
                val = MASK if b == 0 else a // b
            elif f3 == 6:
                val = sa if sb == 0 else sa - _tdiv(sa, sb) * sb
            else:
                val = a if b == 0 else a % b
        elif op == 0x33:  # ALU register
            sh = b & 31
            val = {(0, 0): lambda: a + b, (0, 0x20): lambda: a - b, (1, 0): lambda: a << sh,
                   (2, 0): lambda: int(sa < sb), (3, 0): lambda: int(a < b), (4, 0): lambda: a ^ b,
                   (5, 0): lambda: a >> sh, (5, 0x20): lambda: sa >> sh, (6, 0): lambda: a | b,
                   (7, 0): lambda: a & b}[(f3, f7)]()
        elif op == 0x0F:  # FENCE
            pass
        elif op == 0x73 and inst == 0x73:  # ECALL
            self.ecall()
        else:
            raise RuntimeError(f"illegal instruction {inst:#010x} at pc {self.pc:#x}")
        if val is not None and rd != 0:
            self.x[rd] = val & MASK
        self.pc = nxt & MASK
        self.instret += 1


def _tdiv(a: int, b: int) -> int:
    """Division rounding toward zero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def run(image: bytes, limit: int = 50_000_000) -> Machine:
    m = Machine(image)
    while m.exit_code is None:
        if m.instret >= limit:
            raise RuntimeError(f"no exit after {limit} instructions")
        m.step()
    return m


def main() -> None:
    m = run(open(sys.argv[1], "rb").read())
    sys.stdout.write(m.out.decode("latin-1"))
    print(f"[exit {m.exit_code}, {m.instret} instructions]", file=sys.stderr)


if __name__ == "__main__":
    main()
