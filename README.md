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
| `@wl simple` | Runs **simple**: a window with a bouncing square (like weston-simple-shm). |
| `@wl paint` | Runs **paint**: a canvas. Click to paint. Type `1`–`8` for a color, `p` to toggle the pen (paint as you look), `c` to clear. |
| `@wl term` | Runs **term**: a terminal with a small shell (`help`, `echo`, `ps`, `uptime`, `run <app>`, `clear`, `exit`). |
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
  an fd queue beside it (SCM_RIGHTS). A memfd is a global list: 32-bit
  little-endian words, or one glyph string per pixel row for p15 images. A
  client draws into its memfd, and the compositor reads the same list, so
  pixels are never copied between processes.
- **Wire** (`wire.tc`, `protocol.tc`). A message is `[object id, size << 16
  | opcode, args...]`. Strings and arrays are their byte length, then the
  bytes packed four to a word. `tools/protocol2tc.py` generates the message
  signatures from `wayland.xml` and `xdg-shell.xml`.
- **Compositor** (`server.tc`). It offers `wl_compositor` 4, `wl_shm` 1
  (argb8888, xrgb8888, rgb332 and p15), `wl_seat` 1 (pointer and keyboard),
  `wl_output` 1 and `xdg_wm_base` 1. Surfaces follow the usual
  pending/commit model, and toplevels get the initial configure / ack
  handshake. The keymap is format 0 (no_keymap): both ends use the US evdev
  table in `keymap.tc`.
- **Rendering** (`render.tc`, the pack). A window is a stack of text displays
  ("bands"), one text line per pixel row. The core text shader decodes the
  pixels:

  | Format | fourcc | How the data travels | Pixels per glyph | DF µs/glyph |
  | --- | --- | --- | --- | --- |
  | **p15** (all the apps) | `DF15` (892421700) | the buffer already holds glyph rows; a band is its rows joined, inside `<font:wl:p15>` | 1 (rgb555) | ~0.05 |
  | `argb8888` | 0 | each word becomes a `wl:px` glyph (top byte) with a text color (low 24 bits) | 1 (alpha below 128 is cut out) | ~7 |
  | `xrgb8888` | 1 | as argb8888 | 1 | ~7 |
  | `rgb332` | `RGB8` | as argb8888 | 4, the leftmost in the low byte | ~7 |

  A p15 buffer is a pool of row strings, one `wl:p15` glyph per pixel. The
  buffer's `offset` is its first row in the pool, and `stride` counts glyphs.
  Clients draw by splicing row strings (`font.tc`: `p15Fill`, `p15Text`,
  `p15Splice`), so the compositor never converts pixels. p15 bands hold
  about 1,024 glyphs, and the others about 512.

  A commit's damage marks bands. Each tick the compositor redraws marked
  bands within a budget of 1,500 units. A tagged glyph costs 1 unit and a p15
  glyph costs 1/5, because the client re-processes every glyph sent, so the
  budget is about 7,500 p15 glyphs a tick. A frame is presented when no
  marked bands are left: the buffer is released and the frame callbacks run,
  which paces the clients. Each glyph's last texel column is transparent, so
  the bitmap font's advance equals the glyph width and pixels tile with no
  gaps.
- **Decorations** (`wm.tc`). Title bars are small p15 images that the
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
| tagged formats: `simple` animating, alone or with `paint` and `term` idle | 41% |
| p15 (2026-11-05): `simple` animating, `paint` and `term` idle | 3.9% |

- **Cost per glyph:** about 6.7 µs of DF time for the tagged formats, and
  about 0.05 µs for p15 (see Data path benchmarks).
- **Where the time goes:** about 30% builds the MiniMessage strings and about
  70% parses them and sets the text.
- **Damage tracking:** windows that don't change cost almost nothing.
- **Tearing:** bands reach the client on different frames, so a moving
  image can show two frames at once across a band boundary.

## Data path benchmarks

These tests (`src/bench.tc`) find the cheapest way to get data from DF to the
shader. They were run on Plot 206003 on 2026-11-05.

- `@bench` times DF per glyph.
- `@bench probe <test> <glyphs>` checks that a text really arrives. DF can't
  read display text back, so it prints the parsed length and shows the text
  with an `END` marker.
- `@bench stress <displays> <mode> <every> <rows>` loads the network and the
  client while `tools/netrate.sh` samples the receive rate.

