# Shader Deck backend · v0.4.0

## Commands, fixed effects and intensity

Exact advertised actions: `apply`, `restore`, `confirm` (Keep), `favorite`, `preview`, `compare`. Every nonempty Apply/Preview is a 15-second independent trial. `disable` or intensity zero clears the shader without a trial, retaining explicit Restore. No capture/import/export of arbitrary GLSL or output paths is supported.

```
/usr/bin/python3 runtime/0.4.0/backend.py catalog
/usr/bin/python3 runtime/0.4.0/backend.py preferences --apply --payload '{"options":{"intensity":50}}'
/usr/bin/python3 runtime/0.4.0/backend.py action --id cool --verb compare --apply
/usr/bin/python3 runtime/0.4.0/backend.py action --id cool --verb preview --apply
/usr/bin/python3 runtime/0.4.0/backend.py action --id cool --verb confirm --apply
/usr/bin/python3 runtime/0.4.0/backend.py action --id restore:last --verb restore --apply
```

The only compositor option is `decoration.screen_shader`. Built-in IDs: `disable`, `grayscale`, `warm`, `cool`, `sepia`, `softcontrast`, `dim`. Preset markers resolve only to those bounded bundled `.frag` files. Shader path strings read for baseline recovery are not an import interface. The `[[EMPTY]]` transport spelling canonicalizes to empty in reads, writes and validated legacy snapshots in memory; legacy receipts are not silently rewritten.

Preference `intensity` is integer 0–100, default 100. Settings writes do not reapply effects. Full intensity uses the bundled program; zero resolves to disabled; intermediate strengths generate only a fixed-template RGB mix with a two-decimal literal. Programs preserve sampled alpha. Generated code is at most 16 KiB and lives in private session state as `shader-<sha256(bytes)>.frag`. Exclusive hard-link publication avoids partial visibility or replacing an existing edited file. Before reuse, current-value reads and every setter (including Restore and compensation), the owned generated file's mode, owner, link count, bytes, size and content hash are checked. Conflicts preserve the bytes and journal. There is a finite effect × integer-intensity space; files are retained for recoverable references, not automatically deleted.

`compare` is read-only and returns `{ok,message,preview,detail}` pointing to a bundled full-strength CPU reference PNG. Catalogue rows expose the same absolute local PNG. Images are measured original color-bar/gray-ramp comparisons with original left/effect right and on-image **NOT GPU** labels. They do not depict current intensity, live windows, color-managed HDR output or compositor acceptance. New cool/sepia/softcontrast/dim filters and reference charts are project-authored; grayscale retains its documented HyDE lineage.

Tests use the real installed offline `glslangValidator` on all fixed shaders and generated strengths 1/50/99/100, with an invalid GLSL negative control. ImageMagick decodes charts for measured pixel assertions; both tools are development-only prerequisites, not runtime dependencies. **Real isolated compositor/GPU rendering remains pending parent qualification**; offline syntax/reference passes are never a GPU pass.

## CPU comparison scene

Saved `comparisonScene` is enum `color-bars` (default) / `grayscale-ramp`.
Catalogue and Compare resolve the same fixed full-strength reference chart:
`data/comparisons/<known-shader>.png` for color bars, or
`data/comparisons/grayscale-ramp/<known-shader>.png` for grayscale input.
Only fresh bundled shader IDs reach this selector; callers cannot supply paths.
Compare refuses missing/symlink reference files and performs no compositor IPC
or writes. Both scenes show original left / fixed 100% transform right, with
on-image NOT GPU labels. They are CPU reference artwork, never live GPU output,
current-intensity rendering, HDR or color-management qualification.

Scene configuration does not modify shader source, intensity generation,
watchdog admission, deadlines, setters or recovery records. Original default
charts remain byte-identical. Pixel controls use the existing independent
transform oracle on known grayscale input levels as well as old color samples.

