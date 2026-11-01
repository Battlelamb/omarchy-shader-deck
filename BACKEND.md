# Backend operations and limits

## Contract and providers

System `/usr/bin/python3`, standard library, installed `hyprctl`, Hyprland Lua
**0.56.2** only. Other versions fail closed until separately qualified. Backend
and data resolve relative to `__file__`, not cwd; no plugin depends on another.
No installation, default enablement, autostart service or config include is added.
Catalogue is static and has no IPC/state writes; Apply verifies provider/version
and session. Missing providers/session and malformed responses fail with JSON.
No catalogue or selection performs an action.

```
/usr/bin/python3 runtime/0.1.0/backend.py catalog
/usr/bin/python3 runtime/0.1.0/backend.py action --id <known-id> --verb apply --apply
/usr/bin/python3 runtime/0.1.0/backend.py action --id restore:last --verb restore --apply
```

`--apply` is mandatory for every user action. Fresh full membership and strict
fields/types are checked, not a QML row or arbitrary command/path. Catalogue
returns one JSON object with bounded id/label/detail rows, Apply primary and
advertised Restore. Success means normal IPC acknowledgement plus value readback;
failures are nonzero JSON without a traceback. State is never trusted as Lua.

## Inspected supported API

`hyprctl -j version`, `hyprctl -j getoption <dotted-key>` return typed JSON.
Only generated fixed-key `hyprctl eval` code calls `hl.get_config` for guarded
compare-before-write and `hl.config({["known.dotted.key"]=literal})` for settings.
Gap tables use named `top/right/bottom/left`, not positional arrays in Lua.
No `repl`, print, shell evaluation, arbitrary Lua, dispatcher, reload or installer
is invoked. Strings use escaped decimal UTF-8 bytes, not invalid Lua JSON `\u`
escapes. Installed source and pinned matching C++ bindings were inspected before
choosing these methods; exact hashes/receipts are in NOTICE.backend.md.

## Empty shader representation (0.56.2)

`getoption` exposes the raw `Config::STRING`: the default can be `[[EMPTY]]`,
whereas an explicit empty Lua assignment is returned as `""`. The qualified
`CLuaConfigString::push` converts the sentinel to `""` for `hl.get_config`.
The renderer also explicitly treats **both** spellings as disabled before path
resolution. A sentinel is therefore not evidence of a bogus GLSL file open,
and the hypothesis that every Disable must fail readback was not reproduced
with the source-faithful fixture. The demonstrated bug was leaking a transport
spelling into snapshots/comparisons: a same-empty spelling change could falsely
block Restore as an external edit.

The backend uses `""` as the canonical disabled value for reads, new snapshots,
and Lua assignment. All three value dictionaries in an old valid receipt
(`before`, `previous`, `expected`) are normalized in memory after their schema
validation; reading an old receipt does not rewrite it. Legacy active/pending
receipts remain recoverable, including timed Restore. Only the exact sentinel
for the shader key is normalized; malformed values, foreign sessions, invalid
tokens and genuinely divergent external shader paths still fail closed. No
journal, ownership, deadline, persistence or compare-before-write guard is bypassed.
Nonempty shader paths retain their exact spelling and UTF-8 literal escaping.

The fixture separates raw empty transport spelling from actual Lua `""`, switches
to raw literal empty after an explicit empty setter, and records actual generated
Lua assignments. Its earlier sentinel-as-underlying-value model was incorrect.
Qualified source/header hashes, immutable RED/GREEN snapshots and logs,
hash-matched original-backend controls, full-suite/package/diff receipts are in
`release-output/live-empty-fix-1793565123473744123/`. Start with
`api-evidence/interpretation.txt`, `red-qualified-source/`, and the final receipts;
earlier sticky-sentinel runs are preserved but superseded, not compositor evidence.
This investigation used the parent's supplied read-only observation, not a new
live IPC capture. It ran no live setter, install, commit, or other-plugin edit.

## Transaction and recovery

