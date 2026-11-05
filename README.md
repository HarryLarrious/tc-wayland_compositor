# tc-wayland_compositor

A Wayland compositor that runs entirely on a DiamondFire plot, written in
[Terracotta](https://owlfroggy.github.io/terracotta-beta-docs/). The clients
are Terracotta programs on the same plot. A resource pack's core text shader
draws their buffers.

Status: render spike. It answers one question: how fast can DF put buffer
pixels on screen?

## How pixels reach the screen

Each 32-bit word of a client's buffer becomes one glyph of the font `wl:px`:

- the text color holds the word's low 24 bits,
- the glyph (one of 256 per format) holds the top byte.

The text shader (`pack/assets/minecraft/shaders/core/text.fsh`,
`pack/assets/wl/shaders/include/px.glsl`) reads both and paints the glyph's
quad with the decoded pixels. DF only copies words into glyphs and does no
per-pixel math.

| Format | Pixels per glyph | Glyph size (font units) |
| --- | --- | --- |
| `argb8888` | 1 (alpha below 128 is cut out) | 10 × 10 |
| `rgb332` | 4, the leftmost in the low byte | 40 × 10 |

Each glyph's last texel column has alpha 0. The bitmap provider then gives
the glyph an advance equal to its quad width, so glyphs tile with no gap. A
text display's line height (10) equals the glyph height, so rows tile too.

## Spike commands

| Command | Does |
| --- | --- |
| `@px still <argb\|332> <width> <height> [bands]` | Draws a test card once and prints how long it took. |
| `@px start <argb\|332> <width> <height> [bands] [every]` | Loops an 8-frame animation, one frame every `every` ticks, and prints a `PXSPIKE` line every 5 seconds. |
| `@px stop` | Removes the window. |
| `@pack` | Sends the resource pack again. |

A window is a stack of text displays ("bands"), one text line per pixel row,
1/16 block per pixel. By default a band holds about 512 glyphs.

The test card has eight color bars on top. At the bottom left is a
one-pixel checkerboard, which shows any gap or blur between glyphs. At the
bottom right is a red checker with cut-out squares (argb8888 only).

A `PXSPIKE run` line reports frames per second (`fps`), the mean DF time per
frame in milliseconds (`ms`, worst in brackets) and the mean plot CPU
(`cpu`). Only DF's time is measured, not the client's.

## Spike results

Measured on 2026-11-04 on Plot 206003, with one player and every band
rewritten each frame:

| Window | Glyphs | Every | fps | DF ms per frame (worst) | Building strings | Plot CPU |
| --- | --- | --- | --- | --- | --- | --- |
| argb8888 64×48 | 3,072 | 1 tick | 20 | 20–21 (46) | 6 ms | 70–86% |
| rgb332 128×96 | 3,072 | 1 tick | 20 | 20 (35) | — | 73–82% |
| argb8888 128×96 | 12,288 | 4 ticks | 5 | 83 (113) | — | 78–84% |

- **Correct output:** both test cards are exact. The bars are in order, the
  1-pixel checkerboard is crisp with no seams between bands, and argb8888
  cut-out works.
- **Cost:** about 6.7 µs of DF time per glyph, whatever the format, so
  rgb332 gives 4 times the pixels for the same cost. Roughly 3,000 glyphs per
  tick fills the plot's CPU.
- **Where the time goes:** about 30% builds the MiniMessage strings and about
  70% parses them and sets the display text. The parse is the first thing to
  cut.
- **Tearing:** bands update on different client frames, so a moving image
  can show two frames at once across a band boundary.
- **DF bitwise:** the actions work on 32-bit signed ints, and the 64-bit
  option (`^>>`, `^<<` and the rest) gives wrong results. Words reach 2^32,
  so the top byte is split off with `%` and exact division.

## Layout

| Path | Contents |
| --- | --- |
| `src/spike.tc` | Window spawn, test-pattern painter, frame drawing and timing |
| `src/commands.tc` | Chat command dispatcher |
| `src/pack.tc` | Sends the pack on join |
| `src/glyphs.tc` | Generated glyph and hex tables |
| `src/cpu.tc` | `cpuYield`, from tc-neural_network |
| `pack/` | Resource pack source (`pack/src/` holds generators and is not shipped) |
| `tools/build_pack.py` | Validates, builds and publishes the pack |

## Resource pack

```sh
python3 pack/src/px_assets.py                    # regenerate the font and src/glyphs.tc
python3 tools/build_pack.py --check              # validate only
python3 tools/build_pack.py --publish --push     # build, commit to pack-dist, push
```

The shader check needs `glslc` and the Minecraft 26.3 client jar. After
publishing, set the printed URL in `packUrl()` (`src/pack.tc`).

This pack overrides `minecraft:core/text`, the same as the mech game's pack,
and the spike defines the `command`, `join` and `resourcePackLoad` events. On
a plot shared with the mech game, the last code and pack sent win.
