#!/usr/bin/env python3
"""A model of the DF RISC-V interpreter (src/rv.tc) under DF's number rules.

    python3 tools/rvdf.py              # run every console program, compare with tools/rvemu.py

Deploying takes minutes; this takes seconds. It follows rv.tc op by op
(the same decode lists and the same arithmetic) but with DF's rules,
measured in game:
  * bitwise operators work on 64-bit integers: << doesn't wrap at 32 bits;
    & | ^ ~ >> are exact on any value (Python's are too);
  * >>> is wrong for negative numbers, so rv.tc never uses it;
  * % rounds toward zero (the remainder takes the dividend's sign);
  * numbers are 64-bit fixed point: rv.tc only divides exactly.
If rv.tc changes, change this to match.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rvemu  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAM_WORDS = 10000
I32 = 4294967296


def mod(a: int, b: int) -> int:
    """DF %: rounds toward zero."""
    return int(math.fmod(a, b))


def wrap(v: int) -> int:
    r = mod(v, I32)
    if r < 0:
        r += I32
    if r >= 2147483648:
        r -= I32
    return r


def u(v: int) -> int:
    return v + I32 if v < 0 else v


def check64(v: int) -> int:
    assert -(2**63) <= v < 2**63, v
    return v


class DFMachine:
    def __init__(self, image: bytes):
        words = [int.from_bytes(image[i : i + 4], "little") for i in range(0, len(image), 4)]
        words = [w - I32 if w >= 2147483648 else w for w in words]
        n = len(words)
        self.m = [0] + words + [0] * (RAM_WORDS - n)  # index 1-based
        self.x = [0] * 34
        self.x[3] = RAM_WORDS * 4
        self.op = [0] * (n + 1)
        self.rd = [0] * (n + 1)
        self.ra = [0] * (n + 1)
        self.rb = [0] * (n + 1)
        self.im = [0] * (n + 1)
        for i in range(1, n + 1):
            self.decode(i)
        self.pc = 1
        self.out = bytearray()
        self.exit = None
        self.instret = 0

    def decode(self, i: int) -> None:
        inst = self.m[i]
        opc = inst & 127
        rd = (inst >> 7) & 31
        f3 = (inst >> 12) & 7
        rs1 = (inst >> 15) & 31
        rs2 = (inst >> 20) & 31
        f7 = (inst >> 25) & 127
        imm = inst >> 20
        op = 48
        if opc == 0x13:
            op = [1, 10, 30, 31, 32, 11, 33, 13][f3]
            if f3 in (1, 5):
                imm = rs2
                if f3 == 5 and f7 == 32:
                    op = 12
                elif rs2 == 0:
                    op = 1
                elif f3 == 1:
                    rs2 = (1 << (32 - imm)) - 2
        elif opc == 0x03:
            op = [34, 35, 2, 48, 18, 36, 48, 48][f3]
        elif opc == 0x23:
            op = [19, 37, 3, 48, 48, 48, 48, 48][f3]
            imm = ((inst >> 25) << 5) | rd
        elif opc == 0x33:
            if f7 == 1:
                op = 38 + f3
            elif f7 == 0:
                op = [4, 25, 28, 29, 24, 26, 22, 23][f3]
            elif f7 == 32 and f3 == 0:
                op = 20
            elif f7 == 32 and f3 == 5:
                op = 27
        elif opc == 0x63:
            op = [6, 5, 48, 48, 14, 15, 16, 17][f3]
            b = ((inst >> 31) << 12) | (((inst >> 7) & 1) << 11) | (((inst >> 25) & 63) << 5) | (((inst >> 8) & 15) << 1)
            imm = i + b // 4
        elif opc == 0x6F:
            op = 7
            j = ((inst >> 31) << 20) | (((inst >> 12) & 255) << 12) | (((inst >> 20) & 1) << 11) | (((inst >> 21) & 1023) << 1)
            imm = i + j // 4
        elif opc == 0x37:
            op = 8
            imm = inst & -4096
        elif opc == 0x17:
            op = 21
            imm = wrap((i - 1) * 4 + (inst & -4096))
        elif opc == 0x67:
            op = 9
        elif opc == 0x0F:
            op = 47
        elif opc == 0x73 and inst == 0x73:
            op = 46
        if rd == 0:
            rd = 32
        self.op[i], self.rd[i], self.ra[i], self.rb[i], self.im[i] = op, rd + 1, rs1 + 1, rs2 + 1, imm

    def step(self) -> None:
        pc, x, m = self.pc, self.x, self.m
        op = self.op[pc]
        A = x[self.ra[pc]]
        B = x[self.rb[pc]] if op != 10 else 0
        im = self.im[pc]
        rd = self.rd[pc]
        nxt = pc + 1
        if op in (1, 4, 20):
            v = A + (im if op == 1 else B if op == 4 else -B)
            if v > 2147483647:
                v -= I32
            elif v < -2147483648:
                v += I32
            x[rd] = v
        elif op in (2, 3, 18, 19, 34, 35, 36, 37):
            ad = A + im
            assert 0 <= ad < RAM_WORDS * 4, (pc, ad)
            wi = (ad >> 2) + 1
            w = m[wi]
            sh = (ad & 3) << 3
            if op == 2:
                x[rd] = w
            elif op == 3:
                m[wi] = B
            elif op == 18:
                x[rd] = (w >> sh) & 255
            elif op == 19:
                v = ((w & 4294967295) & ~(255 << sh)) | ((B & 255) << sh)
                m[wi] = v - I32 if v > 2147483647 else v
            elif op == 34:
                v = (w >> sh) & 255
                x[rd] = v - 256 if v > 127 else v
            elif op == 35:
                v = (w >> sh) & 65535
                x[rd] = v - 65536 if v > 32767 else v
            elif op == 36:
                x[rd] = (w >> sh) & 65535
            else:
                v = ((w & 4294967295) & ~(65535 << sh)) | ((B & 65535) << sh)
                m[wi] = v - I32 if v > 2147483647 else v
        elif op in (5, 6, 14, 15, 16, 17):
            take = {5: A != B, 6: A == B, 14: A < B, 15: A >= B,
                    16: (A ^ -2147483648) < (B ^ -2147483648), 17: (A ^ -2147483648) >= (B ^ -2147483648)}[op]
            if take:
                nxt = im
        elif op == 7:
            x[rd] = pc * 4
            nxt = im
        elif op in (8, 21):
            x[rd] = im
        elif op == 9:
            nxt = ((A + im) >> 2) + 1
            x[rd] = pc * 4
        elif op == 10:
            v = check64((A & self.rb[pc]) << im)
            x[rd] = v - I32 if v > 2147483647 else v
        elif op == 11:
            v = A + I32 if A < 0 else A
            x[rd] = v >> im
        elif op == 12:
            x[rd] = A >> im
        elif op == 13:
            x[rd] = A & im
        elif 22 <= op <= 33:
            v = 0
            if op == 22:
                v = A | B
            elif op == 23:
                v = A & B
            elif op == 24:
                v = A ^ B
            elif op == 25:
                sh = B & 31
                v = check64((A & ((1 << (32 - sh)) - 1)) << sh)
                if v > 2147483647:
                    v -= I32
            elif op == 26:
                sh = B & 31
                v = A
                if sh > 0:
                    if v < 0:
                        v += I32
                    v = v >> sh
            elif op == 27:
                v = A >> (B & 31)
            elif op == 28:
                v = int(A < B)
            elif op == 29:
                v = int((A ^ -2147483648) < (B ^ -2147483648))
            elif op == 30:
                v = int(A < im)
            elif op == 31:
                v = int((A ^ -2147483648) < (im ^ -2147483648))
            elif op == 32:
                v = A ^ im
            else:
                v = A | im
            x[rd] = v
        elif 38 <= op <= 45:
            x[rd] = muldiv(op, A, B)
        elif op == 46:
            self.syscall()
        elif op == 47:
            pass
        else:
            raise RuntimeError(f"illegal at word {pc}")
        x[33] = 0  # the sink: never read
        assert all(-2147483648 <= r <= 2147483647 for r in x), (pc, op, x)
        self.pc = nxt
        self.instret += 1

    def syscall(self) -> None:
        x = self.x
        n, a0, a1, a2 = x[18], x[11], x[12], x[13]
        ret = 0
        if n == 64:
            for i in range(a2):
                ad = a1 + i
                self.out.append((self.m[(ad >> 2) + 1] >> ((ad & 3) << 3)) & 255)
            ret = a2
        elif n == 93:
            self.exit = a0
        elif n == 124 or n == 4096:
            ret = 0
        elif n == 4102:
            ret = wrap(self.instret)
        else:
            raise RuntimeError(f"system call {n}")
        x[11] = ret


def mulhiu(ua: int, ub: int) -> int:
    al = mod(ua, 65536)
    ah = (ua - al) // 65536
    bl = mod(ub, 65536)
    bh = (ub - bl) // 65536
    low = al * bl
    mid = ah * bl + al * bh + (low - mod(low, 65536)) // 65536
    return ah * bh + (mid - mod(mid, 65536)) // 65536


def muldiv(op: int, a: int, b: int) -> int:
    ua, ub = u(a), u(b)
    if op == 38:
        al = mod(ua, 65536)
        ah = (ua - al) // 65536
        bl = mod(ub, 65536)
        bh = (ub - bl) // 65536
        return wrap(al * bl + mod(ah * bl + al * bh, 65536) * 65536)
    if op <= 41:
        hi = mulhiu(ua, ub)
        if op != 41 and a < 0:
            hi -= ub
        if op == 39 and b < 0:
            hi -= ua
        return wrap(hi)
    if op in (43, 45):
        if ub == 0:
            return -1 if op == 43 else a
        r = mod(ua, ub)
        return wrap((ua - r) // ub) if op == 43 else wrap(r)
    if b == 0:
        return -1 if op == 42 else a
    ma, mb = abs(a), abs(b)
    r = mod(ma, mb)
    q = (ma - r) // mb
    if op == 42:
        if (a < 0) != (b < 0):
            q = -q
        return wrap(q)
    return -r if a < 0 else r


def main() -> None:
    ok = True
    for name in ["hello", "bench", "isa"]:
        image = (ROOT / "build" / "rv" / f"{name}.bin").read_bytes()
        image += b"\0" * (-len(image) % 4)
        want = rvemu.run(image).out
        dm = DFMachine(image)
        while dm.exit is None:
            dm.step()
        got = bytes(dm.out)
        same = got == want or name == "bench" and got.split(b"\n")[0] == want.split(b"\n")[0]
        ok &= same
        print(f"{name}: {'same' if same else 'DIFFERENT'} ({dm.instret} instructions)")
        if not same:
            for g, w in zip(got.decode().splitlines(), want.decode().splitlines()):
                if g != w:
                    print(f"  got {g!r}, want {w!r}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
