#version 300 es
// SPDX-License-Identifier: GPL-3.0-only
// Original Shader Deck constant-channel filter, not HyDE's third-party temperature shader.
precision highp float;
in vec2 v_texcoord;
out vec4 fragColor;
uniform sampler2D tex;
void main() {
    vec4 pix = texture(tex, v_texcoord);
    fragColor = vec4(pix.rgb * vec3(1.0, 0.96, 0.88), pix.a);
}
