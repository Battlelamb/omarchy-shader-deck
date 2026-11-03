import importlib.util
import pathlib
import unittest

import json
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / pathlib.Path(json.loads((ROOT / 'manifest.json').read_text())['entryPoints']['overlay']).parent
spec = importlib.util.spec_from_file_location("backend", RUNTIME / "backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

class BackendTests(unittest.TestCase):
    def setUp(self):
        import tempfile, os, json
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = pathlib.Path(self.temp.name)
        self.shim = self.home / 'bin'
        self.shim.mkdir()
        tool = self.shim / 'hyprctl'
        tool.write_bytes((ROOT / 'tests/hyprctl_fixture.py').read_bytes())
        tool.chmod(0o755)
        self.original = {
            'animations.enabled': True, 'animations.workspace_wraparound': False,
            'general.gaps_in': [2,3,4,5], 'general.gaps_out': [7,8,9,10],
            'general.border_size': 4, 'decoration.rounding': 11,
            'decoration.blur.enabled': True, 'decoration.shadow.enabled': True,
            'decoration.screen_shader': '/old/example.frag', 'unrelated': 'keep'
        }
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        self.env = {'HOME': str(self.home), 'PATH': str(self.shim)+':/usr/bin',
                    'XDG_STATE_HOME': str(self.home / 'state'),
                    'HYPRLAND_INSTANCE_SIGNATURE': 'private_fixture_123',
                    'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}

    def cli(self, *args, extra=None):
        import subprocess, json
        p = subprocess.run(['/usr/bin/python3', str(RUNTIME / 'backend.py'), *args],
                           env=dict(self.env, **(extra or {})), capture_output=True, timeout=25)
        self.assertLess(len(p.stdout), 1048576)
        self.assertEqual(p.stderr, b'', p.stderr)
        return p.returncode, json.loads(p.stdout)

    def confirm_trial(self, row):
        import time
        path = next((self.home / 'state').rglob('transaction.json'))
        receipt = path.read_bytes()
        assignments = (self.home / 'assignments.jsonl').read_bytes()
        limit = min(time.monotonic() + 2, json.loads(receipt)['deadline'])
        while True:
            calls = (self.home / 'calls.jsonl').read_bytes()
            code, result = self.cli('action', '--id', row, '--verb', 'confirm', '--apply')
            if (code, result) != (1, {'ok': False, 'message': 'Another preset action is in progress; retry'}):
                self.assertEqual(code, 0, result)
                self.assertTrue(result['ok'], result)
                return result
            # Busy is pre-admission, not a failed Keep; no option read, setter or journal write.
            self.assertEqual(path.read_bytes(), receipt)
            self.assertEqual((self.home / 'assignments.jsonl').read_bytes(), assignments)
            delta = (self.home / 'calls.jsonl').read_bytes()[len(calls):]
            self.assertEqual([json.loads(line) for line in delta.splitlines()], [['-j', 'version']])
            self.assertLess(time.monotonic(), limit, result)
            time.sleep(0.01)

    def values(self):
        import json
        return json.loads((self.home / 'compositor.json').read_text())

    def test_restore_alias_restores_receipt_not_selected_row(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertNotEqual(self.values(), self.original)
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertEqual(self.values(), self.original)
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))

    def test_legacy_oversized_preferences_cannot_block_confirmed_apply_or_restore(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True):
            prefs = backend.preferences.change(backend.SLUG, backend.PREFERENCE_SCHEMA, {})
        ids = [str(i).zfill(3) + 'x' * 200 for i in range(512)]
        prefs['collections'] = {'group-' + str(i): ids for i in range(16)}
        path = self.home / '.config/omarchy/lego' / backend.SLUG / 'preferences.json'
        raw = json.dumps(prefs).encode('utf-8')
        self.assertGreater(len(raw), 1048576)
        self.assertLess(len(raw), 16777216)
        path.write_bytes(raw)  # Legacy disk fixture, not a newly permitted oversized write.
        for command in ['preferences', 'catalog']:
            code, result = self.cli(command)
            self.assertNotEqual(code, 0, result)
            self.assertIn('limit', result['message'].lower())
        ident = backend.load_rows()[0]['id']
        code, result = self.cli('action', '--id', ident, '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertIn('warning', result['message'].lower())
        self.assertNotEqual(self.values(), self.original)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        self.assertEqual(path.read_bytes(), raw)

    def test_restore_alias_without_receipt_cannot_claim_success(self):
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('No snapshot', result['message'])
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'eval-count').exists())

    def test_restore_alias_is_exact_explicit_restore_only(self):
        for ident, verb, apply in [('restore:last', 'apply', True), ('restore:last', 'confirm', True),
                                   ('restore:last ', 'restore', True), ('restore:LAST', 'restore', True),
                                   ('restore:last', 'restore', False)]:
            args = ['action', '--id', ident, '--verb', verb] + (['--apply'] if apply else [])
            code, result = self.cli(*args)
            self.assertNotEqual(code, 0)
            self.assertFalse(result['ok'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())
        self.assertEqual(self.values(), self.original)

    def test_restore_alias_preserves_external_edit_and_receipt(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        receipt = path.read_bytes()
        count = (self.home / 'eval-count').read_bytes()
        edited = self.values()
        key = next(iter(row['settings']))
        value = edited[key]
        edited[key] = not value if type(value) is bool else (99 if type(value) is int else ([99]*4 if type(value) is list else '/external.frag'))
        (self.home / 'compositor.json').write_text(json.dumps(edited))
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('conflict', result['message'].lower())
        self.assertEqual(self.values(), edited)
        self.assertEqual(path.read_bytes(), receipt)
        self.assertEqual((self.home / 'eval-count').read_bytes(), count)

    def test_restore_alias_requires_valid_bounded_session_receipt(self):
        import copy, json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        good = json.loads(path.read_text())
        invalid = []
        missing_id = dict(good); del missing_id['id']; invalid.append(missing_id)
        invalid.extend([dict(good, id=[]), dict(good, instance='foreign_session'), dict(good, phase='bad')])
        bad_values = copy.deepcopy(good); bad_values['before']['exec'] = 'bad'; invalid.append(bad_values)
        contents = [json.dumps(record).encode() for record in invalid] + [b' ' * 65537]
        before, count = self.values(), (self.home / 'eval-count').read_bytes()
        for content in contents:
            with self.subTest(receipt=content[:80]):
                path.write_bytes(content)
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                self.assertNotEqual(code, 0)
                self.assertFalse(result['ok'])
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(self.values(), before)
                self.assertEqual((self.home / 'eval-count').read_bytes(), count)
        path.write_text(json.dumps(good))
        moved = self.home / 'owned-receipt.json'; path.rename(moved); path.symlink_to(moved)
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(moved.read_text()), good)
        self.assertEqual(self.values(), before)

    def test_explicit_apply_then_restore_actual_values(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['ok'])
        self.assertNotEqual(self.values(), self.original)
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_partial_failure_rolls_back_actual_values(self):
        row = backend.load_rows()[0]
        fail = '2' if backend.SLUG == 'workspace-profiles' else '1'
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FAIL_AT': fail, 'FIXTURE_FAIL_AFTER': '1'})
        self.assertNotEqual(code, 0)
        self.assertFalse(result['ok'])
        self.assertEqual(self.values(), self.original, 'partial mutation was not rolled back')
        self.assertIn('rollback', result['message'].lower())

    def test_external_edits_block_restore_without_clobbering(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        changed = self.values()
        key = next(iter(row['settings']))
        changed[key] = not changed[key] if type(changed[key]) is bool else (99 if type(changed[key]) is int else ([99]*4 if type(changed[key]) is list else '/external.frag'))
        (self.home / 'compositor.json').write_text(json.dumps(changed))
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('conflict', result['message'].lower())
        self.assertEqual(self.values(), changed)

    def test_unknown_membership_and_verb_have_no_ipc(self):
        for ident, verb in [('../evil', 'apply'), ('$(bad)', 'apply'), (backend.load_rows()[0]['id'], 'launch')]:
            code, result = self.cli('action', '--id', ident, '--verb', verb, '--apply')
            self.assertNotEqual(code, 0)
            self.assertFalse(result['ok'])
        self.assertFalse((self.home / 'calls.jsonl').exists())

    def test_catalog_has_no_state_or_ipc_side_effects(self):
        code, result = self.cli('catalog')
        self.assertEqual(code, 0)
        self.assertEqual(result['rows'], backend.catalog()['rows'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())

    def test_unqualified_version_fails_closed(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_VERSION': '0.99.0'})
        self.assertNotEqual(code, 0)
        self.assertIn('0.56.2', result['message'])
        self.assertEqual(self.values(), self.original)

    def test_missing_session_fails_closed(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'HYPRLAND_INSTANCE_SIGNATURE': ''})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'calls.jsonl').exists())

    def test_missing_helper_reports_failure(self):
        (self.shim / 'hyprctl').unlink()
        # PATH remains fixture-only to exclude the real executable even inside this isolated box.
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'PATH': str(self.shim)})
        self.assertNotEqual(code, 0)
        self.assertIn('unavailable', result['message'])
        self.assertEqual(self.values(), self.original)

    def test_disable_accepts_empty_transport_readback_and_restores_path(self):
        import json
        code, result = self.cli('action', '--id', 'disable', '--verb', 'apply', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values()['decoration.screen_shader'], '')
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        self.assertEqual(record['expected'], {'decoration.screen_shader': ''})
        self.assertFalse({'token', 'deadline', 'watchdog_pid'} & record.keys())
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)
        self.assertFalse(path.exists())

    def test_empty_sentinel_and_literal_previous_shader_restore_exactly(self):
        import json
        for previous, sentinel in [('', True), ('', False), ('/old/a \"quote\"; os.execute(\"bad\"); ü.frag', False)]:
            with self.subTest(previous=previous, sentinel=sentinel):
                marker = self.home / 'empty-getoption-sentinel'
                marker.touch() if sentinel else marker.unlink(missing_ok=True)
                (self.home / 'assignments.jsonl').unlink(missing_ok=True)
                self.original['decoration.screen_shader'] = previous
                (self.home / 'compositor.json').write_text(json.dumps(self.original))
                code, result = self.cli('action', '--id', 'grayscale', '--verb', 'apply', '--apply')
                self.assertEqual(code, 0, result)
                path = next((self.home / 'state').rglob('transaction.json'))
                before = json.loads(path.read_text())['before']
                code, result = self.cli('action', '--id', 'disable', '--verb', 'restore', '--apply')
                self.assertEqual(code, 0, result)
                self.assertEqual(self.values(), self.original)
                self.assertFalse(path.exists())
                self.assertEqual(before, {'decoration.screen_shader': previous})
                assigned = [json.loads(line)['value'] for line in (self.home / 'assignments.jsonl').read_text().splitlines()]
                self.assertNotIn('[[EMPTY]]', assigned)

    def legacy_empty_receipt(self, phase='active', current='', expected='[[EMPTY]]', previous='[[EMPTY]]'):
        import hashlib, json
        directory = self.home / 'state/omarchy-shader-deck' / hashlib.sha256(self.env['HYPRLAND_INSTANCE_SIGNATURE'].encode()).hexdigest()[:24]
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.parent.chmod(0o700)
        path = directory / 'transaction.json'
        record = {'instance': self.env['HYPRLAND_INSTANCE_SIGNATURE'], 'id': 'disable', 'phase': phase,
                  'before': {'decoration.screen_shader': '[[EMPTY]]'},
                  'previous': {'decoration.screen_shader': previous},
                  'expected': {'decoration.screen_shader': expected}}
        path.write_text(json.dumps(record))
        state = dict(self.original, **{'decoration.screen_shader': current})
        (self.home / 'compositor.json').write_text(json.dumps(state))
        return path, record

    def test_legacy_empty_receipt_fields_are_canonical_without_rewriting_file(self):
        import json
        path, record = self.legacy_empty_receipt()
        original = path.read_bytes()
        loaded = backend.load_state(path.parent, record['instance'])
        for field in ['before', 'previous', 'expected']:
            self.assertEqual(loaded[field], {'decoration.screen_shader': ''})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.home / 'eval-count').exists())

    def test_legacy_empty_restore_never_assigns_sentinel_as_shader_path(self):
        import json
        for phase, current, expected, previous in [
                ('active', '/old/confirmed.frag', '/old/confirmed.frag', '/old/confirmed.frag'),
                ('active', '', '[[EMPTY]]', '[[EMPTY]]'),
                ('pending', '', '/old/trial.frag', '[[EMPTY]]'),
                ('pending', '/old/trial.frag', '/old/trial.frag', '[[EMPTY]]')]:
            with self.subTest(phase=phase, current=current):
                path, record = self.legacy_empty_receipt(phase, current, expected, previous)
                (self.home / 'assignments.jsonl').unlink(missing_ok=True)
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                assigned = self.home / 'assignments.jsonl'
                values = [json.loads(line)['value'] for line in assigned.read_text().splitlines()] if assigned.exists() else []
                self.assertNotIn('[[EMPTY]]', values, 'transport sentinel crossed hl.config instead of canonical empty')
                self.assertEqual(code, 0, result)
                self.assertEqual(self.values(), dict(self.original, **{'decoration.screen_shader': ''}))
                self.assertFalse(path.exists())

    def test_empty_sentinel_setter_uses_empty_lua_assignment(self):
        import json, os
        from unittest.mock import patch
        self.original['decoration.screen_shader'] = ''
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        with patch.dict(os.environ, self.env, clear=True):
            backend.write_value('decoration.screen_shader', '[[EMPTY]]', {'decoration.screen_shader': '[[EMPTY]]'})
        self.assertEqual(self.values(), self.original)
        assignments = [json.loads(line) for line in (self.home / 'assignments.jsonl').read_text().splitlines()]
        self.assertEqual(assignments, [{'key': 'decoration.screen_shader', 'value': ''}])

    def test_empty_baseline_rollback_after_real_lua_mutation(self):
        import json
        self.original['decoration.screen_shader'] = ''
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        (self.home / 'empty-getoption-sentinel').touch()
        code, result = self.cli('action', '--id', 'warm', '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FAIL_AT': '1', 'FIXTURE_FAIL_AFTER': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('rollback confirmed', result['message'])
        self.assertEqual(self.values(), self.original)
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))
        assigned = [json.loads(line)['value'] for line in (self.home / 'assignments.jsonl').read_text().splitlines()]
        self.assertTrue(assigned[0].endswith('/warm.frag'))
        self.assertEqual(assigned[1:], [''])

    def test_empty_baseline_detached_watchdog_restores_canonical_value(self):
        import json, os
        from unittest.mock import patch
        self.original['decoration.screen_shader'] = ''
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        (self.home / 'empty-getoption-sentinel').touch()
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 0.5):
            self.assertTrue(backend.action('warm', 'apply')['ok'])
        path = next((self.home / 'state').rglob('transaction.json'))
        self.assertEqual(json.loads(path.read_text())['before'], {'decoration.screen_shader': ''})
        self.assert_timed_recovery(path)
        assigned = [json.loads(line)['value'] for line in (self.home / 'assignments.jsonl').read_text().splitlines()]
        self.assertEqual(assigned[-1], '')
        self.assertNotIn('[[EMPTY]]', assigned)

    def test_legacy_empty_timed_receipt_recovers_without_changing_authority(self):
        import json, os, time
        from unittest.mock import patch
        self.original['decoration.screen_shader'] = ''
        path, record = self.legacy_empty_receipt(current='/old/trial.frag', expected='/old/trial.frag', previous='/old/trial.frag')
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 0.5):
            with backend.locked(path.parent):
                backend.start_watchdog(path.parent, record)
        saved = json.loads(path.read_text())
        self.assertEqual(saved['before'], {'decoration.screen_shader': '[[EMPTY]]'})
        self.assertEqual(saved['token'], record['token'])
        self.assertEqual(saved['deadline'], record['deadline'])
        self.assert_timed_recovery(path)
        assigned = [json.loads(line)['value'] for line in (self.home / 'assignments.jsonl').read_text().splitlines()]
        self.assertEqual(assigned, [''])

    def test_legacy_empty_receipt_still_refuses_divergent_external_edit(self):
        for phase in ['active', 'pending']:
            with self.subTest(phase=phase):
                path, record = self.legacy_empty_receipt(phase=phase, current='/external.frag')
                receipt, before = path.read_bytes(), self.values()
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                self.assertNotEqual(code, 0)
                self.assertIn('conflict', result['message'].lower())
                self.assertEqual(path.read_bytes(), receipt)
                self.assertEqual(self.values(), before)
                self.assertFalse((self.home / 'eval-count').exists())

    def test_legacy_empty_normalization_does_not_bypass_receipt_validation(self):
        import copy, json
        path, record = self.legacy_empty_receipt()
        invalid = []
        for field in ['before', 'previous', 'expected']:
            for bad in ['[[EMPTY]] ', 'relative.frag', None, 0, [], '/bad\nfile']:
                changed = copy.deepcopy(record)
                changed[field]['decoration.screen_shader'] = bad
                invalid.append(changed)
        invalid += [dict(record, instance='foreign'), dict(record, phase='bad'), dict(record, token='bad')]
        for changed in invalid:
            with self.subTest(record=changed):
                path.write_text(json.dumps(changed))
                receipt = path.read_bytes()
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                self.assertNotEqual(code, 0)
                self.assertEqual(path.read_bytes(), receipt)
                self.assertFalse((self.home / 'eval-count').exists())
        self.assertEqual(self.values()['decoration.screen_shader'], '')

    def test_empty_sentinel_guard_still_refuses_lua_race(self):
        import os
        from unittest.mock import patch
        before = self.values()
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(ValueError, 'external edit'):
                backend.write_value('decoration.screen_shader', '', {'decoration.screen_shader': '[[EMPTY]]'})
        self.assertEqual(self.values(), before)
        self.assertFalse((self.home / 'assignments.jsonl').exists())

    def test_empty_transport_read_is_canonical_without_state_or_setter(self):
        import json, os
        from unittest.mock import patch
        self.original['decoration.screen_shader'] = ''
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        (self.home / 'empty-getoption-sentinel').touch()
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(json.loads(backend.run_hypr('-j', 'getoption', 'decoration.screen_shader'))['str'], '[[EMPTY]]')
            self.assertEqual(backend.read_values(), {'decoration.screen_shader': ''})
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / 'eval-count').exists())
        self.assertEqual(self.values(), self.original)

    def test_empty_readback_spelling_change_is_not_external_edit(self):
        self.assertEqual(self.cli('action', '--id', 'disable', '--verb', 'apply', '--apply')[0], 0)
        # Raw default sentinel versus explicit empty assignment, same Lua-visible value.
        (self.home / 'empty-getoption-sentinel').touch()
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))

    def test_fixture_empty_setter_switches_transport_to_literal_empty(self):
        import json, os
        from unittest.mock import patch
        self.original['decoration.screen_shader'] = ''
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        (self.home / 'empty-getoption-sentinel').touch()
        with patch.dict(os.environ, self.env, clear=True):
            backend.write_value('decoration.screen_shader', '', {'decoration.screen_shader': ''})
            self.assertEqual(json.loads(backend.run_hypr('-j', 'getoption', 'decoration.screen_shader'))['str'], '')
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'empty-getoption-sentinel').exists())

    def test_default_watchdog_survives_killed_ui_process_group(self):
        import subprocess, json, time, os, signal
        script = "import runpy,json,time; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); print(json.dumps(b['action']('warm','apply')),flush=True); time.sleep(30)"
        caller = subprocess.Popen(['/usr/bin/python3', '-c', script], env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            self.assertTrue(json.loads(caller.stdout.readline())['ok'])
            recordfile = next((self.home / 'state').rglob('transaction.json'))
            record = json.loads(recordfile.read_text())
            self.assertGreater(record['deadline'] - time.monotonic(), 13)
            self.assertNotEqual(os.getsid(record['watchdog_pid']), caller.pid)
            os.killpg(caller.pid, signal.SIGKILL)
            caller.wait(timeout=2)
            deadline = time.monotonic() + 19
            while recordfile.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(recordfile.exists(), '15 second watchdog died with the UI process group')
            self.assertEqual(self.values(), self.original)
        finally:
            if caller.poll() is None:
                os.killpg(caller.pid, signal.SIGKILL)
                caller.wait(timeout=2)
            caller.stdout.close()
            caller.stderr.close()

    def test_shader_switch_does_not_leave_stale_watchdog_authority(self):
        import subprocess, json, time
        script = "import runpy; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.8; b['action']('grayscale','apply'); b['action']('warm','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script],env=self.env,capture_output=True,timeout=5)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.values()['decoration.screen_shader'].endswith('warm.frag'))
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        deadline = time.monotonic() + 5
        while recordfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(recordfile.exists())
        self.assertEqual(self.values(), self.original)

    def test_shader_file_read_has_hard_cap(self):
        # Replace DATA only within the imported test module; production derives it from __file__.
        from unittest.mock import patch
        data = self.home / 'data'
        (data / 'shaders').mkdir(parents=True)
        (data / 'shaders/grayscale.frag').write_bytes(b'x' * 16385)
        with patch.object(backend, 'DATA', data):
            with self.assertRaises(ValueError):
                backend.shader_path('@grayscale.frag')
        # A stat alone is insufficient: read at most cap+1 even if file grows after stat.
        import inspect
        self.assertNotIn('.read_bytes()', inspect.getsource(backend.shader_path))

    def test_failed_shader_switch_rearms_previous_timed_restore(self):
        import subprocess, time
        script = "import runpy; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.5; b['action']('grayscale','apply'); b['action'].__globals__['TRIAL_SECONDS']=2;\ntry: b['action']('warm','apply')\nexcept ValueError: pass"
        p = subprocess.run(['/usr/bin/python3','-c',script], env=dict(self.env, FIXTURE_FAIL_AT='2',
                           FIXTURE_FAIL_AFTER='1', FIXTURE_DELAY_FAIL='1.5'), capture_output=True,timeout=6)
        self.assertEqual(p.returncode, 0, p.stderr)
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        deadline = time.monotonic() + 5
        while recordfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(recordfile.exists(), 'failed switch orphaned the earlier effect')
        self.assertEqual(self.values(), self.original)

    def test_watchdog_recovers_real_caller_crash_mid_transaction(self):
        import subprocess, time
        script = "import runpy; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.7; b['action']('warm','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script], env=dict(self.env,FIXTURE_KILL_CALLER='1'),
                           capture_output=True,timeout=6)
        self.assertEqual(p.returncode, -9)
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        deadline = time.monotonic() + 5
        while recordfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(recordfile.exists())
        self.assertEqual(self.values(), self.original)

    def test_slow_readiness_writer_does_not_publish_an_empty_record(self):
        import os, subprocess, time
        from unittest.mock import patch
        real_popen = backend.subprocess.Popen
        children = []
        def launch(argv, **kwargs):
            if 'watchdog' in argv:
                process = real_popen(['/usr/bin/python3', str(ROOT / 'tests/readiness_watchdog_fixture.py'),
                                      argv[-1], '0.15', 'hold-lock'], **kwargs)
                children.append(process)
                return process
            return real_popen(argv, **kwargs)
        try:
            with patch.dict(os.environ, self.env, clear=True), patch.object(backend.subprocess, 'Popen', launch):
                self.assertTrue(backend.action('grayscale', 'apply')['ok'])
                self.assertTrue(self.values()['decoration.screen_shader'].endswith('/grayscale.frag'))
                self.assertTrue((self.home / 'readiness-paused').exists())
                deadline = time.monotonic() + 3
                while not (self.home / 'watchdog-lock-held').exists():
                    self.assertLess(time.monotonic(), deadline, 'watchdog did not acquire its real lock')
                    time.sleep(0.002)
                recordfile = next((self.home / 'state').rglob('transaction.json'))
                receipt, current = recordfile.read_bytes(), self.values()
                calls = (self.home / 'calls.jsonl').read_bytes()
                assignments = (self.home / 'assignments.jsonl').read_bytes()
                count = (self.home / 'eval-count').read_bytes()
                with self.assertRaisesRegex(backend.BusyError, 'retry'):
                    backend.action('grayscale', 'restore')
                self.assertEqual(recordfile.read_bytes(), receipt)
                self.assertEqual(self.values(), current)
                # Session validation precedes flock; Busy must not reach option reads or setters.
                delta = (self.home / 'calls.jsonl').read_bytes()[len(calls):]
                self.assertEqual([json.loads(line) for line in delta.splitlines()], [['-j', 'version']])
                self.assertEqual((self.home / 'assignments.jsonl').read_bytes(), assignments)
                self.assertEqual((self.home / 'eval-count').read_bytes(), count)
                (self.home / 'release-watchdog').touch()
                deadline = time.monotonic() + 3
                while True:
                    try:
                        result = backend.action('grayscale', 'restore')
                        break
                    except backend.BusyError:
                        self.assertLess(time.monotonic(), deadline, 'watchdog did not release its lock')
                        time.sleep(0.01)
                self.assertTrue(result['ok'])
                self.assertFalse(recordfile.exists())
                delta = (self.home / 'assignments.jsonl').read_bytes()[len(assignments):]
                self.assertEqual([json.loads(line) for line in delta.splitlines()], [
                    {'key': 'decoration.screen_shader', 'value': self.original['decoration.screen_shader']}])
                self.assertEqual(int((self.home / 'eval-count').read_bytes()), int(count) + 1)
            self.assertEqual(self.values(), self.original)
        finally:
            # Stop only this fixture's owned child, even if an assertion prevented Restore.
            (self.home / 'stop-watchdog').touch()
            (self.home / 'release-watchdog').touch()
            for child in children:
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=1)
                self.assertEqual(child.returncode, 0, 'readiness fixture did not exit cleanly')
                self.assertFalse(pathlib.Path('/proc', str(child.pid)).exists())
            self.assertFalse(list((self.home / 'state').rglob('.ready-*')))
            self.assertFalse(list((self.home / 'state').rglob('.watchdog-*')))

    def test_slow_readiness_cleanup_on_assertion_failure(self):
        from unittest.mock import patch
        real_values = self.values
        def fail_while_locked():
            if (self.home / 'watchdog-lock-held').exists():
                raise AssertionError('injected assertion while watchdog holds lock')
            return real_values()
        with self.assertRaisesRegex(AssertionError, 'injected assertion while watchdog holds lock'):
            with patch.object(self, 'values', fail_while_locked):
                self.test_slow_readiness_writer_does_not_publish_an_empty_record()
        pid = (self.home / 'watchdog-lock-held').read_text()
        self.assertFalse(pathlib.Path('/proc', pid).exists())
        self.assertFalse(list((self.home / 'state').rglob('.ready-*')))
        self.assertFalse(list((self.home / 'state').rglob('.watchdog-*')))

    def test_late_unpublished_watchdog_cleans_readiness_after_timeout(self):
        import os
        from unittest.mock import patch
        real_popen = backend.subprocess.Popen
        children = []
        def launch(argv, **kwargs):
            if 'watchdog' in argv:
                process = real_popen(['/usr/bin/python3', str(ROOT / 'tests/readiness_watchdog_fixture.py'), argv[-1], '2.2'], **kwargs)
                children.append(process)
                return process
            return real_popen(argv, **kwargs)
        try:
            with patch.dict(os.environ, self.env, clear=True), patch.object(backend.subprocess, 'Popen', launch):
                with self.assertRaisesRegex(ValueError, 'rollback confirmed'):
                    backend.action('grayscale', 'apply')
            self.assertEqual(self.values(), self.original)
            self.assertFalse((self.home / 'eval-count').exists())
        finally:
            for child in children:
                child.wait(timeout=4)
        self.assertFalse(list((self.home / 'state').rglob('.ready-*')))
        self.assertFalse(list((self.home / 'state').rglob('.watchdog-*')))

    def test_wrong_or_symlink_readiness_refuses_without_mutation(self):
        import os
        from unittest.mock import patch
        real_popen = backend.subprocess.Popen
        children = []
        outside = self.home / 'not-readiness'; outside.write_text('999999')
        def launch(argv, **kwargs):
            if 'watchdog' in argv:
                directory = next((self.home / 'state').rglob('transaction.json')).parent
                ready = directory / ('.ready-' + argv[-1])
                if kind == 'symlink':
                    ready.symlink_to(outside)
                else:
                    ready.write_text('0')
                process = real_popen(argv, **kwargs)
                children.append(process)
                return process
            return real_popen(argv, **kwargs)
        for kind in ['wrong-pid', 'symlink']:
            with self.subTest(kind=kind):
                try:
                    with patch.dict(os.environ, self.env, clear=True), patch.object(backend.subprocess, 'Popen', launch):
                        with self.assertRaisesRegex(ValueError, 'rollback confirmed'):
                            backend.action('grayscale', 'apply')
                    self.assertEqual(self.values(), self.original)
                    self.assertFalse((self.home / 'eval-count').exists())
                    self.assertEqual(outside.read_text(), '999999')
                finally:
                    for child in children:
                        child.wait(timeout=4)
                self.assertFalse(list((self.home / 'state').rglob('.ready-*')))
                self.assertFalse(list((self.home / 'state').rglob('.watchdog-*')))

    def test_unavailable_watchdog_refuses_before_any_setter(self):
        import os, subprocess
        from unittest.mock import patch
        real_popen = subprocess.Popen
        def launch(argv, **kwargs):
            if 'watchdog' in argv:
                raise OSError('simulated watchdog launch failure')
            return real_popen(argv, **kwargs)
        with patch.dict(os.environ,self.env,clear=True), patch.object(subprocess,'Popen',launch):
            with self.assertRaisesRegex(ValueError,'rollback confirmed'):
                backend.action('grayscale','apply')
        self.assertEqual(self.values(), self.original)
        self.assertFalse((self.home / 'eval-count').exists())

    def test_timed_restore_preserves_conflicting_external_shader(self):
        import contextlib, os, subprocess
        from unittest.mock import patch
        real_popen, real_locked = backend.subprocess.Popen, backend.locked
        children = []
        def launch(argv, **kwargs):
            child = real_popen(argv, **kwargs)
            if 'watchdog' in argv:
                children.append(child)
            return child
        observed = []
        @contextlib.contextmanager
        def edit_before_unlock(directory):
            with real_locked(directory):
                yield
                # Publish the external edit while Apply still owns the real flock, even past expiry.
                self.assertEqual(len(children), 1)
                recordfile = directory / 'transaction.json'
                receipt = recordfile.read_bytes()
                self.assertEqual(json.loads(receipt)['watchdog_pid'], children[0].pid)
                self.assertIsNone(children[0].poll(), 'watchdog exited before the external edit')
                count = (self.home / 'eval-count').read_bytes()
                assignments = (self.home / 'assignments.jsonl').read_bytes()
                external = self.values()
                external['decoration.screen_shader'] = '/external-owned.frag'
                (self.home / 'compositor.json').write_text(json.dumps(external))
                observed.append((recordfile, receipt, count, assignments, external))
        try:
            with patch.dict(os.environ, self.env, clear=True), \
                 patch.object(backend, 'TRIAL_SECONDS', 0.6), \
                 patch.object(backend.subprocess, 'Popen', launch), \
                 patch.object(backend, 'locked', edit_before_unlock):
                self.assertTrue(backend.action('warm', 'apply')['ok'])
            child = children[0]
            recordfile, receipt, count, assignments, external = observed[0]
            # A fixed delay can race the watchdog's guarded IPC retries under its flock.
            self.assertEqual(child.wait(timeout=10), 1, 'watchdog did not report failed recovery')
            self.assertFalse(list(recordfile.parent.glob('.ready-*')))
            self.assertEqual(self.values(), external)
            self.assertEqual(recordfile.read_bytes(), receipt)
            code, result = self.cli('action', '--id', 'warm', '--verb', 'restore', '--apply')
            self.assertNotEqual(code, 0)
            self.assertIn('conflict', result['message'].lower())
            self.assertEqual(self.values(), external)
            self.assertEqual(recordfile.read_bytes(), receipt)
            self.assertEqual((self.home / 'eval-count').read_bytes(), count)
            self.assertEqual((self.home / 'assignments.jsonl').read_bytes(), assignments)
        finally:
            for child in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=1)

    def test_confirm_keeps_only_current_trial_and_preserves_restore(self):
        import os, subprocess, time
        from unittest.mock import patch
        real_popen, real_cli = backend.subprocess.Popen, self.cli
        children, responses = [], []
        def launch(argv, **kwargs):
            if 'watchdog' in argv:
                child = real_popen(['/usr/bin/python3', str(ROOT / 'tests/readiness_watchdog_fixture.py'),
                                    argv[-1], '0', 'hold-lock'], **kwargs)
                children.append(child)
                return child
            return real_popen(argv, **kwargs)
        def confirm(*args, **kwargs):
            try:
                reply = real_cli(*args, **kwargs)
                responses.append(reply)
                return reply
            finally:
                (self.home / 'release-watchdog').touch()
        try:
            with patch.dict(os.environ, self.env, clear=True), patch.object(backend.subprocess, 'Popen', launch):
                self.assertTrue(backend.action('cool', 'apply')['ok'])
            held = self.home / 'watchdog-lock-held'
            limit = time.monotonic() + 2
            while not held.exists():
                self.assertLess(time.monotonic(), limit, 'watchdog never held its real lock')
                time.sleep(0.002)
            path = next((self.home / 'state').rglob('transaction.json'))
            owner = json.loads(path.read_text())
            self.assertEqual(owner['watchdog_pid'], children[0].pid)
            self.assertEqual(int(held.read_text()), children[0].pid)
            with patch.object(self, 'cli', confirm):
                self.confirm_trial('cool')
            self.assertEqual(responses[0], (1, {'ok': False, 'message': 'Another preset action is in progress; retry'}))
            self.assertEqual(responses[-1][0], 0)
            self.assertEqual(children[0].wait(timeout=2), 0)
            self.assertNotIn('token', json.loads(path.read_text()))
            self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
            self.assertEqual(self.values(), self.original)
        finally:
            (self.home / 'stop-watchdog').touch()
            (self.home / 'release-watchdog').touch()
            for child in children:
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=1)
                self.assertFalse(pathlib.Path('/proc', str(child.pid)).exists())
            self.assertFalse(list((self.home / 'state').rglob('.ready-*')))
            self.assertFalse(list((self.home / 'state').rglob('.watchdog-*')))

    def test_confirm_wrong_selected_id_cannot_keep_other_effect(self):
        import subprocess,time
        script = "import runpy; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.7; b['action']('grayscale','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script],env=self.env,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        code,result = self.cli('action','--id','warm','--verb','confirm','--apply')
        self.assertNotEqual(code,0)
        time.sleep(1.2)
        self.assertEqual(self.values(),self.original)

    def test_confirm_without_trial_cannot_claim_success(self):
        for ident in ['disable','warm']:
            code,result = self.cli('action','--id',ident,'--verb','confirm','--apply')
            self.assertNotEqual(code,0)
            self.assertFalse(result['ok'])
        self.assertEqual(self.values(),self.original)

    def test_watchdog_waits_for_inflight_lock_past_expiry(self):
        import subprocess,time,fcntl
        script = "import runpy; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.5; b['action']('warm','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script],env=self.env,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        with (recordfile.parent / 'lock').open('r+') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            time.sleep(1.6)
        deadline = time.monotonic() + 5
        while recordfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(recordfile.exists(),'watchdog abandoned a busy transaction')
        self.assertEqual(self.values(),self.original)

    def test_confirm_missing_snapshot_id_fails_without_trace(self):
        import json
        self.assertEqual(self.cli('action','--id','disable','--verb','apply','--apply')[0],0)
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(recordfile.read_text())
        del record['id']
        recordfile.write_text(json.dumps(record))
        code,result = self.cli('action','--id','warm','--verb','confirm','--apply')
        self.assertNotEqual(code,0)
        self.assertFalse(result['ok'])

    def test_failed_keep_persistence_rearms_trial(self):
        import os,time
        from unittest.mock import patch
        with patch.dict(os.environ,self.env,clear=True), patch.object(backend,'TRIAL_SECONDS',0.9):
            backend.action('warm','apply')
            real_save = backend.save
            failed = [False]
            def fail_once(directory,record):
                if not failed[0]:
                    failed[0] = True
                    raise OSError('simulated Keep save failure')
                return real_save(directory,record)
            with patch.object(backend,'save',fail_once):
                with self.assertRaisesRegex(ValueError,'Keep failed'):
                    backend.action('warm','confirm')
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        deadline = time.monotonic() + 5
        while recordfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(recordfile.exists())
        self.assertEqual(self.values(),self.original)

    def test_detached_watchdog_handle_is_reaped_without_resource_warning(self):
        import os,time,warnings,gc
        from unittest.mock import patch
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always', ResourceWarning)
            with patch.dict(os.environ,self.env,clear=True), patch.object(backend,'TRIAL_SECONDS',0.4):
                backend.action('warm','apply')
            time.sleep(0.9)
            gc.collect()
        self.assertFalse([w for w in seen if issubclass(w.category,ResourceWarning)])
        self.assertEqual(self.values(),self.original)

    def test_restore_alias_failure_retains_trial_identity_and_original_deadline(self):
        import json, os, time
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 1.2):
            backend.action('warm', 'apply')
        path = next((self.home / 'state').rglob('transaction.json'))
        original = json.loads(path.read_text())
        (self.home / 'fail-next-setter').touch()
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('retained', result['message'])
        pending = json.loads(path.read_text())
        self.assertEqual(pending['id'], 'warm')
        self.assertEqual(pending['phase'], 'pending')
        for field in ['token', 'deadline', 'watchdog_pid', 'before']:
            self.assertEqual(pending[field], original[field])
        self.assertTrue((self.home / 'ipc-outage').exists())
        (self.home / 'ipc-outage').unlink()
        limit = original['deadline'] + 3
        while path.exists() and time.monotonic() < limit:
            time.sleep(0.02)
        self.assertFalse(path.exists(), 'alias replaced trial identity or lost timed recovery')
        self.assertEqual(self.values(), self.original)

    def test_timed_restore_retries_ipc_loss_after_initial_read(self):
        import os, json, time
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 0.6):
            backend.action('warm', 'apply')
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        original = json.loads(recordfile.read_text())
        (self.home / 'fail-next-setter').touch()
        failed_read = self.home / 'outage-calls.jsonl'
        limit = time.monotonic() + 4
        while not failed_read.exists() and time.monotonic() < limit:
            time.sleep(0.01)
        self.assertTrue(failed_read.exists(), 'did not reach rollback read during IPC loss')
        pending = json.loads(recordfile.read_text())
        outage = json.loads((self.home / 'outage-start.json').read_text())
        self.assertEqual(outage['pid'], original['watchdog_pid'])
        calls = [json.loads(line) for line in outage['calls'].splitlines()]
        self.assertEqual(calls[-2], ['-j', 'getoption', 'decoration.screen_shader'])
        self.assertEqual(calls[-1][0], 'eval')
        self.assertIn(['-j', 'getoption', 'decoration.screen_shader'],
                      [json.loads(line) for line in failed_read.read_text().splitlines()])
        self.assertEqual(pending['phase'], 'pending')
        self.assertNotEqual(self.values(), self.original)
        (self.home / 'ipc-outage').unlink()
        limit = time.monotonic() + 3
        while recordfile.exists() and time.monotonic() < limit:
            time.sleep(0.02)
        self.assertFalse(recordfile.exists(), 'original watchdog abandoned failed restore: ' + repr(pending))
        self.assertEqual(self.values(), self.original)
        self.assertEqual(pending.get('token'), original['token'])
        self.assertEqual(pending.get('deadline'), original['deadline'])
        print('FIXTURE_EVIDENCE ' + json.dumps({
            'stage': 'restore-ipc-outage', 'initial_restore_read_succeeded': True,
            'setter_failed': True, 'rollback_read_failed': True,
            'original_watchdog_pid': original['watchdog_pid'], 'setter_parent_pid': outage['pid'],
            'original_deadline': original['deadline'], 'pending_deadline': pending['deadline'],
            'ownership_preserved': pending['token'] == original['token'],
            'ipc_recovered': True, 'baseline_restored': self.values() == self.original,
            'journal_removed': not recordfile.exists()}), flush=True)

    def interrupted_caller(self, stage, verb, row):
        import json, os, signal, subprocess, time
        marker = self.home / 'interrupted.json'
        marker.unlink(missing_ok=True)
        caller = subprocess.Popen(['/usr/bin/python3', str(ROOT / 'tests/watchdog_caller_fixture.py'),
                                   stage, verb, row], env=self.env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True)
        try:
            limit = time.monotonic() + 4
            while not marker.exists() and caller.poll() is None and time.monotonic() < limit:
                time.sleep(0.01)
            self.assertTrue(marker.exists(), 'caller did not reach ' + stage)
            evidence = json.loads(marker.read_text())
            original = json.loads((self.home / 'original-trial.json').read_text())
            self.assertEqual(evidence['stage'], stage)
            self.assertEqual(evidence['pid'], caller.pid)
            self.assertEqual(evidence['pgid'], caller.pid)
            self.assertNotEqual(os.getsid(original['watchdog_pid']), caller.pid)
            self.assertEqual(evidence['journal']['phase'], 'pending')
            if stage == 'spawned':
                blocked = self.home / 'blocked-watchdog'
                limit = time.monotonic() + 2
                while not blocked.exists() and time.monotonic() < limit:
                    time.sleep(0.01)
                self.assertTrue(blocked.exists(), 'replacement never entered blocked startup IPC')
                self.assertNotEqual(int(blocked.read_text()), original['watchdog_pid'])
                self.assertFalse(list(next((self.home / 'state').rglob('lock')).parent.glob('.ready-*')))
            if stage == 'ready':
                self.assertEqual(len(evidence['ready']), 1)
                self.assertNotEqual(int(evidence['ready'][0]), original['watchdog_pid'])
                self.assertNotEqual(os.getsid(int(evidence['ready'][0])), caller.pid)
            self.assertTrue(self.values()['decoration.screen_shader'].endswith('grayscale.frag'))
            os.killpg(caller.pid, signal.SIGKILL)
            out, err = caller.communicate(timeout=2)
            self.assertEqual(caller.returncode, -signal.SIGKILL)
            self.assertEqual((out, err), (b'', b''))
            recordfile = next((self.home / 'state').rglob('transaction.json'))
            limit = original['deadline'] + 2
            while recordfile.exists() and time.monotonic() < limit:
                time.sleep(0.02)
            self.assertFalse(recordfile.exists(), stage + ' lost original timed restore: ' + repr(evidence))
            self.assertEqual(self.values(), self.original)
            self.assertEqual(evidence['journal'].get('token'), original['token'])
            self.assertEqual(evidence['journal'].get('deadline'), original['deadline'])
            print('FIXTURE_EVIDENCE ' + json.dumps({
                'stage': stage, 'verb': verb, 'row': row, 'caller_pid': caller.pid,
                'caller_pgid': evidence['pgid'], 'caller_exit': caller.returncode,
                'original_watchdog_pid': original['watchdog_pid'],
                'original_deadline': original['deadline'], 'pending_deadline': evidence['journal']['deadline'],
                'ownership_preserved': evidence['journal']['token'] == original['token'],
                'replacement_ready_pids': evidence['ready'], 'baseline_restored': self.values() == self.original,
                'journal_removed': not recordfile.exists()}), flush=True)
        finally:
            (self.home / 'block-new-watchdog').unlink(missing_ok=True)
            if caller.poll() is None:
                os.killpg(caller.pid, signal.SIGKILL)
                caller.wait(timeout=2)
            caller.stdout.close()
            caller.stderr.close()

    def test_pending_switch_group_kill_retains_original_owner(self):
        self.interrupted_caller('pending', 'apply', 'warm')

    def test_pending_restore_group_kill_retains_original_owner(self):
        self.interrupted_caller('pending', 'restore', 'grayscale')

    def test_pending_disable_group_kill_retains_original_owner(self):
        self.interrupted_caller('pending', 'apply', 'disable')

    def test_replacement_startup_group_kill_retains_original_owner(self):
        self.interrupted_caller('startup', 'apply', 'warm')

    def test_replacement_spawned_unready_group_kill_retains_original_owner(self):
        self.interrupted_caller('spawned', 'apply', 'warm')

    def test_replacement_ready_before_publish_group_kill_retains_original_owner(self):
        self.interrupted_caller('ready', 'apply', 'warm')

    def test_successful_switch_handoff_observes_successor_deadline(self):
        import json, os, time
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(backend, 'TRIAL_SECONDS', 0.6):
                backend.action('grayscale', 'apply')
            recordfile = next((self.home / 'state').rglob('transaction.json'))
            original = json.loads(recordfile.read_text())
            with patch.object(backend, 'TRIAL_SECONDS', 1.4):
                backend.action('warm', 'apply')
        successor = json.loads(recordfile.read_text())
        self.assertNotEqual(successor['token'], original['token'])
        self.assertNotEqual(successor['watchdog_pid'], original['watchdog_pid'])
        self.assertGreater(successor['deadline'], original['deadline'])
        time.sleep(max(0, original['deadline'] + 0.2 - time.monotonic()))
        self.assertTrue(self.values()['decoration.screen_shader'].endswith('warm.frag'))
        self.assertTrue(recordfile.exists(), 'successor restored at predecessor deadline')
        limit = successor['deadline'] + 3
        while recordfile.exists() and time.monotonic() < limit:
            time.sleep(0.02)
        self.assertFalse(recordfile.exists())
        self.assertEqual(self.values(), self.original)

    def test_completed_disable_retires_timer_only_after_readback(self):
        import json, os, time
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 0.5):
            backend.action('warm', 'apply')
            backend.action('disable', 'apply')
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(recordfile.read_text())
        self.assertFalse({'token', 'deadline', 'watchdog_pid'} & record.keys())
        time.sleep(0.9)
        self.assertEqual(self.values()['decoration.screen_shader'], '')
        self.assertTrue(recordfile.exists())
        self.assertEqual(self.cli('action', '--id', 'disable', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def test_inactive_generated_recovery_targets_are_checked_before_setter(self):
        import os
        from unittest.mock import patch
        scenarios = [('restore-active', False), ('restore-pending', False),
                     ('compensation', False), ('compensation', True)]
        for operation, after_replace in scenarios:
            with self.subTest(operation=operation, after_replace=after_replace):
                self.setUp()
                self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"options":{"intensity":50}}')[0], 0)
                if operation.startswith('restore'):
                    with patch.dict(os.environ, self.env, clear=True):
                        generated = pathlib.Path(backend.shader_path('@cool.frag'))
                    self.original['decoration.screen_shader'] = str(generated)
                    (self.home / 'compositor.json').write_text(json.dumps(self.original))
                else:
                    self.assertEqual(self.cli('action', '--id', 'cool', '--verb', 'apply', '--apply')[0], 0)
                    self.confirm_trial('cool')
                    generated = pathlib.Path(self.values()['decoration.screen_shader'])
                clean = generated.read_bytes()
                edited = clean + b'\n// inactive recovery target edited\n'
                real_save = backend.save
                injected = [False]
                def lost_publication(directory, record):
                    if record['phase'] == 'active' and record['id'] == 'sepia' and not injected[0]:
                        injected[0] = True
                        if after_replace:
                            real_save(directory, record)
                        generated.write_bytes(edited)
                        raise OSError('active publication acknowledgement lost')
                    return real_save(directory, record)
                if operation == 'compensation':
                    (self.home / 'eval-count').unlink()
                    (self.home / 'assignments.jsonl').unlink()
                    with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'save', lost_publication):
                        with self.assertRaisesRegex(ValueError, 'retained'):
                            backend.action('sepia', 'apply')
                    self.assertTrue(injected[0])
                    expected_setters = 1  # The clean sepia Apply, never the edited cool compensation.
                else:
                    self.assertEqual(self.cli('action', '--id', 'sepia', '--verb', 'apply', '--apply')[0], 0)
                    self.confirm_trial('sepia')
                    path = next((self.home / 'state').rglob('transaction.json'))
                    if operation == 'restore-pending':
                        record = json.loads(path.read_text())
                        record['phase'] = 'pending'
                        path.write_text(json.dumps(record))
                    (self.home / 'eval-count').unlink()
                    (self.home / 'assignments.jsonl').unlink()
                    generated.write_bytes(edited)
                    code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                    self.assertNotEqual(code, 0, result)
                    expected_setters = 0
                count = self.home / 'eval-count'
                self.assertEqual(int(count.read_text()) if count.exists() else 0, expected_setters,
                                 'a setter reached the tampered inactive recovery target')
                assignments = self.home / 'assignments.jsonl'
                assigned = [json.loads(line)['value'] for line in assignments.read_text().splitlines()] if assignments.exists() else []
                self.assertNotIn(str(generated), assigned)
                self.assertEqual(generated.read_bytes(), edited)
                path = next((self.home / 'state').rglob('transaction.json'))
                record = json.loads(path.read_text())
                self.assertEqual(record['phase'], 'active' if operation == 'restore-active' else 'pending')
                self.assertEqual(record['before'], {k: self.original[k] for k in backend.SCHEMA})
                current = self.values()
                self.assertEqual({'decoration.screen_shader': current['decoration.screen_shader']}, record['expected'] if operation == 'compensation' else record['previous'])
                # Repairing the file is not permission to overwrite an independently changed option.
                generated.write_bytes(clean)
                external = dict(current, **{'decoration.screen_shader': '/external-owned.frag'})
                (self.home / 'compositor.json').write_text(json.dumps(external))
                receipt, calls = path.read_bytes(), count.read_bytes() if count.exists() else None
                code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
                self.assertNotEqual(code, 0, result)
                self.assertIn('conflict', result['message'].lower())
                self.assertEqual(self.values(), external)
                self.assertEqual(path.read_bytes(), receipt)
                self.assertEqual(count.read_bytes() if count.exists() else None, calls)
                (self.home / 'compositor.json').write_text(json.dumps(current))
                self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
                self.assertEqual(self.values(), self.original)
                self.assertFalse(path.exists())
                self.assertEqual(generated.read_bytes(), clean)

    def test_timed_restore_rejects_inactive_edit_and_recovers_after_repair(self):
        import os, time
        from unittest.mock import patch
        self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"options":{"intensity":50}}')[0], 0)
        with patch.dict(os.environ, self.env, clear=True):
            generated = pathlib.Path(backend.shader_path('@cool.frag'))
            self.original['decoration.screen_shader'] = str(generated)
            (self.home / 'compositor.json').write_text(json.dumps(self.original))
            with patch.object(backend, 'TRIAL_SECONDS', 0.8):
                backend.action('sepia', 'apply')
        clean = generated.read_bytes()
        edited = clean + b'\n// inactive baseline edited\n'
        generated.write_bytes(edited)
        path = next((self.home / 'state').rglob('transaction.json'))
        original = json.loads(path.read_text())
        before, count = self.values(), (self.home / 'eval-count').read_bytes()
        time.sleep(max(0, original['deadline'] + 0.15 - time.monotonic()))
        self.assertEqual((self.home / 'eval-count').read_bytes(), count)
        self.assertEqual(self.values(), before)
        self.assertEqual(generated.read_bytes(), edited)
        retained = json.loads(path.read_text())
        for field in ['before', 'token', 'deadline', 'watchdog_pid']:
            self.assertEqual(retained[field], original[field])
        generated.write_bytes(clean)
        self.assert_timed_recovery(path)
        self.assertEqual(generated.read_bytes(), clean)

    def test_keep_failure_restore_also_checks_inactive_generated_target(self):
        import os
        from unittest.mock import patch
        self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"options":{"intensity":50}}')[0], 0)
        with patch.dict(os.environ, self.env, clear=True):
            generated = pathlib.Path(backend.shader_path('@cool.frag'))
            self.original['decoration.screen_shader'] = str(generated)
            (self.home / 'compositor.json').write_text(json.dumps(self.original))
            backend.action('sepia', 'apply')
            path = next((self.home / 'state').rglob('transaction.json'))
            original = json.loads(path.read_text())
            clean = generated.read_bytes()
            edited = clean + b'\n// inactive Keep recovery target edited\n'
            generated.write_bytes(edited)
            current, count = self.values(), (self.home / 'eval-count').read_bytes()
            real_save = backend.save
            failed = [False]
            def save(directory, record):
                if not failed[0]:
                    failed[0] = True
                    raise OSError('Keep publication failed')
                return real_save(directory, record)
            with patch.object(backend, 'save', save), patch.object(backend, 'start_watchdog', side_effect=OSError('rearm failed')):
                with self.assertRaises(ValueError):
                    backend.action('sepia', 'confirm')
        self.assertEqual((self.home / 'eval-count').read_bytes(), count)
        self.assertEqual(self.values(), current)
        self.assertEqual(generated.read_bytes(), edited)
        self.assertEqual(json.loads(path.read_text()), original)
        generated.write_bytes(clean)
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        self.assertFalse(path.exists())

    def test_shader_assets_are_fixed_useful_programs(self):
        for name in ['grayscale', 'warm']:
            path = RUNTIME / 'data/shaders' / (name + '.frag')
            self.assertTrue(path.is_file(), 'shader asset missing: ' + name)
            source = path.read_text()
            self.assertTrue(source.startswith('#version 300 es'))
            self.assertIn('texture(tex, v_texcoord)', source)
            self.assertIn('pix.a', source)
            self.assertNotIn('#include', source)
        self.assertIn('0.2126', (RUNTIME / 'data/shaders/grayscale.frag').read_text())
        self.assertIn('0.88', (RUNTIME / 'data/shaders/warm.frag').read_text())

    def test_watchdog_survives_ui_process_exit_and_reverts(self):
        import subprocess, json, time, os
        # Change a Python constant only in the disposable UI caller; no production env bypass.
        script = "import runpy,json; b=runpy.run_path(" + repr(str(RUNTIME / 'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.7; print(json.dumps(b['action']('grayscale','apply')))"
        caller = subprocess.Popen(['/usr/bin/python3', '-c', script], env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        out, err = caller.communicate(timeout=5)
        self.assertEqual(caller.returncode, 0, err)
        self.assertTrue(json.loads(out)['ok'])
        records = list((self.home / 'state').rglob('transaction.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        pid = record['watchdog_pid']
        self.assertNotEqual(os.getsid(pid), caller.pid)
        self.assertNotEqual(self.values()['decoration.screen_shader'], self.original['decoration.screen_shader'])
        deadline = time.monotonic() + 5
        while records[0].exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(records[0].exists(), 'independent watchdog did not finish')
        self.assertEqual(self.values(), self.original)

    def test_failed_rollback_retains_recoverable_snapshot(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FAILS': '1,2', 'FIXTURE_FAIL_AFTER': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('retained', result['message'].lower())
        self.assertEqual(len(list((self.home / 'state').rglob('transaction.json'))), 1)
        self.assertNotEqual(self.values(), self.original)
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_interrupted_snapshot_restores_partial_transaction(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        record['phase'] = 'pending'
        record['previous'] = {k:self.original[k] for k in backend.SCHEMA}
        path.write_text(json.dumps(record))
        # Simulate a crash after only one field of a multi-field transaction was written.
        partial = self.values()
        keys = list(row['settings'])
        for key in keys[1:]:
            partial[key] = self.original[key]
        (self.home / 'compositor.json').write_text(json.dumps(partial))
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_busy_lock_refuses_without_mutation(self):
        import fcntl
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        lock = next((self.home / 'state').rglob('lock'))
        with lock.open('r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.values()
            code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
            self.assertNotEqual(code, 0)
            self.assertIn('progress', result['message'])
            self.assertEqual(self.values(), before)

    def test_invalid_snapshot_fields_fail_without_trace_or_mutation(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        record = json.loads(path.read_text())
        record['before']['exec'] = 'bad'
        path.write_text(json.dumps(record))
        before = self.values()
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('snapshot', result['message'])
        self.assertEqual(self.values(), before)

    def test_successive_presets_keep_original_restore_baseline(self):
        rows = backend.load_rows() if backend.SLUG != 'shader-deck' else backend.load_rows()[:1]
        for row in rows:
            code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
            self.assertEqual(code, 0, result)
        code, result = self.cli('action', '--id', rows[-1]['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)

    def test_restore_preserves_unrelated_external_values(self):
        import json
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        external = self.values()
        external['unrelated'] = 'externally edited'
        (self.home / 'compositor.json').write_text(json.dumps(external))
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), dict(self.original, unrelated='externally edited'))

    def test_oversized_data_read_is_bounded(self):
        path = self.home / 'large.json'
        path.write_bytes(b' ' * 65537)
        with self.assertRaises(ValueError):
            backend.bounded_json(path)

    def test_private_state_directory_rejects_world_writable_location(self):
        directory = self.home / 'state' / ('omarchy-' + backend.SLUG)
        directory.mkdir(parents=True)
        directory.chmod(0o777)
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
        self.assertNotEqual(code, 0, 'unsafe permissions accepted')
        self.assertEqual(self.values(), self.original)

    def test_malformed_ipc_shapes_return_json_failure_without_trace(self):
        row = backend.load_rows()[0]
        for kind in ['version', 'option']:
            with self.subTest(kind=kind):
                code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                       extra={'FIXTURE_MALFORMED': kind})
                self.assertNotEqual(code, 0)
                self.assertFalse(result['ok'])
                self.assertEqual(self.values(), self.original)

    def test_hung_ipc_times_out_without_mutation(self):
        import time
        start = time.monotonic()
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_HANG': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('timed out', result['message'])
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.values(), self.original)

    def test_flooded_ipc_is_bounded(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply',
                                extra={'FIXTURE_FLOOD': '1'})
        self.assertNotEqual(code, 0)
        self.assertIn('64 KiB', result['message'])
        self.assertEqual(self.values(), self.original)

    def test_symlink_snapshot_never_follows_arbitrary_file(self):
        row = backend.load_rows()[0]
        self.assertEqual(self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')[0], 0)
        path = next((self.home / 'state').rglob('transaction.json'))
        moved = self.home / 'saved.json'
        path.rename(moved)
        path.symlink_to(moved)
        before = self.values()
        code, result = self.cli('action', '--id', row['id'], '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertEqual(self.values(), before)

    def test_sandbox_is_not_connected_to_live_session(self):
        import os
        self.assertFalse(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'))
        self.assertFalse(os.environ.get('WAYLAND_DISPLAY'))
        self.assertFalse(pathlib.Path('/run/user').exists())
        self.assertFalse(pathlib.Path('/srv').exists())
        devices = pathlib.Path('/proc/net/dev').read_text()
        self.assertNotIn('eth0', devices)
        self.assertNotIn('wlan0', devices)

    def test_persistence_failure_after_mutation_rolls_back(self):
        import os
        from unittest.mock import patch
        real_save = backend.save
        count = [0]
        def interrupted(directory, record):
            count[0] += 1
            if count[0] == 2:
                raise OSError('simulated fsync failure')
            real_save(directory, record)
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'save', interrupted):
            with self.assertRaisesRegex(ValueError, 'rollback confirmed'):
                backend.action(backend.load_rows()[0]['id'], 'apply')
        self.assertEqual(self.values(), self.original)
        self.assertFalse(list((self.home / 'state').rglob('transaction.json')))

    def failed_active_publication(self, prior='timed', after_replace=True, row='warm', fail_intent=False):
        import json, os
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 1.2):
            old = None
            if prior:
                # Confirmed setup is not an expiry test; only its successor keeps the short lease.
                with patch.object(backend, 'TRIAL_SECONDS', 15 if prior == 'confirmed' else 1.2):
                    backend.action('grayscale', 'apply')
                if prior == 'confirmed':
                    self.confirm_trial('grayscale')
                old = json.loads(next((self.home / 'state').rglob('transaction.json')).read_text())
            previous = {k: self.values()[k] for k in backend.SCHEMA}
            real_save, real_write = backend.save, backend.write_value
            compensating, intents, writes = [False], [], []
            def save(directory, record):
                if record['phase'] == 'active' and not compensating[0]:
                    compensating[0] = True
                    if after_replace:
                        real_save(directory, record)
                    raise OSError('active publication failed')
                if compensating[0] and fail_intent:
                    raise OSError('cannot persist compensation intent')
                return real_save(directory, record)
            def write(key, value, expected):
                writes.append((key, value))
                if compensating[0]:
                    intents.append(json.loads(next((self.home / 'state').rglob('transaction.json')).read_text()))
                result = real_write(key, value, expected)
                if compensating[0]:
                    raise ValueError('compensation applied but acknowledgment lost')
                return result
            with patch.object(backend, 'save', save), patch.object(backend, 'write_value', write):
                with self.assertRaisesRegex(ValueError, 'retained'):
                    backend.action(row, 'apply')
        path = next((self.home / 'state').rglob('transaction.json'))
        return path, old, previous, intents, writes

    def assert_timed_recovery(self, path):
        import json, time
        record = json.loads(path.read_text())
        self.assertIn('deadline', record, 'compensation retired independent watchdog authority')
        limit = record['deadline'] + 3
        while path.exists() and time.monotonic() < limit:
            time.sleep(0.02)
        self.assertFalse(path.exists(), 'watchdog lost compensation ownership: ' + repr(record))
        self.assertEqual(self.values(), self.original)

    def test_active_replace_lost_compensation_ack_explicit_restore_from_confirmed(self):
        import json
        path, old, previous, intents, writes = self.failed_active_publication(prior='confirmed')
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.values(), self.original)
        self.assertFalse(path.exists())
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0]['phase'], 'pending')
        self.assertEqual(intents[0]['previous'], previous)
        self.assertEqual(intents[0]['before'], {k: self.original[k] for k in backend.SCHEMA})
        self.assertNotIn('token', old)

    def test_active_replace_lost_compensation_ack_timed_restore(self):
        import json
        path, old, previous, intents, writes = self.failed_active_publication()
        record = json.loads(path.read_text())
        self.assert_timed_recovery(path)
        self.assertEqual(record['phase'], 'pending')
        self.assertEqual(record['previous'], previous)
        for field in ['token', 'deadline', 'watchdog_pid']:
            self.assertEqual(record[field], intents[0][field])
        self.assertNotEqual(record['token'], old['token'])

    def test_active_before_replace_lost_compensation_ack_timed_restore(self):
        path, old, previous, intents, writes = self.failed_active_publication(after_replace=False)
        self.assert_timed_recovery(path)
        self.assertEqual(intents[0]['phase'], 'pending')
        self.assertEqual(intents[0]['previous'], previous)

    def test_active_replace_lost_compensation_ack_first_trial_timed_restore(self):
        path, old, previous, intents, writes = self.failed_active_publication(prior=None)
        self.assert_timed_recovery(path)
        self.assertEqual(intents[0]['phase'], 'pending')
        self.assertEqual(intents[0]['previous'], previous)

    def test_failed_compensation_intent_save_prevents_compensating_setters(self):
        import json
        path, old, previous, intents, writes = self.failed_active_publication(fail_intent=True)
        self.assertEqual(len(writes), 1, 'compensation ran without durable pending intent')
        self.assertFalse(intents)
        record = json.loads(path.read_text())
        self.assertEqual(record['phase'], 'active')
        self.assertEqual({k: self.values()[k] for k in backend.SCHEMA}, record['expected'])
        self.assert_timed_recovery(path)

    def test_failed_disable_publication_keeps_owner_during_lost_compensation_ack(self):
        import json
        path, old, previous, intents, writes = self.failed_active_publication(row='disable')
        record = json.loads(path.read_text())
        self.assert_timed_recovery(path)
        for field in ['token', 'deadline', 'watchdog_pid']:
            self.assertEqual(record[field], old[field])
            self.assertEqual(intents[0][field], old[field])
        self.assertEqual(record['phase'], 'pending')
        self.assertEqual(record['previous'], previous)

    def test_compensation_pending_journal_still_refuses_true_external_edit(self):
        import json, time
        path, old, previous, intents, writes = self.failed_active_publication()
        record, receipt = json.loads(path.read_text()), path.read_bytes()
        owned = self.values()
        edited = dict(owned, **{'decoration.screen_shader': '/external-owned.frag'})
        (self.home / 'compositor.json').write_text(json.dumps(edited))
        count = (self.home / 'eval-count').read_bytes()
        time.sleep(max(0, record['deadline'] + 1.2 - time.monotonic()))
        self.assertEqual(self.values(), edited)
        self.assertEqual(path.read_bytes(), receipt)
        self.assertEqual((self.home / 'eval-count').read_bytes(), count)
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('conflict', result['message'].lower())
        self.assertEqual(self.values(), edited)
        self.assertEqual(path.read_bytes(), receipt)
        (self.home / 'compositor.json').write_text(json.dumps(owned))
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def interrupted_compensation(self, stage, publication, operation):
        import json, os, signal, subprocess, time
        marker = self.home / 'compensation-paused.json'
        marker.unlink(missing_ok=True)
        caller = subprocess.Popen(['/usr/bin/python3', str(ROOT / 'tests/compensation_caller_fixture.py'),
                                   stage, publication, operation], env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            limit = time.monotonic() + 5
            while not marker.exists() and caller.poll() is None and time.monotonic() < limit:
                time.sleep(0.01)
            self.assertTrue(marker.exists(), 'caller never reached compensation boundary')
            evidence = json.loads(marker.read_text())
            self.assertEqual((evidence['pid'], evidence['pgid']), (caller.pid, caller.pid))
            os.killpg(caller.pid, signal.SIGKILL)
            out, err = caller.communicate(timeout=2)
            self.assertEqual(caller.returncode, -signal.SIGKILL)
            self.assertEqual((out, err), (b'', b''))
            path = next((self.home / 'state').rglob('transaction.json'))
            record = json.loads(path.read_text())
            self.assert_timed_recovery(path)
            self.assertEqual(record, evidence['journal'])
            self.assertEqual(record['phase'], 'pending')
            self.assertEqual(record['previous'], evidence['original']['expected'])
            self.assertEqual(record['before'], {k: self.original[k] for k in backend.SCHEMA})
            for field in ['token', 'deadline', 'watchdog_pid']:
                self.assertEqual(record[field], evidence['owner'][field])
                if operation != 'switch':
                    self.assertEqual(record[field], evidence['original'][field])
            if operation == 'switch':
                self.assertNotEqual(record['token'], evidence['original']['token'])
            if stage == 'rearm':
                self.assertEqual(evidence['candidate']['deadline'], evidence['original']['deadline'])
                self.assertNotEqual(evidence['candidate']['token'], record['token'])
            print('FIXTURE_EVIDENCE ' + json.dumps({'stage': 'compensation-' + stage,
                'publication': publication, 'operation': operation, 'caller_exit': caller.returncode,
                'phase': record['phase'], 'owner_preserved': True,
                'deadline': record['deadline'], 'baseline_restored': True}), flush=True)
        finally:
            if caller.poll() is None:
                os.killpg(caller.pid, signal.SIGKILL)
                caller.wait(timeout=2)
            caller.stdout.close()
            caller.stderr.close()

    def test_compensation_group_kill_before_and_after_active_replace(self):
        for publication in ['before', 'after']:
            with self.subTest(publication=publication):
                self.interrupted_compensation('compensation', publication, 'switch')

    def test_predecessor_rearm_group_kill_keeps_successor_owner(self):
        self.interrupted_compensation('rearm', 'after', 'switch')

    def test_restore_unlink_failure_compensation_group_kill_preserves_owner(self):
        for publication in ['before', 'after']:
            with self.subTest(publication=publication):
                self.interrupted_compensation('compensation', publication, 'restore')

    def test_disable_compensation_group_kill_preserves_owner(self):
        self.interrupted_compensation('compensation', 'after', 'disable')

    def test_successful_compensation_rearms_predecessor_without_extending_deadline(self):
        import json, os
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 1.2):
            backend.action('grayscale', 'apply')
            path = next((self.home / 'state').rglob('transaction.json'))
            old = json.loads(path.read_text())
            real_save = backend.save
            failed = [False]
            def save(directory, record):
                real_save(directory, record)
                if record['phase'] == 'active' and not failed[0]:
                    failed[0] = True
                    raise OSError('active publication replaced then failed')
            with patch.object(backend, 'save', save):
                with self.assertRaisesRegex(ValueError, 'rollback confirmed'):
                    backend.action('warm', 'apply')
        record = json.loads(path.read_text())
        self.assertEqual(record['id'], 'grayscale')
        self.assertEqual(record['phase'], 'active')
        self.assertEqual(record['deadline'], old['deadline'])
        self.assertNotEqual(record['token'], old['token'])
        self.assertEqual(record['before'], old['before'])
        self.assertEqual({k: self.values()[k] for k in backend.SCHEMA}, old['expected'])
        self.assert_timed_recovery(path)

    def test_failed_predecessor_rearm_keeps_current_pending_owner(self):
        import json, os
        from unittest.mock import patch
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 1.2):
            backend.action('grayscale', 'apply')
            path = next((self.home / 'state').rglob('transaction.json'))
            old = json.loads(path.read_text())
            real_save, real_start = backend.save, backend.start_watchdog
            failed, owner = [False], []
            def save(directory, record):
                real_save(directory, record)
                if record['phase'] == 'active' and not failed[0]:
                    failed[0] = True
                    owner.append(json.loads(path.read_text()))
                    raise OSError('active publication replaced then failed')
            def start(directory, record, preserve_deadline=False):
                if failed[0]:
                    raise OSError('predecessor rearm unavailable')
                return real_start(directory, record, preserve_deadline)
            with patch.object(backend, 'save', save), patch.object(backend, 'start_watchdog', start):
                with self.assertRaisesRegex(ValueError, 'retained'):
                    backend.action('warm', 'apply')
        record = json.loads(path.read_text())
        self.assert_timed_recovery(path)
        self.assertEqual(record['phase'], 'pending')
        self.assertEqual(record['previous'], old['expected'])
        for field in ['token', 'deadline', 'watchdog_pid']:
            self.assertEqual(record[field], owner[0][field])

    def test_profiles_never_reenable_disabled_motion(self):
        import json
        self.original['animations.enabled'] = False
        (self.home / 'compositor.json').write_text(json.dumps(self.original))
        rows = backend.load_rows() if backend.SLUG != 'shader-deck' else backend.load_rows()[:1]
        for row in rows:
            code, result = self.cli('action', '--id', row['id'], '--verb', 'apply', '--apply')
            self.assertEqual(code, 0, result)
            self.assertIs(self.values()['animations.enabled'], False)
        self.assertEqual(self.cli('action', '--id', rows[0]['id'], '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def test_child_closing_stdout_then_hanging_is_plain_timeout(self):
        row = backend.load_rows()[0]
        code, result = self.cli('action','--id',row['id'],'--verb','apply','--apply',
                                extra={'FIXTURE_CLOSE_STDOUT':'1'})
        self.assertNotEqual(code,0)
        self.assertIn('timed out',result['message'])
        self.assertEqual(self.values(),self.original)

    def test_strict_data_validation_and_no_code_fields(self):
        self.assertTrue(callable(getattr(backend, "validate_rows", None)), "strict validation missing")
        rows = backend.load_rows()
        self.assertEqual(backend.validate_rows(rows), rows)
        import copy
        for value in [None, [], rows * 100, [dict(rows[0], code="os.execute('bad')")],
                      [rows[0], rows[0]], [dict(rows[0], id="../bad")],
                      [dict(rows[0], label="X" * 129)],
                      [dict(rows[0], settings={"exec": "bad"})]]:
            with self.subTest(value=str(value)[:80]):
                with self.assertRaises(ValueError):
                    backend.validate_rows(value)
        row = copy.deepcopy(rows[0])
        key = next(iter(row["settings"]))
        row["settings"][key] = "hl.dispatch('exit')"
        with self.assertRaises(ValueError):
            backend.validate_rows([row])

    def test_cli_refuses_action_without_explicit_apply(self):
        import subprocess, json
        p = subprocess.run(["/usr/bin/python3", str(RUNTIME / "backend.py"),
                            "action", "--id", "bad", "--verb", "apply"], capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0, "action lacks explicit apply guard")
        self.assertFalse(json.loads(p.stdout)["ok"])

    def test_catalog_is_bounded_and_has_unique_known_rows(self):
        self.assertTrue(callable(getattr(backend, "catalog", None)), "catalog behavior is missing")
        result = backend.catalog()
        self.assertEqual(result["actions"], ["apply", "restore", "confirm", "favorite", "preview", "compare"])
        self.assertEqual(result["actionLabel"], "Apply")
        rows = result["rows"]
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertTrue(all({"id", "label", "detail"} <= set(r) <= {"id", "label", "detail", "favorite", "preview"} for r in rows))
        self.assertTrue(all(type(r["favorite"]) is bool for r in rows))

if __name__ == "__main__":
    unittest.main()
