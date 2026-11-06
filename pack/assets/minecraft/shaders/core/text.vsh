#version 330
#extension GL_ARB_separate_shader_objects : require

// Vanilla 26.3 core/text.vsh, plus:
//   rawColor: the text color before lighting, which text.fsh needs to decode
//     pixel glyphs (wl:px.glsl).
//   Screen canvas: glyphs whose text color is #FA<g>A5 sit on text displays at
//     the player's eye (yaw 0, pitch 0, fixed billboard), so Position is the
//     glyph's offset from the eye in blocks. They are placed on a canvas that
//     covers the whole window, ignoring camera rotation and FOV: 40 canvas
//     pixels per block, canvas (0, 0) at the window centre, x right, y down,
//     and the canvas 2 * g pixels tall (wl_canvas_position).

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

// Canvas pixel position (from the window centre, y down) to clip space: whole
// window pixels, `canvasH` canvas pixels to the window height, drawn just in
// front of the camera (layer orders displays: larger is nearer).
vec4 wl_canvas_position(vec2 canvasPos, float canvasH, float layer) {
    vec2 pixel = floor(canvasPos * (ScreenSize.y / canvasH) + 0.5) + floor(ScreenSize * 0.5);
    vec2 ndc = pixel / ScreenSize * 2.0 - 1.0;
    vec4 up = ProjMat * vec4(0.0, 1.0, -1.0, 1.0);
    ndc.y *= -sign(up.y / up.w);
    vec4 front = ProjMat * vec4(0.0, 0.0, -(0.1 - layer), 1.0);
    return vec4(ndc, front.z / front.w, 1.0);
}

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);
    ivec3 mark = ivec3(round(Color.rgb * 255.0));
    bool canvas = false;
#ifndef IS_GUI
    // Tagged wl:px glyphs carry pixel data in the color, so the marker is two
    // exact bytes; one tagged pixel color in 65,536 would be misread.
    if (mark.r == 250 && mark.b == 165 && mark.g > 0) {
        canvas = true;
        // The text renderer puts an even-width line's glyph edges half a canvas
        // pixel off the grid; rows are already on it.
        vec2 canvasPos = floor(vec2(Position.x * 40.0 - 0.5, -Position.y * 40.0) + 0.5);
        gl_Position = wl_canvas_position(canvasPos, 2.0 * float(mark.g), clamp(Position.z, -0.05, 0.05));
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
}
