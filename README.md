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
| `@wl start` | Starts the desktop: you sit on an invisible seat, every window is locked to your screen, and where you look is the mouse. |
| `@wl info` | Runs **wayland-info**: prints the globals, shm formats, seat and output in chat. |
| `@wl simple` | Runs **simple**: a window with a bouncing square (like weston-simple-shm). |
| `@wl paint` | Runs **paint**: a canvas. Click to paint. Type `1`–`8` for a color, `p` to toggle the pen (paint as you look), `c` to clear. |
| `@wl terminal` | Runs **terminal**: a terminal with a small shell (`help`, `echo`, `ps`, `uptime`, `run <app>`, `clear`, `exit`). |
| `@wl bg <rrggbb>` | Sets the desktop color (black to start), like the start menu's swatches. |
| `@wl stop` | Stops the desktop and every app, and lets you off the seat. |
| `@wl stats` | Prints plot CPU, windows and connections. |
| `@key <name>` | Types a special key: `enter`, `back`, `tab`, `esc`, `up`, `down`, `left`, `right`. |
| `@wl look <x> <y>` | Points the cursor at canvas pixel (x, y), counted from the screen centre (it turns you). For testing. |
| `@wl test` | Runs the kernel and wire self-test (prints `WLTEST` lines). |
| `@scr <width> <height> [bandRows] [anim]` | Shows a screen-locked test canvas over your whole view (width a multiple of 32; `anim` 1 bounces a square). `@scr stop` removes it. |

Any app command starts the compositor if it isn't running. On the desktop,
the home button on the taskbar does the same.

**Tests on join:** when a player with developer or owner access joins, or
switches to play mode (which every deploy does), `tests.tc` runs:
- the codec checks;
- an end-to-end run of the desktop and its apps:
  - the seat and the cursor, and the seat at the shaders' desktop flag;
  - the shell's background and taskbar, the home button opening the start
    menu, and the menu starting paint;
  - globals and the p15 format;
  - three windows mapped and presented;
  - a typed line echoed by the terminal;
  - a click painting a dot;
  - hit tests for body, grip, title and close;
  - the cursor following the player's look;
  - a window dragged by its title bar;
  - a window resized with its grip (paint keeps its picture, and the
    terminal reflows);
  - taskbar buttons focusing, minimizing and restoring a window;
  - simple animating, and the menu closing it;
  - a swatch setting the desktop color, and a desktop click closing the menu;
- the canvas card, then the card on screen for 5 seconds.

The mouse checks turn the player to aim the cursor, the way looking around
does, and hold the resize outline up for 3 seconds. The run prints
`WLTEST` lines to chat. After a deploy, `tools/read_test.sh 150` prints it
from the client log, so no keyboard or mouse input is needed.

**The desktop:** windows, title bars and the cursor are locked to your
screen. They stay put wherever you look and draw over the world, on a
canvas 360 pixels tall that fits the window's height. You sit on an
invisible seat facing yaw 0; dismounting is cancelled while the desktop
runs.

**Input:**
- **Mouse:** where you look. The cursor moves 4 canvas pixels per degree of
  yaw and pitch from straight ahead. The shader draws the cursor arrow from
  the camera every frame, and the server uses the same mapping for
  `wl_pointer` enter, leave and motion.
- **Clicks:** left and right click send button 272 and 273 (a press and a
  release, since DF only reports clicks).
- **Keyboard:** chat lines go to the focused window as `wl_keyboard` key
  events, followed by Enter.

**Shell** (`shell.tc`). The desktop is an OS shell around the compositor:
- **Background:** one solid color, black to start. The start menu's
  swatches and `@wl bg` change it.
- **Taskbar:** a static bar along the bottom, with no title bar. The home
  button (the house) opens and closes the start menu. Then there is one
  button per window, oldest first. Click a button to bring its window up;
  click the focused window's button to minimize it.
- **Start menu:** a static panel above the home button, with no title bar.
  It starts apps (info, simple, paint, terminal), lists open windows (click
  one to bring it up, or its red x to close it) and offers desktop colors.
  Starting or closing something closes the menu, and so does a click on the
  desktop.
- **No hand, hotbar or crosshair:** while you sit at the desktop, the pack's
  shaders don't draw the first-person hand and held item, the hotbar with
  the hearts, food, armor and XP bars around it, or the crosshair.

**Windows:**
- Click a window to focus and raise it. The focused window's title bar is
  blue.
- Click a title bar to pick the window up, then click again to drop it.
- Click the grip in a window's bottom-right corner, move, and click again
  to resize it. A yellow outline shows the new size. The client gets
  `xdg_toplevel.configure` with that size and redraws: simple rebuilds its
  background, paint keeps its picture, and the terminal reflows. Windows
  are 48×32 to 600×330 pixels, with even widths.
