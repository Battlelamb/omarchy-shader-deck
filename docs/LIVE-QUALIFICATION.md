# leviathan.shader-deck: workstation live qualification

Recorded 2026-11-02; local candidate only, not published or marketplace-approved.

Final live qualification: **passed within the scope below**. Independent fix reviews and real Apply/Restore gates passed; earlier failed attempts are retained.

## Executed scope

- Installed/enabled from reviewed local source with exact runtime hashes, no shell/compositor restart.
- Real native wide-layout UI, populated catalogue, search/actions and open/close surface lifetime exercised on DP-2. Initial catalogue observed 3 rows; displayed matches remain capped and palette extraction is budgeted.
- Direct shortcut: **Super+Ctrl+Alt+9** (physical number row). Real input opens this overlay; original Super+D remains Native Overview.
- Offline regression checkpoint: **27 Node, 88 backend, 23 native process cases**; exact run/source/commit receipts are outside Git in release-output and the parent deployment record.

The reviewed empty-value canonicalization fix passed real session tests: clear/Restore from empty, grayscale with captured saturation falling from 0.583837 to 0, independent timed rollback in 15.398 s, warm Keep surviving the trial deadline, and explicit Restore. Captured warm RGB means matched multipliers (1, .96, .88) within .002. Original disabled-shader value was restored. This is real GPU pixel evidence, not calibration, color-management or medical certification.

## Limits and cleanup

Private compact-layout checks are separate from the live wide-layout pass. Native RTL/fractional scaling, all-output combinations, IME/full accessibility, screen-lock races, upgrades, long soak, hostile-media certification, physical power loss and hosted CI remain unqualified. Storage/IPC failure, genuine external edits or killing an independent watchdog can still prevent recovery. Cancellation cannot undo accepted external work or own escaped groups. The earlier whole-shell resource gate remains failed and is not superseded here; no speedup/FPS/steady-state memory claim.

The independent fix reviews, new local commits, installed hashes, actual action/pixel readbacks, restoration records and retained failure logs are in the parent deployment evidence. No raw clipboard data, credentials or recovery material was logged. A game initially appeared on workspace1 during a direct-launch retry and was immediately moved to empty3; its later scoped capture confirms the menu. Isolated Hyprland config-verifier processes segfaulted on both unchanged baseline and candidate; the actual compositor PID1511 and shell stayed alive. Native live reload/configerrors and actual keyboard tests were used, without pretending the offline verifier passed.
