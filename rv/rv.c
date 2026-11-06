/* rv.c: the libc pieces declared in rv.h. */
#include "rv.h"

void *memset(void *d, int c, unsigned n)
{
    u8 *p = d;
    while (n--) *p++ = (u8)c;
    return d;
}

void *memcpy(void *d, const void *s, unsigned n)
{
    u8 *p = d;
    const u8 *q = s;
    while (n--) *p++ = *q++;
    return d;
}

unsigned strlen(const char *s)
{
    unsigned n = 0;
    while (s[n]) n++;
    return n;
}

void puts_(const char *s) { sys_write(1, s, (int)strlen(s)); }

void putu(u32 v)
{
    char buf[12];
    int i = 11;
    buf[i] = 0;
    do {
        buf[--i] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    puts_(buf + i);
}

void puti(int v)
{
    if (v < 0) {
        puts_("-");
        putu((u32)0 - (u32)v);
    } else {
        putu((u32)v);
    }
}

void puthex(u32 v)
{
    char buf[9];
    for (int i = 7; i >= 0; i--) {
        buf[i] = "0123456789abcdef"[v & 15];
        v >>= 4;
    }
    buf[8] = 0;
    puts_(buf);
}