- The red box closes the window (`xdg_toplevel.close`).

## How it works

```
 app process (apps.tc)            compositor process (server.tc)
 wlc.tc client library            dispatch -> objects, surfaces, xdg-shell
        |    wire.tc words              |   wm.tc: desktop, seat, cursor, focus, move, resize
        v                               v   render.tc: bands -> canvas text displays
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
  signatures from `wayland.xml`, `xdg-shell.xml` and `protocol/df-shell.xml`.
- **Compositor** (`server.tc`). It offers `wl_compositor` 4, `wl_shm` 1
  (argb8888, xrgb8888, rgb332 and p15), `wl_seat` 1 (pointer and keyboard),
  `wl_output` 1, `xdg_wm_base` 1 and `df_shell` 1 (the shell's own). Surfaces follow the usual
  pending/commit model, and toplevels get the initial configure / ack
  handshake. The keymap is format 0 (no_keymap): both ends use the US evdev
  table in `keymap.tc`.
- **Rendering** (`render.tc`, the pack). A window is a stack of text displays
  ("bands"), one text line per pixel row.
  - **p15 buffers** (fourcc `DF15`, 892421700; all the apps) are pools of
    row strings, one `wl:p15` glyph (an rgb555 pixel) per pixel. A buffer's
    `offset` is its first row in the pool, and `stride` counts glyphs.
    Clients draw by splicing row strings (`font.tc`: `p15Fill`, `p15Text`,
    `p15Splice`), so the compositor never converts pixels: a band is just
    the canvas mark and its rows joined, about 0.05 µs of DF time per glyph.
  - **Tagged formats** (`argb8888`, `xrgb8888`, `rgb332`) are still offered,
    but they carry pixel data in the text color, which the canvas mark needs,
    so their windows show grey on the desktop. (The `@px` spike still draws
    them in the world.)

  Bands hold about 1,024 glyphs. A commit's damage marks bands, and each tick
  the compositor redraws marked bands within a budget of about 7,500 glyphs,
  because the client re-processes every glyph sent. A frame is presented
  when no marked bands are left: the buffer is released and the frame
  callbacks run, which paces the clients. Each glyph's last texel column is
  transparent, so the bitmap font's advance equals the glyph width and
  pixels tile with no gaps.
- **Desktop** (`wm.tc`, `text.vsh`). Every band, title bar, grip, the resize
  outline and the cursor is a text display at the seated player's eye. Its
  translation puts it on a 360-pixel-tall canvas (40 canvas pixels per
  block, from the screen centre), and its z stacks windows. The text color
  marks canvas glyphs: `#FAB4A5` for windows, `A6` for sprites (pure black
  is clear), `A7` for the cursor, which the shader places at the camera's
  look point every frame, and `A8` for full-width strips. Title bars are small p15 images the compositor
  draws with the 8×8 font (`font.tc`, from Lat15-VGA8).
- **Shell** (`shell.tc`, `protocol/df-shell.xml`). The shell is an ordinary
  client with one extra global, `df_shell` (like wlr-layer-shell and
  wlr-foreign-toplevel-management cut down). `get_panel` gives a surface a
  role, background, taskbar or menu: a panel has no title bar, can't be
  moved or resized, never takes keyboard focus, maps with a buffer and
  unmaps with a null one. The compositor tells the shell about every window
  by handle (`window` with title and focused/minimized state,
  `window_closed`, `done`), and the shell asks it to `activate`, `minimize`
  or `close` a window or `launch` an app. Stacking, back to front: the
  background, the windows, the taskbar, the menu, the resize outline and
  the cursor. The background and the taskbar's ends are full-width strips
  (`A8`, below): a few glyphs per row that the shader stretches across the
  window, so they cost a few hundred glyphs, not 230,000, and fill windows
  wider than 16:9.
- **Hiding the hand and HUD** (`wl:desktop.glsl`). The seat sits at block
  fraction 0.123 in x and 0.456 in z. Every pipeline can read the camera's
  fraction (`Globals.CameraOffset`), so that is the desktop flag. While it
  is set, `entity.vsh` and `item.vsh` drop vertices within 2 blocks of the
  camera (the first-person hand and held item), and `position_tex_color.vsh`
  drops textured GUI vertices in the bottom-centre HUD area and at the
  crosshair. Text keeps drawing, so the chat box still works.
- **Resize** (`wm.tc`, `wlc.tc`). The grip click starts an outline (four
  sprite displays) that follows the cursor; the next click sends
  `xdg_toplevel.configure` and `xdg_surface.configure`. `wlcConfigure` acks
  it and reports the new size, and `wlcResize` swaps in a new buffer and
  pool. The client's next commit at that size makes the compositor rebuild
  the window's displays.

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
| tagged formats: `simple` animating, alone or with `paint` and `terminal` idle | 41% |
| p15 (2026-11-05): `simple` animating, `paint` and `terminal` idle | 3.9% |