Per-plugin/per-instance files under
`${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-<slug>/<sha256(instance)[:24]>/`.
Plugin/session directories must be user-owned mode 0700, not symlinks. Lock and
state are private. Snapshot is bounded JSON, written using a mode-0600 temporary
file, fsync, atomic replace and directory fsync before mutation. A nonblocking
flock serializes Apply/Restore/Keep. A complete first snapshot retains actual
values across subsequent presets; no fabricated defaults are used for rollback.

A pending journal records both pre-transaction and planned values. Every setter
checks all allowed current values inside compositor Lua; a final readback confirms
success. Partial mutation or post-mutation persistence failure attempts guarded
rollback to the immediately previous runtime values. Active publication uses a
separate record, preserving the pending phase and actual pre-transaction values.
Before any compensating setter, that pending intent must be durably republished,
even if active replacement succeeded before its acknowledgement failed. If intent
persistence fails, no compensating setter runs. Failed rollback retains the
journal. A later explicit Restore can recover interrupted mixed previous/target
values. Active snapshots require exact expected-value agreement. Divergent
external edits cause refusal, not silent overwrite. Unrelated keys are untouched.
Restore accepts the literal `restore:last` alias or any currently known row ID
and restores the **first session snapshot**, not the selected row's defaults.
The alias is valid only with `--verb restore --apply`; Apply/Keep cannot use it.
It resolves to the saved preset identity after the same bounded receipt, session,
lock and external-edit checks, without depending on a visible/filtered UI row.
After successful Restore the snapshot is removed; a second Restore reports no snapshot.

This is value-level optimistic conflict detection, not a global compositor lock:
ABA edits returning to the same values cannot be distinguished. Restoring values
does not restore Hyprland's `setByUser` diagnostic bookkeeping. Config reloads,
external toggle writers or another plugin can cause a deliberate conflict. No
boot/user configuration file is rewritten. IPC/service loss can leave a pending
journal; do not delete it to hide a failure. Resolve differing owned values first
and retry Restore; never force-overwrite an external edit automatically.

## Bounds and verification

Preset JSON and each IPC reply are limited to 64 KiB; at most 64 rows, unique
IDs <=64 chars, labels <=128, details <=512. Each helper call has a 3-second
wall timeout and bounded incremental pipes, and kills its owned process group on
timeout/overflow (including a child that closes stdout then hangs). No stderr or
private response body is dumped to UI. Parent owns the overall 30s action deadline;
a parent hard-kill during a multi-field outage leaves its pending journal for
explicit recovery rather than claiming success. No action test touched live IPC.

Run from this project with an existing approved scratch directory:

```
TMPDIR=/home/leviathan/.hermes/cache/scratch env -u PYTHONPATH /usr/bin/python3 scripts/run-tests.py --backend-only
```

The runner uses offline bwrap, cleared environment, a fresh fake HOME, hidden
/run and real HOME, no display/session sockets, readonly /usr and source. Inside:
`/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v` (no inherited
`PYTHONPATH`).
The fake `hyprctl` executes actual generated code with system Lua against a fake
`hl` object and persists observable fake compositor state. It is logic/transport
fixture evidence, not proof that a real C++ compositor or GPU accepted an effect.

The earlier recovery suite had **75 tests**. Added regressions cover active-save failure
before/after replacement, lost compensation acknowledgement, first/timed/confirmed
previous state, explicit and actual timed recovery, failed pending-intent save
with no compensation setters, and genuine external-edit refusal. Test-owned
callers are group-SIGKILLed after real compensation and before predecessor
republication, including failed clear and Restore removal before/after unlink.
The rearm checks retain the original deadline and recover after rearm failure.
RED/GREEN logs, final frozen sources/hashes and hash-matched old-backend negative
controls are under `release-output/review-r2-1793560487506391914/`. Workspace
Profiles remains unchanged and passes the supplementary recovery control.
Earlier receipts remain immutable historical evidence. These runs use
`env -u PYTHONPATH PATH=/usr/bin /usr/bin/python3 scripts/run-tests.py --backend-only`.
## Shader-specific scope and UI integration

