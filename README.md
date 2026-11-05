# tc-wayland_compositor

A Wayland compositor that runs entirely on a DiamondFire plot, written in
[Terracotta](https://owlfroggy.github.io/terracotta-beta-docs/). Its clients
are Terracotta programs on the same plot. They speak the real Wayland wire
protocol (`wl_*` and `xdg-shell`, encoded as 32-bit words) to the compositor
through an in-DF "kernel" that provides sockets, fd passing and shared
memory. A resource pack's core text shader draws the windows.

Nothing runs outside DF. Python scripts only generate tables and the pack at
build time.

## Use

| Command | Does |
| --- | --- |
| `@wl start` | Starts the compositor. The wall goes 7 blocks in front of you, facing you. |
| `@wl info` | Runs **wayland-info**: prints the globals, shm formats, seat and output in chat. |
| `@wl simple` | Runs **simple**: an argb8888 window with a bouncing square (like weston-simple-shm). |
| `@wl paint` | Runs **paint**: an rgb332 canvas. Click to paint. Type `1`–`8` for a color, `p` to toggle the pen (paint as you look), `c` to clear. |
| `@wl term` | Runs **term**: an rgb332 terminal with a small shell (`help`, `echo`, `ps`, `uptime`, `run <app>`, `clear`, `exit`). |
| `@wl stop` | Stops the compositor and every app. |
| `@wl stats` | Prints plot CPU, windows and connections. |
| `@key <name>` | Types a special key: `enter`, `back`, `tab`, `esc`, `up`, `down`, `left`, `right`. |
| `@wl look <x> <y>` | Turns you to look at wall pixel (x, y). This is for testing the pointer. |
| `@wl test` | Runs the kernel and wire self-test (prints `WLTEST` lines). |

Any app command starts the compositor if it isn't running.

**Input:**
- **Pointer:** your crosshair. Each tick the compositor casts your look ray
  onto the wall, which gives `wl_pointer` enter, leave and motion.
- **Clicks:** left and right click send button 272 and 273 (a press and a
  release, since DF only reports clicks).
- **Keyboard:** chat lines go to the focused window as `wl_keyboard` key
  events, followed by Enter.

**Windows:**
- Click a window to focus and raise it. The focused window's title bar is
  blue.
- Click a title bar to pick the window up, then click again to drop it.
- The red box closes the window (`xdg_toplevel.close`).

## How it works

```
 app process (apps.tc)            compositor process (server.tc)
 wlc.tc client library            dispatch -> objects, surfaces, xdg-shell
        |    wire.tc words              |   wm.tc: wall, focus, pointer, keys
        v                               v   render.tc: bands -> text displays
 kernel.tc: k.q <c> c2s / s2c word queues, k.fdq fd queues, k.mem <fd> memfds
```

- **Kernel** (`kernel.tc`). A connection is a pair of word queues, each with
  an fd queue beside it (SCM_RIGHTS). A memfd is a global list of 32-bit
  little-endian words. A client draws into its memfd, and the compositor
  reads the same list, so pixels are never copied between processes.
- **Wire** (`wire.tc`, `protocol.tc`). A message is `[object id, size << 16
  | opcode, args...]`. Strings and arrays are their byte length, then the
  bytes packed four to a word. `tools/protocol2tc.py` generates the message
  signatures from `wayland.xml` and `xdg-shell.xml`.
- **Compositor** (`server.tc`). It offers `wl_compositor` 4, `wl_shm` 1
  (argb8888, xrgb8888, rgb332), `wl_seat` 1 (pointer and keyboard),
  `wl_output` 1 and `xdg_wm_base` 1. Surfaces follow the usual
  pending/commit model, and toplevels get the initial configure / ack
  handshake. The keymap is format 0 (no_keymap): both ends use the US evdev
  table in `keymap.tc`.
- **Rendering** (`render.tc`, the pack). A window is a stack of text displays
  ("bands"), one text line per pixel row, about 512 glyphs per band. Each
  buffer word becomes one glyph of the font `wl:px`: the text color carries
  the word's low 24 bits and the glyph carries the top byte. The core text
  shader decodes them:

  | Format | Pixels per glyph |
  | --- | --- |
  | `argb8888` | 1 (alpha below 128 is cut out) |
  | `xrgb8888` | 1 |
  | `rgb332` | 4, the leftmost in the low byte |

  A commit's damage marks bands. The compositor redraws at most about 1,500
  glyphs per tick. A frame is presented when no marked bands are left: the
  buffer is released and the frame callbacks run, which paces the clients.
  Each glyph's last texel column is transparent, so the bitmap font's advance
  equals the glyph width and pixels tile with no gaps.
- **Decorations** (`wm.tc`). Title bars are small rgb332 memfds that the
  compositor draws itself with the 8×8 font (`font.tc`, from Lat15-VGA8), and
  renders like any window.

## Measurements

These were measured on Plot 206003 on 2026-11-04 with one player.

The render spike (`@px`) rewrote every band each frame:

| Window | Glyphs | Every | fps | DF ms per frame (worst) | Plot CPU |
| --- | --- | --- | --- | --- | --- |
| argb8888 64×48 | 3,072 | 1 tick | 20 | 20–21 (46) | 70–86% |
| rgb332 128×96 | 3,072 | 1 tick | 20 | 20 (35) | 73–82% |
| argb8888 128×96 | 12,288 | 4 ticks | 5 | 83 (113) | 78–84% |

The compositor itself:

| State | Plot CPU |
| --- | --- |
| no compositor | 0% |
| `simple` animating | 41% |
| `simple` animating, `paint` and `term` idle | 41% |

- **Cost per glyph:** about 6.7 µs of DF time, whatever the format, so rgb332
  gives four times the pixels for the same cost.
- **Where the time goes:** about 30% builds the MiniMessage strings and about
  70% parses them and sets the text.
- **Damage tracking:** windows that don't change cost almost nothing.
- **Tearing:** bands reach the client on different frames, so a moving
  image can show two frames at once across a band boundary.

## DiamondFire findings

- **Bitwise:** DF's bitwise actions work on 32-bit signed ints, and the
  64-bit option (`^>>`, `^<<` and the rest) gives wrong results. For example,
  `0xFFFF0000 ^>>> 24` comes back unchanged. Words reach 2^32, so the code
  splits off the top byte with `%` and exact division and keeps shifts below
  2^31.
- **Function arguments:** `f(argNum(...), argNum(...))` once gave a wrong
  argument (height 0). Putting each call's result in its own variable first
  fixed it.
- **Mode switches:** a mode switch ends processes without running any
  cleanup, so the compositor keeps a heartbeat (`s.beat`), and `@wl` restarts
  it when the heartbeat is old.
- **Line splitting:** long codelines (the generated `wlProtoInit`) need
  `plotSize` in `.vscode/launch.json` (300 here). Without it, placing code
  can stall.

## Layout

| Path | Contents |
| --- | --- |
| `src/kernel.tc` | Sockets, fd queues, memfds |
| `src/wire.tc` | Wire format encode and decode |
| `src/protocol.tc` | Generated message tables (`tools/protocol2tc.py`) |
| `src/server.tc` | Compositor loop, request dispatch, surfaces, xdg-shell |
| `src/wm.tc` | Wall, placement, title bars, focus, pointer, keyboard, dragging |
| `src/render.tc` | Band rendering and presentation |
| `src/wlc.tc` | Client library |
| `src/apps.tc` | wayland-info, simple, paint, term |
| `src/font.tc`, `src/font8.tc` | 8×8 text drawing; font rows generated by `tools/font2tc.py` |
| `src/keymap.tc` | US evdev key table |
| `src/events.tc` | Player clicks and chat as input |
| `src/wl.tc`, `src/commands.tc` | `@wl`, `@key`, `@px`, `@pack` |
| `src/tests.tc` | Self-test (`@wl test`) |
| `src/spike.tc` | The original render spike (`@px`) |
| `src/glyphs.tc` | Generated pixel-glyph and hex tables (`pack/src/px_assets.py`) |
| `src/pack.tc` | Sends the pack on join |
| `src/cpu.tc` | `cpuYield`, from tc-neural_network |
| `pack/` | Resource pack source (`pack/src/` holds generators and is not shipped) |
| `tools/build_pack.py` | Validates, builds and publishes the pack |
| `tools/deploy.sh` | Compiles, places the code and switches to play mode |
| `tools/read_test.sh` | Prints the last `WLTEST` run from the client log |

## Build

```sh
python3 tools/protocol2tc.py                     # regenerate src/protocol.tc
python3 tools/font2tc.py                         # regenerate src/font8.tc
python3 pack/src/px_assets.py                    # regenerate the pixel font and src/glyphs.tc
python3 tools/build_pack.py --check              # validate the pack
python3 tools/build_pack.py --publish --push     # build, commit to pack-dist, push
tools/deploy.sh                                  # place the code on the plot
```

The shader check needs `glslc` and the Minecraft 26.3 client jar. After
publishing, set the printed URL in `packUrl()` (`src/pack.tc`).

This pack overrides `minecraft:core/text`, the same as the mech game's pack.
This project also defines the `command`, `join`, `resourcePackLoad`,
`leftClick`, `rightClick` and `chat` events. On a plot shared with the mech
game, the last code and pack sent win.

## Limits

- Only `wl_shm` buffers, toplevels and the interfaces above: no subsurfaces,
  popups, dmabuf, data devices or touch.
- A memfd holds at most 10,000 words (DF's list limit), so a window can be
  at most about 96×96 in argb8888 or 192×192 in rgb332.
- No key repeat and no held mouse buttons: DF reports clicks and chat lines,
  not presses and releases.
- One player drives the input: whoever ran `@wl start`.