- **Cost per glyph:** about 6.7 µs of DF time for the tagged formats, and
  about 0.05 µs for p15 (see Data path benchmarks).
- **Where the time goes:** about 30% builds the MiniMessage strings and about
  70% parses them and sets the text.
- **Damage tracking:** windows that don't change cost almost nothing.
- **Tearing:** bands reach the client on different frames, so a moving
  image can show two frames at once across a band boundary.

## Screen canvas

`@scr` (`screen.tc`) puts p15 bands at the player's eye and lets the text
shader place them on a canvas over the whole window, whatever the player
looks at. This is the full-view route to a "1080p screen".

- **Marker:** a band's text is `<font:wl:p15><c:#FA<g>A5>` and its rows. The
  color is one tag per band, so it costs DF nothing per pixel. `text.vsh`
  reads it: red 250 and blue 165 mean canvas, and green is half the canvas
  height.
- **Placement:** the display sits at the eye (yaw 0, pitch 0, fixed
  billboard), so a glyph's `Position` is its offset from the eye. That is
  40 canvas pixels per block, and the display translation positions each
  band. The shader snaps glyph edges to whole window pixels and draws just
  in front of the camera, ignoring camera rotation and FOV. The canvas fits
  the window height and is centred.
- **Following the player:** the bands are teleported to the player's eye
  every tick. A walking player sees the canvas jitter by a few canvas
  pixels; a seated or still player sees none.

Tested on Plot 206003 on 2026-11-05 at 480×270: the card covered the
view, centred, not mirrored, with its one-pixel border at the window edges.
The 5-bit color steps of rgb555 show as bands in the gradient. FPS was not
measured (it needs the F3 overlay). The per-glyph cost from Data path
benchmarks gives about 40 FPS static for 130k glyphs, about 60 at 384×216
and about 24 at 640×360.

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
| `src/wm.tc` | Desktop, placement, title bars, panels, focus, minimize, pointer, keyboard, dragging, resizing, the shell's window list |
| `src/shell.tc` | The desktop shell: background, taskbar, start menu |
| `protocol/df-shell.xml` | The shell's protocol, `df_shell` and `df_panel` |
| `src/render.tc` | Band rendering and presentation |
| `src/wlc.tc` | Client library |
| `src/apps.tc` | wayland-info, simple, paint, terminal |
| `src/font.tc`, `src/font8.tc` | p15 drawing: glyph lookup, fills, splices and 8×8 text; font rows generated by `tools/font2tc.py` |
| `src/p15.tc` | Generated `wl:p15` glyph table (`pack/src/px_assets.py`) |
| `src/bench.tc` | Data path benchmarks (`@bench`) |
| `src/keymap.tc` | US evdev key table |
| `src/events.tc` | Player clicks and chat as input |
| `src/wl.tc`, `src/commands.tc` | `@wl`, `@key`, `@px`, `@pack` |
| `src/tests.tc` | Codec self-test (`@wl test`) and the tests that run on join |
| `src/screen.tc` | Screen-locked canvas spike (`@scr`) |
| `src/spike.tc` | The original render spike (`@px`) |
| `src/glyphs.tc` | Generated pixel-glyph and hex tables (`pack/src/px_assets.py`) |
| `src/pack.tc` | Sends the pack on join |
| `src/cpu.tc` | `cpuYield`, from tc-neural_network |
| `pack/` | Resource pack source (`pack/src/` holds generators and is not shipped) |
| `tools/build_pack.py` | Validates, builds and publishes the pack |
| `tools/deploy.sh` | Compiles, places the code and switches to play mode |
| `tools/read_test.sh` | Prints the last `WLTEST` run from the client log (after a deploy: `tools/read_test.sh 90`) |
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

This pack overrides `minecraft:core/text`, the same as the mech game's pack,
and the vertex shaders of `core/entity`, `core/item` and
`core/position_tex_color` (only while the desktop flag is set).
This project also defines the `command`, `join`, `resourcePackLoad`,
`leftClick`, `rightClick`, `chat` and `dismount` events. On a plot shared with the mech
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
- One player drives the input: whoever ran `@wl start`. The desktop's
  displays aren't hidden from other players, so others nearby would see
  them in the world.
- The server assumes a 16:9 window when it clamps the cursor and places
  windows. On wider windows the shader shows more canvas at the sides, so
  the cursor can't reach the outer edges. The taskbar's buttons stay in the
  16:9 area, and its color runs out to the sides.
- The taskbar shows 7 window buttons and the start menu lists 5 windows.
- The hand hiding drops every entity and item vertex within 2 blocks of the
  camera while you sit at the desktop, so a mob or item that close
  disappears too. Item counts in the hotbar slots are text and still draw.
