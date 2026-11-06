#version 330
#extension GL_ARB_separate_shader_objects : require

// Vanilla 26.3 core/text.vsh, plus:
//   rawColor: the text color before lighting, which text.fsh needs to decode
//     pixel glyphs (wl:px.glsl).
//   Screen canvas: glyphs whose text color is #FA<g><kind> sit on text
//     displays at the player's eye (yaw 0, pitch 0, fixed billboard), so
//     Position is the glyph's offset from the eye in blocks. They are placed
//     on a canvas that covers the whole window, ignoring camera rotation and
//     FOV: 40 canvas pixels per block, canvas (0, 0) at the window centre, x
//     right, y down, and the canvas 2 * g pixels tall (wl_canvas_position).
//     kind A5: a window band, opaque, placed by the display translation;
//          the translation's z stacks windows (0 to 0.1, larger is nearer).
//     kind A6: a sprite placed the same way; pure black p15 pixels are clear.
//     kind A7: the cursor: placed at the camera's look point (4 canvas pixels
//          per degree from yaw 0, pitch 0, the server's mapping too), in
//          front of everything; pure black pixels are clear.

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
#include <minecraft:fog.glsl>
#include <minecraft:sample_lightmap.glsl>
#endif

#include <minecraft:globals.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:projection.glsl>

layout(location = 0) in vec3 Position;
layout(location = 1) in vec4 Color;
layout(location = 2) in vec2 UV0;
#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
layout(location = 3) in ivec2 UV2;
#endif

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
uniform sampler2D Sampler2;
layout(location = 0) out float sphericalVertexDistance;
layout(location = 1) out float cylindricalVertexDistance;
#endif

layout(location = 2) out vec4 vertexColor;
layout(location = 3) out vec2 texCoord0;
layout(location = 4) out vec4 rawColor;
// 1 for sprite and cursor glyphs: text.fsh clears their pure black pixels.
layout(location = 5) out float spriteKey;

// Canvas pixel position (from the window centre, y down) to clip space: whole
// window pixels, `canvasH` canvas pixels to the window height, `depth` blocks
// in front of the camera (the near plane is 0.05).
vec4 wl_canvas_position(vec2 canvasPos, float canvasH, float depth) {
    vec2 pixel = floor(canvasPos * (ScreenSize.y / canvasH) + 0.5) + floor(ScreenSize * 0.5);
    vec2 ndc = pixel / ScreenSize * 2.0 - 1.0;
    vec4 up = ProjMat * vec4(0.0, 1.0, -1.0, 1.0);
    ndc.y *= -sign(up.y / up.w);
    vec4 front = ProjMat * vec4(0.0, 0.0, -depth, 1.0);
    return vec4(ndc, front.z / front.w, 1.0);
}

// Camera yaw and pitch in degrees (yaw 0 looks +Z, pitch > 0 looks down).
// ModelViewMat is the inverse camera rotation: its third row is backward.
vec2 wl_look_degrees() {
    vec3 forward = -vec3(ModelViewMat[0][2], ModelViewMat[1][2], ModelViewMat[2][2]);
    return degrees(vec2(atan(-forward.x, forward.z), asin(clamp(-forward.y, -1.0, 1.0))));
}

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);
    ivec3 mark = ivec3(round(Color.rgb * 255.0));
    bool canvas = false;
#ifndef IS_GUI
    spriteKey = 0.0;
    // Tagged wl:px glyphs carry pixel data in the color, so the marker is two
    // exact bytes; one tagged pixel color in 65,536 would be misread.
    if (mark.r == 250 && mark.g > 0 && mark.b >= 165 && mark.b <= 167) {
        canvas = true;
        float canvasH = 2.0 * float(mark.g);
        // The text renderer puts an even-width line's glyph edges half a canvas
        // pixel off the grid; rows are already on it.
        vec2 local = vec2(Position.x * 40.0 - 0.5, -Position.y * 40.0);
        if (mark.b == 167) {
            spriteKey = 1.0;
            vec2 halfCanvas = vec2(canvasH * ScreenSize.x / ScreenSize.y, canvasH) * 0.5;
            vec2 point = clamp(floor(wl_look_degrees() * 4.0 + 0.5), -halfCanvas, halfCanvas);
            gl_Position = wl_canvas_position(floor(point + local + 0.5), canvasH, 0.1);
        } else {
            spriteKey = mark.b == 166 ? 1.0 : 0.0;
            gl_Position = wl_canvas_position(floor(local + 0.5), canvasH, 0.25 - clamp(Position.z, 0.0, 0.1));
        }
    }
#endif

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
    sphericalVertexDistance = canvas ? 0.0 : fog_spherical_distance(Position);
    cylindricalVertexDistance = canvas ? 0.0 : fog_cylindrical_distance(Position);
    vertexColor = Color * sample_lightmap(Sampler2, UV2);
#else
    vertexColor = Color;
#endif
    texCoord0 = UV0;
    rawColor = Color;
#ifdef IS_GUI
    spriteKey = 0.0;
#endif
}