```
/usr/bin/python3 runtime/0.4.0/backend.py preferences --apply --payload '{"options":{"comparisonScene":"grayscale-ramp"}}'
/usr/bin/python3 runtime/0.4.0/backend.py action --id cool --verb compare --apply
```

## Provider and trust boundary

System `/usr/bin/python3`, Python standard library and installed `hyprctl`; the adapter is qualified for **Hyprland Lua 0.56.2 only** and rejects other versions. Runtime paths derive from `__file__`, never cwd. Each package includes its own runtime helpers; no sibling plugin is required. Native shell code is unsandboxed at runtime; the development runner is not a runtime security sandbox.

Only `hyprctl -j version`, `hyprctl -j getoption <allowlisted dotted key>` and generated fixed-key `hyprctl eval` are used. Generated Lua uses `hl.get_config` for compare-before-write and `hl.config({[known_key]=typed_literal})` for mutation. Gap tables have named `top/right/bottom/left` fields. Strings use decimal-escaped UTF-8 bytes. No `repl`, bare print, arbitrary Lua, shell evaluation, dispatcher, installer, reload or configuration-file rewrite is used.

Every write/action requires `--apply`; success is JSON with `ok:true`, failure is nonzero JSON with plain bounded text and no traceback. Unexpected options, inappropriate payloads and invalid membership fail closed. CLI payloads are JSON objects limited to **16384 UTF-8 bytes**; duplicate keys, nonfinite numbers, malformed Unicode and nesting beyond 12 levels are rejected. ID strings never become commands or output paths. Catalogue reads do no IPC or writes and expose fresh rows, `preferences` and `settingsSchema`.

## v0.4.0 display preferences

The exact enum keys are `density` (`comfortable` default, `compact`), `layout`
(`list` default, `grid`), and `sortOrder` (`default` default, `name`,
`favorites-first`). They affect native catalogue presentation only. Existing
stores without these keys receive defaults without an implicit write; Reset
returns those defaults. The UI owns stable sorting and fresh action admission.
All settings writes remain local preference operations, never compositor setters.

## Preferences

`PREFERENCE_SCHEMA` is passed to the bundled `preferences.py` helper's exact `read`, `change`, `reset`, `toggle`, `remember` APIs. Storage is `${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/lego/<slug>/preferences.json`, outside the installed source. The helper bounds reads, rejects unsafe files/ancestor symlinks, locks updates and uses fsync plus atomic replacement. Corrupt preferences are not silently reset.

```
/usr/bin/python3 runtime/0.4.0/backend.py preferences
/usr/bin/python3 runtime/0.4.0/backend.py preferences --apply --payload '{"reset":true}'
/usr/bin/python3 runtime/0.4.0/backend.py preferences --apply --payload '{"favorites":["known-id"],"collections":{"Desk":["known-id"]}}'
```

Reads return `{ok,preferences,settingsSchema,message}`. Patches accept only `options`, `favorites`, `collections`; recent/version cannot be written. Reset is the sole-key `{reset:true}` request and resets **only preferences**, never custom presets, generated effects or transaction journals. Favorites may retain stale IDs inertly; Favorite actions require fresh membership. Recents update only after confirmed Apply/Preview/export. If recent persistence fails after an externally confirmed action, success remains truthful with a warning rather than reporting an invented action failure.

## Transaction and Restore invariants

Journals live under `${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-<slug>/<sha256(instance)[:24]>/`. Plugin and session directories must be user-owned private directories, not symlinks. A nonblocking flock serializes transactions. A bounded pending journal is fsynced and atomically replaced before any setter, retaining the first actual `before`, immediately previous actual values and planned target. A final compositor readback confirms success.

Each setter guards all owned current values inside compositor Lua. Partial failures compensate only values this transaction could have written, in reverse order. Active publication uses a separate record: it cannot mutate the in-memory pending intent. Before compensation, that original pending intent must be durably republished even when active replace succeeded but acknowledgement/fsync failed. If that persistence fails, no compensating setter runs. Lost compensation acknowledgement leaves a pending journal recoverable from the real previous/target mixture, not a fabricated baseline. Failed compensation retains the receipt and reports failure.

