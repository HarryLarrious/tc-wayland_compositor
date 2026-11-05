#ifndef WL_PX_GLSL
#define WL_PX_GLSL

// Pixel glyphs (font wl:px, made by pack/src/px_assets.py) each carry one
// 32-bit buffer word:
//   glyph texel: red = word >> 24, green = WL_PX_MARK, blue = 0xA0 | format << 2 | sub-pixel
//   text color:  red = (word >> 16) & 255, green = (word >> 8) & 255, blue = word & 255
// Formats:
//   0 argb8888: one pixel; alpha below 128 is cut out
//   1 rgb332:   four pixels; sub-pixel s (left to right) is byte s of the
//               word, as a little-endian buffer stores them

const int WL_PX_MARK = 0xC3;
const int WL_PX_ARGB8888 = 0;
const int WL_PX_RGB332 = 1;

// Decodes the fragment of a pixel glyph from its texel and raw (unlit) text
// color. Sets marked to false for any other glyph; the result is then unused.
vec4 wl_px_decode(vec4 texel, vec4 rawColor, out bool marked) {
    ivec3 t = ivec3(round(texel.rgb * 255.0));
    marked = t.g == WL_PX_MARK && (t.b & 0xF0) == 0xA0;
    if (!marked) {
        return vec4(0.0);
    }
    int format = (t.b >> 2) & 3;
    int sub = t.b & 3;
    uvec3 c = uvec3(round(rawColor.rgb * 255.0));
    uint word = uint(t.r) << 24 | c.r << 16 | c.g << 8 | c.b;
    if (format == WL_PX_RGB332) {
        uint b = (word >> (8u * uint(sub))) & 0xFFu;
        return vec4(float(b >> 5) / 7.0, float((b >> 2) & 7u) / 7.0, float(b & 3u) / 3.0, 1.0);
    }
    return vec4(vec3(c) / 255.0, (word >> 24) >= 128u ? 1.0 : 0.0);
}

#endif
