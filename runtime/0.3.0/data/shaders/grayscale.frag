#version 300 es
// SPDX-License-Identifier: GPL-3.0-only
// Reduced fixed Rec.709 mode adapted from pinned HyDE grayscale.frag; see NOTICE.backend.md.
precision highp float;
in vec2 v_texcoord;
out vec4 fragColor;
uniform sampler2D tex;
void main() {
    vec4 pix = texture(tex, v_texcoord);
    float gray = dot(pix.rgb, vec3(0.2126, 0.7152, 0.0722));
    fragColor = vec4(vec3(gray), pix.a);
}
