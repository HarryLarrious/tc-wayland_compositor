#version 330
#extension GL_ARB_separate_shader_objects : require

// Vanilla 26.3 core/position_tex_color.vsh (textured GUI), except that on the
// desktop (wl:desktop.glsl) the HUD around the hotbar and the crosshair are
// not drawn: the desktop has its own taskbar and cursor. Vanilla inlines its
// uniform blocks because the game uses this shader before resource packs
// load; this override only loads with the pack, so it can include them.

#include <minecraft:globals.glsl>
#include <minecraft:dynamictransforms.glsl>
#include <minecraft:projection.glsl>
#include <wl:desktop.glsl>

layout(location = 0) in vec3 Position;
layout(location = 1) in vec2 UV0;
layout(location = 2) in vec4 Color;

layout(location = 0) out vec2 texCoord0;
layout(location = 1) out vec4 vertexColor;

// GUI vertices are in GUI pixels; the GUI projection is orthographic, from
// (0, 0) at the top-left to the GUI size. Hidden: the hotbar, offhand slot,
// XP bar, hearts, food, armor and air (182 + 2 * 29 wide, 50 tall, bottom
// centre), and the crosshair and attack indicator at the centre.
bool wl_hide_hud(vec2 p) {
    if (ProjMat[3][3] != 1.0) {
        return false;
    }
    vec2 gui = vec2(2.0 / ProjMat[0][0], 2.0 / abs(ProjMat[1][1]));
    vec2 d = p - gui * 0.5;
    bool hud = abs(d.x) <= 122.0 && p.y >= gui.y - 50.0;
    bool crosshair = abs(d.x) <= 9.0 && d.y >= -9.0 && d.y <= 14.0;
    return hud || crosshair;
}

void main() {
    gl_Position = ProjMat * ModelViewMat * vec4(Position, 1.0);
    if (wl_desktop_active() && wl_hide_hud((ModelViewMat * vec4(Position, 1.0)).xy)) {
        gl_Position = WL_HIDDEN;
    }

    texCoord0 = UV0;
    vertexColor = Color;
}