**Hard limits:**
- A DF string holds at most 10,000 characters. A longer join comes back
  empty, and concatenation is cut at 10,000. Styled text joined from parts is
  capped near 10,000 too, so **one text display takes at most about 10,000
  glyphs per set**.
- Supplementary-plane characters take two string positions, so a string
  holds only 5,000 of them. Fonts should use BMP codepoints.
- Parsing about 19,000 tags in a burst trips DF's LagSlayer, which halts the
  plot's code for a second.

**DF time per glyph** (texts under the limit; "Mbit/s" is payload at half
the plot's CPU):

| Method | µs/glyph | bits/glyph | Mbit/s |
| --- | --- | --- | --- |
| tag32: `<c:#rrggbb>G</c>` per glyph (the compositor today) | 8.5 | 32 | 1.9 |
| legacy color codes per glyph | 5.6 | 32 | 2.9 |
| tagged rows parsed ahead, joined as styled text | 2.4 | 32 | ~6 |
| lut13: one list lookup per value | 0.72–0.79 | 13 | 8.3–9.1 |
| str15: string-chunk lookup per value | 1.7–2.9 | 15 | 2.6–4.4 |
| join15: glyph strings made ahead, joined | 0.09–0.12 | 15 | 61–86 |
| **rows15: row strings made ahead, joined, parsed with `<font:wl:p15>`** | **0.05** | 15 | **147** |
| rows15 raw (no parse, default font) | ~0.01 | 15 | ~600 |

**Client:**
- **Drawing static glyphs:** about 0.17–0.21 µs per glyph per frame with
  our bitmap fonts. A 128×96 p15 card ran at 212 FPS against 193 for the
  tagged card (384 with nothing shown). Default-font CJK glyphs cost about
  15× more (30 FPS for 9,728 glyphs), so always use our own font.
- **Updating glyphs:** about 3–4 µs of client time per glyph re-sent. A text
  display re-processes its whole text on every change. Displays of 9,728
  p15 glyphs updated every tick gave:

  | Displays | Glyph updates/s | Payload | DF CPU | FPS |
  | --- | --- | --- | --- | --- |
  | 1 | 195k | 2.9 Mbit/s | ~1.5% | 68 |
  | 2 | 389k | 5.8 Mbit/s | ~3% | 36 |
  | 4 | 778k | 11.7 Mbit/s | 5.7% | 20 |

- **Network:** with four displays updating every tick, the client received
  1.78 MB/s for 11.7 Mbit/s of payload, which is 83% efficient once
  compressed.

**Best method:** tag-free `wl:p15` glyphs (15 bits each; rgb555 for now,
decoded by `px.glsl`).
- Clients keep their buffers as row strings.
- The compositor joins rows into bands of at most 10,000 glyphs and parses
  them inside `<font:wl:p15>`.
- That costs DF about 0.05 µs per glyph, 40–170× less than per-glyph color
  tags. The limit moves to the client: to stay near 60 FPS, keep changed
  glyphs under about 100–150k per second.
- Use small bands for windows that change in small regions, since every
  update re-sends and re-processes the whole band.

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
| `src/font.tc`, `src/font8.tc` | p15 drawing: glyph lookup, fills, splices and 8×8 text; font rows generated by `tools/font2tc.py` |
| `src/p15.tc` | Generated `wl:p15` glyph table (`pack/src/px_assets.py`) |
| `src/bench.tc` | Data path benchmarks (`@bench`) |
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
| `tools/netrate.sh` | Prints the client's receive rate from the server, once a second |

## Build

```sh
python3 tools/protocol2tc.py                     # regenerate src/protocol.tc
python3 tools/font2tc.py                         # regenerate src/font8.tc
python3 pack/src/px_assets.py                    # regenerate the pixel fonts, src/glyphs.tc and src/p15.tc
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
- A memfd holds at most 10,000 entries (DF's list limit). An argb8888 window
  can be at most about 96×96 and an rgb332 window about 192×192. A p15
  window can be up to 9,999 pixels wide (DF's string limit, with one
  character left for the newline) and 10,000 rows tall. In practice the
  client sets the limit: it draws about 40,000 glyphs a frame at 60 FPS and
  re-processes about 100–150k changed glyphs a second.
- No key repeat and no held mouse buttons: DF reports clicks and chat lines,
  not presses and releases.
- One player drives the input: whoever ran `@wl start`.
