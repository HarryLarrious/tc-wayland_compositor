/* isa: checks the instruction set against a reference. It runs every
 * RV32IM ALU, load and store instruction on awkward values (signs,
 * overflow, division by zero, shifts by 31) and prints a checksum per
 * group. tools/rv2tc.py gets the expected output from tools/rvemu.py. */
#include "rv.h"

#define R3(name)                                                         \
    static u32 name(u32 a, u32 b)                                        \
    {                                                                    \
        u32 r;                                                           \
        __asm__ volatile(#name " %0, %1, %2" : "=r"(r) : "r"(a), "r"(b)); \
        return r;                                                        \
    }
R3(add) R3(sub) R3(sll) R3(slt) R3(sltu) R3(xor) R3(srl) R3(sra) R3(or) R3(and)
R3(mul) R3(mulh) R3(mulhsu) R3(mulhu) R3(div) R3(divu) R3(rem) R3(remu)

typedef u32 (*op_fn)(u32, u32);

static const u32 vals[] = {0, 1, 2, 3, 7, 31, 32, 255, 0x7fff, 0x8000, 0xffff, 0x12345678,
                           0x7fffffff, 0x80000000, 0x80000001, 0xfffffffe, 0xffffffff,
                           0xdeadbeef, 0x00010000, 0xcafe0001, (u32)-7, (u32)-3000};
#define NV (sizeof vals / sizeof vals[0])

static u32 mix(u32 h, u32 v) { return (h ^ v) * 0x01000193u + 0x9e3779b9u; }

static u32 group(op_fn f)
{
    u32 h = 0x811c9dc5u;
    for (unsigned i = 0; i < NV; i++)
        for (unsigned j = 0; j < NV; j++) h = mix(h, f(vals[i], vals[j]));
    return h;
}

static void line(const char *name, u32 h)
{
    puts_(name);
    puts_(" ");
    puthex(h);
    puts_("\n");
}

static volatile u32 word;

int main(void)
{
    static const struct { const char *name; op_fn f; } ops[] = {
        {"add", add}, {"sub", sub}, {"sll", sll}, {"slt", slt}, {"sltu", sltu},
        {"xor", xor}, {"srl", srl}, {"sra", sra}, {"or", or}, {"and", and},
        {"mul", mul}, {"mulh", mulh}, {"mulhsu", mulhsu}, {"mulhu", mulhu},
        {"div", div}, {"divu", divu}, {"rem", rem}, {"remu", remu},
    };
    for (unsigned k = 0; k < sizeof ops / sizeof ops[0]; k++) line(ops[k].name, group(ops[k].f));

    /* Immediates, branches and sub-word loads and stores. */
    u32 h = 0x811c9dc5u;
    for (unsigned i = 0; i < NV; i++) {
        volatile u32 v = vals[i];
        h = mix(h, v + 2047);
        h = mix(h, v << 31);
        h = mix(h, (u32)((int)v >> 31));
        h = mix(h, (int)v < -5);
        h = mix(h, v < 9u);
        h = mix(h, v ^ 0xfffff800u);
        word = 0x11223344;
        volatile u8 *b = (volatile u8 *)&word;
        volatile u16 *s = (volatile u16 *)&word;
        b[i & 3] = (u8)v;
        s[(i >> 1) & 1] = (u16)(v >> 3);
        h = mix(h, word);
        h = mix(h, (u32)(int)(signed char)b[(i + 1) & 3]);
        h = mix(h, b[(i + 2) & 3]);
        h = mix(h, (u32)(int)(short)s[i & 1]);
        h = mix(h, s[(i + 1) & 1]);
    }
    line("mem", h);
    return 0;
}
