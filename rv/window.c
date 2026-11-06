/* window: a Wayland client in C. It speaks the wire protocol itself, word
 * by word, over the runner's socket: it binds the globals, makes an
 * xdg_toplevel, shares a p15 buffer and draws a gradient. A click paints
 * a dot; the close box ends it. */
#include "rv.h"

#define W 64
#define H 48
#define P15 892421700u /* "DF15": p15 glyph rows (README) */

static u16 fb[W * H];     /* rgb555 pixels; p15_blit copies them into the memfd */
static u32 msg[64];       /* the message being built */
static int mlen;
static u32 rx[512];       /* received events, whole messages */
static int sock;
static u32 next_id = 2;

static u32 new_id(void) { return next_id++; }

static void begin(u32 obj, u32 opcode)
{
    msg[0] = obj;
    msg[1] = opcode;
    mlen = 2;
}

static void arg(u32 v) { msg[mlen++] = v; }

static void arg_str(const char *s)
{
    u32 n = strlen(s) + 1;
    u32 words = (n + 3) / 4;
    arg(n);
    memset(&msg[mlen], 0, words * 4);
    memcpy(&msg[mlen], s, n);
    mlen += (int)words;
}

/* Sends the message, with fd (or -1) beside it. */
static void send(int fd)
{
    msg[1] |= (u32)(mlen * 4) << 16;
    syscall5(SYS_WL_SEND, sock, (int)msg, mlen, fd, 0);
}

static int streq(const u8 *a, const char *b)
{
    while (*b && *a == (u8)*b) a++, b++;
    return *a == 0 && *b == 0;
}

/* Objects, by the ids this client gives them. */
static u32 registry, compositor, shm, wm, seat, surface, xsurface, toplevel, pointer, pool, buffer;
static int memfd, configured, quit;
static int px, py;
static u32 brush = 0x7c00;

static void bind(u32 name, const char *iface, u32 version, u32 *id)
{
    *id = new_id();
    begin(registry, 0);
    arg(name);
    arg_str(iface);
    arg(version);
    arg(*id);
    send(-1);
}

/* Handles one event: obj, opcode and its argument words. */
static void event(u32 obj, u32 op, u32 *a)
{
    if (obj == 1 && op == 0) {
        puts_("wayland error: ");
        puts_((const char *)&a[3]);
        puts_("\n");
        quit = 1;
    } else if (obj == registry && op == 0) {
        const u8 *iface = (const u8 *)&a[2];
        if (streq(iface, "wl_compositor")) bind(a[0], "wl_compositor", 4, &compositor);
        else if (streq(iface, "wl_shm")) bind(a[0], "wl_shm", 1, &shm);
        else if (streq(iface, "xdg_wm_base")) bind(a[0], "xdg_wm_base", 1, &wm);
        else if (streq(iface, "wl_seat")) bind(a[0], "wl_seat", 1, &seat);
    } else if (obj == wm && op == 0) {
        begin(wm, 3); /* pong */
        arg(a[0]);
        send(-1);
    } else if (obj == xsurface && op == 0) {
        begin(xsurface, 4); /* ack_configure */
        arg(a[0]);
        send(-1);
        configured = 1;
    } else if (obj == toplevel && op == 1) {
        quit = 1; /* close */
    } else if (obj == pointer && (op == 0 || op == 2)) {
        /* enter (serial, surface, x, y) or motion (time, x, y): 24.8 fixed */
        px = (int)a[op == 0 ? 2 : 1] >> 8;
        py = (int)a[op == 0 ? 3 : 2] >> 8;
    } else if (obj == pointer && op == 3 && a[3] == 1) {
        /* button press: paint a 5 x 5 dot and change color */
        for (int y = py - 2; y <= py + 2; y++)
            for (int x = px - 2; x <= px + 2; x++)
                if (x >= 0 && x < W && y >= 0 && y < H) fb[y * W + x] = (u16)brush;
        brush = ((brush << 5) | (brush >> 10)) & 0x7fff;
        syscall5(SYS_P15_BLIT, memfd, (int)fb, W, 0, H);
        begin(surface, 1); /* attach */
        arg(buffer); arg(0); arg(0);
        send(-1);
        begin(surface, 9); /* damage_buffer */
        arg(0); arg(0); arg(W); arg(H);
        send(-1);
        begin(surface, 6); /* commit */
        send(-1);
    }
}

/* Reads and handles every event waiting; 0 if there were none. */
static int dispatch(void)
{
    int n = syscall5(SYS_WL_RECV, sock, (int)rx, 512, 0, 0);
    if (n < 0) quit = 1;
    int i = 0;
    while (i + 2 <= n) {
        u32 size = rx[i + 1] >> 16;
        event(rx[i], rx[i + 1] & 0xffff, &rx[i + 2]);
        i += (int)(size / 4);
    }
    return n > 0;
}

int main(void)
{
    sock = syscall5(SYS_WL_CONNECT, 0, 0, 0, 0, 0);
    registry = new_id();
    begin(1, 1); /* wl_display.get_registry */
    arg(registry);
    send(-1);
    while (!compositor || !shm || !wm || !seat) {
        if (!dispatch()) sys_yield();
    }

    surface = new_id();
    begin(compositor, 0); /* create_surface */
    arg(surface);
    send(-1);
    xsurface = new_id();
    begin(wm, 2); /* get_xdg_surface */
    arg(xsurface);
    arg(surface);
    send(-1);
    toplevel = new_id();
    begin(xsurface, 1); /* get_toplevel */
    arg(toplevel);
    send(-1);
    begin(toplevel, 2); /* set_title */
    arg_str("C on RISC-V");
    send(-1);
    pointer = new_id();
    begin(seat, 0); /* get_pointer */
    arg(pointer);
    send(-1);
    begin(surface, 6); /* commit: ask for the first configure */
    send(-1);
    while (!configured && !quit) {
        if (!dispatch()) sys_yield();
    }

    /* A gradient: red across, green down, blue in a checker. Shifts only:
     * the machine runs a few thousand instructions a second. */
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++)
            fb[y * W + x] = (u16)(((x >> 1) << 10) | ((y >> 1) << 5) | (((x ^ y) & 8) ? 24 : 8));

    memfd = syscall5(SYS_P15_CREATE, W, H, 0, 0, 0);
    syscall5(SYS_P15_BLIT, memfd, (int)fb, W, 0, H);
    pool = new_id();
    begin(shm, 0); /* create_pool(id, fd, size): the fd travels beside the words */
    arg(pool);
    arg(W * H);
    send(memfd);
    buffer = new_id();
    begin(pool, 0); /* create_buffer(id, offset, w, h, stride, format) */
    arg(buffer); arg(0); arg(W); arg(H); arg(W); arg(P15);
    send(-1);
    begin(surface, 1); /* attach */
    arg(buffer); arg(0); arg(0);
    send(-1);
    begin(surface, 9); /* damage_buffer */
    arg(0); arg(0); arg(W); arg(H);
    send(-1);
    begin(surface, 6); /* commit */
    send(-1);
    puts_("window up\n");

    while (!quit) {
        if (!dispatch()) sys_yield();
    }
    puts_("window closed\n");
    return 0;
}
