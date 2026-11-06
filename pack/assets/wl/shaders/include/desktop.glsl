#ifndef WL_DESKTOP_GLSL
#define WL_DESKTOP_GLSL

// The desktop flag. While the compositor runs, its player sits on a seat at
// block fraction 0.123 in x and 0.456 in z (wm.tc, wmStart), so the camera is
// there too. Globals.CameraOffset is floor(camera) - camera, the same in
// every pipeline (world and GUI), so any shader can tell the desktop is up.
// Callers include <minecraft:globals.glsl> first.

const vec2 WL_DESK_FRACTION = vec2(0.123, 0.456);

bool wl_desktop_active() {
    vec2 fraction = -CameraOffset.xz;
    return all(lessThan(abs(fraction - WL_DESK_FRACTION), vec2(0.002)));
}

// A clip position outside the view: every vertex moved here draws nothing.
const vec4 WL_HIDDEN = vec4(2.0, 2.0, 2.0, 1.0);

// First-person hand and held item: drawn within a block or so of the camera
// (entity and item pipelines). On the desktop nothing else is that close.
bool wl_hide_near(vec3 position) {
    return wl_desktop_active() && dot(position, position) < 4.0;
}

#endif
