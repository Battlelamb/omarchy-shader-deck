#version 300 es
// SPDX-License-Identifier: GPL-3.0-only
// Original fixed Shader Deck transform; no external resources.
precision highp float;
in vec2 v_texcoord;
out vec4 fragColor;
uniform sampler2D tex;
void main() {
    vec4 pix = texture(tex, v_texcoord);
    fragColor = vec4(pix.rgb * 0.65, pix.a);
}