Restore accepts any freshly known row or the exact `restore:last` alias, **only with Restore**. It follows the validated receipt even if the active custom preset is no longer in the visible search. Active state must exactly match expected values; interrupted pending state accepts only per-key previous/target mixtures. Divergent external values block Restore/timeout without clobbering the values or journal. Unrelated options remain untouched. Successful Restore removes the receipt; a second Restore fails honestly.

This is optimistic value-level conflict detection, not a global compositor lock. Same-value **ABA edits cannot be distinguished**. Restore does not restore `setByUser` diagnostics or undo arbitrary normal provider side effects. External writers, another plugin and config reloads may create deliberate conflicts. Resolve those explicitly and retry Restore; do not delete a journal to hide failure.

Each IPC reply and preset/journal read is bounded to 64 KiB. JSON file reads use nofollow/nonblocking descriptors, require regular files, check metadata stability, reject duplicates/nonfinite/deep JSON and read at most cap+1. Each helper call has a three-second wall timeout, incremental output cap and owned-process-group kill, including helpers that close stdout then hang. Overall UI cancellation/watchdog admission belongs to the native controller; accepted external work cannot be revoked by closing a panel.

## Offline verification

Run from this checkout, with an existing approved private scratch directory:

```
TMPDIR="${TMPDIR:?Set an existing private scratch directory}" env -u PYTHONPATH PATH=/usr/bin /usr/bin/python3 scripts/run-tests.py --backend-only
```

The shipped runner uses offline bwrap, unshared network, cleared environment, fresh fake HOME, hidden real HOME and `/run`, no live display/compositor sockets, read-only source/system files and fake IPC. The fake `hyprctl` executes generated Lua with the installed system Lua against an observable fake `hl` object. This proves logic/transport, not C++ compositor/GPU integration. Full native/component gate: `bash test.sh` with the same TMPDIR. Historical 0.3.0 counts, commands, source hashes and RED/GREEN receipts are held in private ignored `release-output/v030-result.json`, which is not shipped or required by the documented runners; old validation receipts remain historical rather than overwritten.

## Independent timed preview

The watchdog is a detached, separately session-owned `/usr/bin/python3 backend.py watchdog --token <32 lowercase hex>` process, not a QML timer. It announces complete PID bytes using private temporary-file plus exclusive hard-link readiness publication. A replacement token/PID/deadline is published only after independent readiness. The predecessor's authority/deadline remain durable during pending transactions and spawn/unready/ready-before-publication boundaries.

Pending compensation preserves the current ready owner's token/PID/deadline. Predecessor rearming preserves its original deadline rather than extending it; a failed rearm retains the successor's pending authority. Keep verifies the matching unexpired current row, exact readback and durable receipt readback before retiring timer authority; failed Keep rearms or restores. Restore/disable retire authority only after confirmed readback. Superseded tokens do nothing. Temporary IPC loss gets bounded retry; unresolved IPC/external conflicts retain the journal for explicit Restore. The process cannot survive logout, missing runtime files or an inaccessible compositor indefinitely. It is recovery, not a promise to overwrite external edits or recover from arbitrary host failure.

New preference writes have a separate aggregate limit of **128 KiB compact UTF-8
JSON**, checked under the store lock before mutation; rejection preserves existing
bytes. Per-field counts and the 16384-byte CLI payload limit do not increase that
aggregate. Legacy reads remain bounded to **16 MiB** and fully schema-validated,
allowing explicit Reset to shrink old valid stores without touching custom presets
or recovery journals. Reply JSON must be **strictly below 1 MiB** after UTF-8
serialization; with its terminating LF, the wire reply is **at most 1 MiB**,
matching the inclusive UI collector/parser budget. Oversized read snapshots fail
cleanly; an already confirmed action omits its optional preference snapshot with
a warning instead of fabricating an external-action failure. Ordinary preference
patches refuse an already oversized snapshot before mutation; explicit Reset
remains available.
