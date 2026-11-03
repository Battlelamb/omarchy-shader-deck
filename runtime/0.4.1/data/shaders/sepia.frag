#version 300 es
// SPDX-License-Identifier: GPL-3.0-only
// Original fixed Shader Deck transform; no external resources.
precision highp float;
in vec2 v_texcoord;
out vec4 fragColor;
uniform sampler2D tex;
void main() {
    vec4 pix = texture(tex, v_texcoord);
    fragColor = vec4(clamp(vec3(dot(pix.rgb, vec3(0.393, 0.769, 0.189)), dot(pix.rgb, vec3(0.349, 0.686, 0.168)), dot(pix.rgb, vec3(0.272, 0.534, 0.131))), 0.0, 1.0), pix.a);
}
