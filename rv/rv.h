/* rv.h: the system calls of the DF RISC-V runner (src/rv.tc) and a few
 * libc pieces. Programs are freestanding RV32IM: no OS, no libc. */
#ifndef RV_H
#define RV_H

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

/* System call numbers (a7). 64 and 93 are Linux's; the rest are the runner's. */
enum {
    SYS_WRITE = 64,        /* write(fd, buf, len): fd 1 and 2 go to the player's chat */
    SYS_EXIT = 93,         /* exit(code) */
    SYS_YIELD = 124,       /* sched_yield(): give up the rest of this tick */
    SYS_TIME = 4096,       /* milliseconds since the server started */
    SYS_WL_CONNECT = 4097, /* connect to the compositor: returns the socket */
    SYS_WL_SEND = 4098,    /* wl_send(sock, words, n, fd): one message's words, and an fd or -1 */
    SYS_WL_RECV = 4099,    /* wl_recv(sock, words, max): words received (0 if none yet) */
    SYS_P15_CREATE = 4100, /* p15_create(w, h): a p15 pixel memfd (black) */
    SYS_P15_BLIT = 4101,   /* p15_blit(fd, src, w, y, rows): rgb555 rows from RAM into the memfd */
    SYS_INSTRET = 4102,    /* instructions run so far */
};

static inline int syscall5(int n, int a0, int a1, int a2, int a3, int a4)
{
    register int r_a0 __asm__("a0") = a0;
    register int r_a1 __asm__("a1") = a1;
    register int r_a2 __asm__("a2") = a2;
    register int r_a3 __asm__("a3") = a3;
    register int r_a4 __asm__("a4") = a4;
    register int r_a7 __asm__("a7") = n;
    __asm__ volatile("ecall"
                     : "+r"(r_a0)
                     : "r"(r_a1), "r"(r_a2), "r"(r_a3), "r"(r_a4), "r"(r_a7)
                     : "memory");
    return r_a0;
}

static inline int sys_write(int fd, const void *buf, int len) { return syscall5(SYS_WRITE, fd, (int)buf, len, 0, 0); }
static inline void sys_exit(int code) { syscall5(SYS_EXIT, code, 0, 0, 0, 0); for (;;) {} }
static inline void sys_yield(void) { syscall5(SYS_YIELD, 0, 0, 0, 0, 0); }
static inline u32 sys_time(void) { return (u32)syscall5(SYS_TIME, 0, 0, 0, 0, 0); }
static inline u32 sys_instret(void) { return (u32)syscall5(SYS_INSTRET, 0, 0, 0, 0, 0); }

/* The compiler may call these for struct copies and zeroing. */
void *memset(void *d, int c, unsigned n);
void *memcpy(void *d, const void *s, unsigned n);
unsigned strlen(const char *s);

/* Output to stdout (the player's chat, a line at a time). */
void puts_(const char *s);
void putu(u32 v);
void puti(int v);
void puthex(u32 v);

#endif