Rows: `disable`, `grayscale`, `warm`. Only `decoration.screen_shader` is mutated.
Fixed bundled GLSL ES 3.00 paths; no discovery of user shaders, includes, metadata
hooks, compilation commands, downloads or damage-tracking changes. Grayscale
uses Rec.709 luma and preserves alpha; warm multiplies RGB by (1, .96, .88) and
preserves alpha. This is not a medical/night-light or colour-management tool.

Applying an effect starts a **15-second trial**. A separate Python process is
started with `start_new_session=True`, closed inherited streams, a minimal
session environment, a random token and a readiness handshake BEFORE any setter.
Readiness is written privately, closed, then published by an exclusive atomic
hard link: an empty/partial PID record is never announced. Existing wrong-PID or
symlink records are refused, not overwritten. The caller removes handshake files;
a late unpublished child also cleans its own record on exit. Hard-killing the
watchdog itself can still leave a private temporary/ready file; it grants no
authority without the matching journal token.
Its saved deadline is monotonic. It is not QML-owned and survives the caller's
exit or SIGKILL of the caller's entire process group (tested at the real 15s).
A daemon reaper thread in a still-alive caller only reaps the handle; the child
watchdog itself is independent of that thread and caller lifetime.

Parent UI advertises `apply`, `restore`, `confirm`. Keep effect must call:

```
/usr/bin/python3 backend.py action --id <current-selected-id> --verb confirm --apply
```

Only the matching current unexpired effect can be confirmed, after compositor
readback under the same lock. Confirmation removes the timer token durably and
retains the original Restore snapshot; it does not create startup persistence.
Expired/wrong/absent trials fail, never claim success. A failed Keep save rearms
the original deadline or attempts restoration. Failed switches rearm the previous
trial without extending its original deadline. Pending Restore and clear journals
retain the current token, PID and deadline; a pending switch retains predecessor
authority until a ready successor is published. Compensation preserves that
current independent owner in the immutable pending intent, including after an
active replacement or clear retired the on-disk token. It stays actionable while
the predecessor is rearmed; failed rearming does not strand compensated values.
Failed timed Restore leaves the same watchdog authorized to retry when IPC returns.

Replacement startup does not publish its new token: the candidate first checks
the session/state and announces readiness independently. Only then does the
locked caller atomically publish the successor token/PID/deadline, before any
setter. The candidate cannot mutate until it obtains the action lock and checks
both published ownership and expiry. A kill after the pending journal write,
before spawn, during blocked candidate startup, or after readiness but before
publication leaves the original owner/deadline intact. A completed switch gets
its new trial deadline; old callbacks cannot undo it. A clear retires ownership
only after successful setter/readback and active-state persistence; Restore
retires it by removing the journal after readback. Successful Keep also retires
ownership explicitly, while retaining the original Restore baseline.

Emergency explicit clear (not confirmation):

```
/usr/bin/python3 backend.py action --id disable --verb apply --apply
```

Clear retains the first snapshot for explicit Restore, but is not auto-reverted.
The watchdog waits up to 30s for an in-flight action lock after expiry and retries
transient restore failures four times; every individual IPC call is capped at 3s.
Divergent external edits are never overwritten. Compositor loss, OS/process kill,
unavailable old shader file, unrecoverable storage or a persistently busy lock
can prevent restoration: recoverable snapshot remains for explicit Restore.
A successful setter/readback confirms the stored option, **not GPU compilation
or visible colour/readability**. Those remain unverified pending parent's real
private headless-compositor/GPU qualification. No live setter was run here.

## Not qualified here

No compositor setters, GUI, live installation/enabling, packages or publication were performed. Parent owns native Qt/QML, packaging and headless-compositor/GPU qualification. Shim tests are not GPU/readability evidence. RED and GREEN receipts, including earlier failures, remain immutable.
