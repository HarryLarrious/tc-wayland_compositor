#version 330
#extension GL_ARB_separate_shader_objects : require

// Vanilla 26.3 core/text.fsh, except pixel glyphs (wl:px.glsl): they are
// drawn in the color their word decodes to, full bright and without fog,
// over the whole glyph quad. Other text renders exactly as vanilla.

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
#include <minecraft:fog.glsl>
#endif

#include <minecraft:dynamictransforms.glsl>
#include <minecraft:oit.glsl>
#include <wl:px.glsl>

uniform sampler2D Sampler0;

#if !defined(IS_GUI) && !defined(IS_SEE_THROUGH)
layout(location = 0) in float sphericalVertexDistance;
layout(location = 1) in float cylindricalVertexDistance;
#endif

layout(location = 2) in vec4 vertexColor;
layout(location = 3) in vec2 texCoord0;
layout(location = 4) in vec4 rawColor;
layout(location = 5) in float spriteKey;

#ifndef OIT_ALPHA_ONLY
layout(location = 0) out vec4 fragColor;
#endif

vec4 calculateFinalColor(vec4 color) {
    #ifdef OIT_ACCUMULATE
    color = sampleColorForAccumulation(color);
    #endif

    #if !defined(IS_SEE_THROUGH) && !defined(IS_GUI)

    #ifdef OIT_ACCUMULATE
    vec4 fogColor = vec4(FogColor.rgb * color.a, FogColor.a);
    #else
    vec4 fogColor = FogColor;
    #endif

    color = apply_fog(color, sphericalVertexDistance, cylindricalVertexDistance, FogEnvironmentalStart, FogEnvironmentalEnd, FogRenderDistanceStart, FogRenderDistanceEnd, fogColor);
    #endif

    return color;
}

vec4 calculatePixelColor(vec4 color) {
    #ifdef OIT_ACCUMULATE
    color = sampleColorForAccumulation(color);
    #endif
    return color;
}

void main() {
    bool pixel = false;
    vec4 color;
    #ifdef IS_GRAYSCALE
    color = texture(Sampler0, texCoord0).rrrr * vertexColor * ColorModulator;
    #else
    vec4 texColor = texture(Sampler0, texCoord0);
    vec4 decoded = wl_px_decode(texColor, rawColor, pixel);
    // Sprites and the cursor (text.vsh) are clear where they are pure black.
    if (pixel && spriteKey > 0.5 && decoded.rgb == vec3(0.0)) {
        discard;
    }
    color = pixel ? decoded : texColor * vertexColor * ColorModulator;
    #endif

    if (color.a < 0.1) {
        discard;
    }

    #ifdef OIT_ALPHA_ONLY
    executeAlphaOnlyPhase(gl_FragCoord.z, color.a);
    #else
    fragColor = pixel ? calculatePixelColor(color) : calculateFinalColor(color);
    #endif
}
