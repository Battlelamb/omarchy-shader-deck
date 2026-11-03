# Backend source and asset notice

SPDX-License-Identifier: GPL-3.0-only

Pinned donor: HyDE-Project/HyDE, commit `fa2fd57afc7203b1b5653d3271f3a57ea3873f97`.
Repository licence: GNU GPL v3; the full licence is included in `LICENSE`.

grayscale.frag is a reduced fixed Rec.709 mode adapted from the pinned GPL HyDE grayscale.frag, retaining the GLSL sampler/input/output/alpha behavior and luma coefficients. warm.frag is ORIGINAL project code, not a donor asset: it uses fixed channel multipliers. The HyDE blue-light-filter shader points to Hyprland issue commentary, Shadertoy and BlenderArtists provenance; that third-party approximation was inspected but NOT copied, because repository-level GPL alone does not resolve those embedded third-party rights. Selector explicit-set, transactional restore and token invalidation behavior are adapted from the GPL shaders.lua design; the detached watchdog protocol is new Python project code.

## Exact inspected sources

- `https://raw.githubusercontent.com/HyDE-Project/HyDE/fa2fd57afc7203b1b5653d3271f3a57ea3873f97/Configs/.local/lib/hyde/shaders.lua` — SHA-256 `f360a23ab37a68af64adfc17a086eeab248620099ea42a7ee71efcbb9312f178`.
- `https://raw.githubusercontent.com/HyDE-Project/HyDE/fa2fd57afc7203b1b5653d3271f3a57ea3873f97/Configs/.local/lib/hyde/rofi.shaders.lua` — SHA-256 `7221f2c746435d756e3083512494e6d55e2efe14d00991f912feb84b95994b59`.
- `https://raw.githubusercontent.com/HyDE-Project/HyDE/fa2fd57afc7203b1b5653d3271f3a57ea3873f97/Configs/.config/hypr/shaders/grayscale.frag` — SHA-256 `cd72cfcc653342f78b3cd9dcd544e40903fab70d951a52717f97177e0a331db2`.
- `https://raw.githubusercontent.com/HyDE-Project/HyDE/fa2fd57afc7203b1b5653d3271f3a57ea3873f97/Configs/.config/hypr/shaders/blue-light-filter.frag` — SHA-256 `b576f516ebc1cb3aafe8e50851f2d749b23519606679005f004d14a6f5044e44`.
- `https://raw.githubusercontent.com/HyDE-Project/HyDE/fa2fd57afc7203b1b5653d3271f3a57ea3873f97/LICENSE` — SHA-256 `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`.
- `/usr/share/omarchy/bin/omarchy-hyprland-toggle` — SHA-256 `32a6ea6bef5529f26f0c0ab836380e1f1ba48b6fb2cbcbea5d0a1a46d37f4f7a`.
- `/usr/share/omarchy/default/hypr/looknfeel.lua` — SHA-256 `4eed2dc9f3ec4d6697c4347cb76fc47e052c1220e97fa03a5385ef9e8831ddb1`.
- `/usr/share/omarchy/default/hypr/toggles/no-animations.lua` — SHA-256 `2ff210d9d1eaf5ed5009e618968ca6490894d423dbbb8acf231ea4683a437486`.
- `/usr/share/hypr/stubs/hl.meta.lua` — SHA-256 `0c3f4c7ef6dab084437ef3b6956b5e268c1ae80271e9b375aa77254047ff851a`.
- `/usr/include/hyprland/src/version.h` — SHA-256 `dbedffa593494a4f610d8a8eaac5a32c2daed3e2e0998f47d875587370397c58`.
- `https://raw.githubusercontent.com/hyprwm/Hyprland/efb50993780079460b0cbed1363e2166a2de1d9f/src/debug/HyprCtl.cpp` — SHA-256 `798b7c6c4c1684557842463d46ac99c96629be4179e0e461dca77670247b91fa`.
- `https://raw.githubusercontent.com/hyprwm/Hyprland/efb50993780079460b0cbed1363e2166a2de1d9f/src/config/lua/ConfigManager.cpp` — SHA-256 `94b5c6891326e7a3e490019d26fd9d6f5b3137fb5318a94dff0a6cb6dfdaf502`.
- `https://raw.githubusercontent.com/hyprwm/Hyprland/efb50993780079460b0cbed1363e2166a2de1d9f/src/config/lua/bindings/LuaBindingsConfigRules.cpp` — SHA-256 `157c3e45b364f3e41b6fd7cf13fd19e7477e8c03a6a75c6c46fde5e2b5715be9`.
- `https://raw.githubusercontent.com/hyprwm/Hyprland/efb50993780079460b0cbed1363e2166a2de1d9f/src/config/lua/types/LuaConfigCssGap.cpp` — SHA-256 `ac91c9593a04ff96274cb6fcb46c62e996845cc03086dd0e831b5aa1d0515423`.
- `https://raw.githubusercontent.com/hyprwm/Hyprland/efb50993780079460b0cbed1363e2166a2de1d9f/src/config/lua/types/LuaConfigString.cpp` — SHA-256 `7f4cb8035764a7a65833bdc4f0ab0d54c4014ee336f5a7075f37ad1301ac1420`.

Installed Omarchy and Hyprland files are read-only API references, not vendored runtime code. Hyprland source is pinned to the installed version-header commit. No donor installer/init, arbitrary Lua, third-party temperature approximation, font, wallpaper or ambiguous dataset is shipped. Python adapter/tests and the warm filter are new GPL-3.0-only project code. Private source snapshots are not runtime dependencies.

## v0.3.0 programs and comparison artwork

`data/shaders/cool.frag`, `sepia.frag`, `softcontrast.frag`, `dim.frag` are original
project-authored fixed transforms, GPL-3.0-only. Intensity generation only mixes
those fixed outputs with the original RGB; grayscale retains its lineage above.
No third-party temperature approximation or arbitrary GLSL import was added.

The six `data/comparisons/*.png` files are original synthetic color-bar/gray-ramp
CPU reference compositions, not screenshots, desktop captures or GPU evidence.
Their labels explicitly distinguish original/effect and NOT GPU. They contain
no third-party wallpaper or app artwork. Pixel values are checked with actual
ImageMagick decoding; PNG CRCs/chunks were inspected, with only IHDR/IDAT/IEND.
The deterministic generation script and hashes are kept in ignored evidence.

Raster labels use the installed Liberation Sans font; no font file is bundled.
Digitized data copyright (c) 2010 Google Corporation (reserved names Arimo,
Tinos, Cousine); copyright (c) 2012 Red Hat, Inc. (reserved name Liberation).
Installed `/usr/share/licenses/ttf-liberation/LICENSE` was read in full: SIL Open
Font License 1.1 explicitly excludes created documents from its font-software
redistribution requirement. Font SHA-256:
`baccc64becc3eb7d104b7c84d99f5314a0a1f896e2b3ea6c2f22fc08d2003bee`;
license SHA-256:
`93fed46019c38bbe566b479d22148e2e8a1e85ada614accb0211c37b2c61c19b`.
This notice distinguishes rendered chart artwork from font software; it is not
a claim to redistribute font outlines or reserved font names.

## v0.4.0 grayscale reference scene

The six `data/comparisons/grayscale-ramp/*.png` compositions are new
project-authored CPU references, GPL-3.0-only. Input swatches are fixed neutral
levels 0/64/128/192/255; the right half applies the same fixed full-strength
transforms. Original/effect and NOT GPU labels are rasterized with the same
Liberation Sans font described above; no font file or third-party artwork is
bundled. These are not GPU captures or live-desktop evidence. Existing shader
and donor attribution is unchanged.
