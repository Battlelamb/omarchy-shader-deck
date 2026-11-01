import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backend", ROOT / "runtime/0.1.0/backend.py")
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
        p = subprocess.run(['/usr/bin/python3', str(ROOT / 'runtime/0.1.0/backend.py'), *args],
                           env=dict(self.env, **(extra or {})), capture_output=True, timeout=25)
        self.assertLess(len(p.stdout), 1048576)
        self.assertEqual(p.stderr, b'', p.stderr)
        return p.returncode, json.loads(p.stdout)

    def values(self):
        import json
        return json.loads((self.home / 'compositor.json').read_text())

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

    def test_empty_sentinel_and_literal_previous_shader_restore_exactly(self):
        import json
        for previous in ['[[EMPTY]]', '', '/old/a \"quote\"; os.execute(\"bad\"); ü.frag']:
            with self.subTest(previous=previous):
                self.original['decoration.screen_shader'] = previous
                (self.home / 'compositor.json').write_text(json.dumps(self.original))
                code, result = self.cli('action', '--id', 'grayscale', '--verb', 'apply', '--apply')
                self.assertEqual(code, 0, result)
                code, result = self.cli('action', '--id', 'disable', '--verb', 'restore', '--apply')
                self.assertEqual(code, 0, result)
                self.assertEqual(self.values(), self.original)

    def test_default_watchdog_survives_killed_ui_process_group(self):
        import subprocess, json, time, os, signal
        script = "import runpy,json,time; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); print(json.dumps(b['action']('warm','apply')),flush=True); time.sleep(30)"
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
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.8; b['action']('grayscale','apply'); b['action']('warm','apply')"
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
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.5; b['action']('grayscale','apply'); b['action'].__globals__['TRIAL_SECONDS']=2;\ntry: b['action']('warm','apply')\nexcept ValueError: pass"
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
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.7; b['action']('warm','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script], env=dict(self.env,FIXTURE_KILL_CALLER='1'),
                           capture_output=True,timeout=6)
        self.assertEqual(p.returncode, -9)
        recordfile = next((self.home / 'state').rglob('transaction.json'))
        deadline = time.monotonic() + 5
        while recordfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(recordfile.exists())
        self.assertEqual(self.values(), self.original)

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
        import subprocess,json,time
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.6; b['action']('warm','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script],env=self.env,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        external = self.values()
        external['decoration.screen_shader'] = '/external-owned.frag'
        (self.home / 'compositor.json').write_text(json.dumps(external))
        time.sleep(1.6)
        self.assertEqual(self.values(),external)
        self.assertTrue(list((self.home / 'state').rglob('transaction.json')))
        code,result = self.cli('action','--id','warm','--verb','restore','--apply')
        self.assertNotEqual(code,0)
        self.assertIn('conflict',result['message'].lower())

    def test_confirm_keeps_only_current_trial_and_preserves_restore(self):
        import subprocess,time
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.9; b['action']('grayscale','apply')"
        p = subprocess.run(['/usr/bin/python3','-c',script],env=self.env,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        code,result = self.cli('action','--id','grayscale','--verb','confirm','--apply')
        self.assertEqual(code,0,result)
        time.sleep(1.5)
        self.assertTrue(self.values()['decoration.screen_shader'].endswith('grayscale.frag'))
        self.assertEqual(self.cli('action','--id','grayscale','--verb','restore','--apply')[0],0)
        self.assertEqual(self.values(),self.original)

    def test_confirm_wrong_selected_id_cannot_keep_other_effect(self):
        import subprocess,time
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.7; b['action']('grayscale','apply')"
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
        script = "import runpy; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.5; b['action']('warm','apply')"
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

    def test_shader_assets_are_fixed_useful_programs(self):
        for name in ['grayscale', 'warm']:
            path = ROOT / 'runtime/0.1.0/data/shaders' / (name + '.frag')
            self.assertTrue(path.is_file(), 'shader asset missing: ' + name)
            source = path.read_text()
            self.assertTrue(source.startswith('#version 300 es'))
            self.assertIn('texture(tex, v_texcoord)', source)
            self.assertIn('pix.a', source)
            self.assertNotIn('#include', source)
        self.assertIn('0.2126', (ROOT / 'runtime/0.1.0/data/shaders/grayscale.frag').read_text())
        self.assertIn('0.88', (ROOT / 'runtime/0.1.0/data/shaders/warm.frag').read_text())

    def test_watchdog_survives_ui_process_exit_and_reverts(self):
        import subprocess, json, time, os
        # Change a Python constant only in the disposable UI caller; no production env bypass.
        script = "import runpy,json; b=runpy.run_path(" + repr(str(ROOT / 'runtime/0.1.0/backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.7; print(json.dumps(b['action']('grayscale','apply')))"
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
        self.assertFalse(pathlib.Path('/srv/projects').exists())
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
        p = subprocess.run(["/usr/bin/python3", str(ROOT / "runtime/0.1.0/backend.py"),
                            "action", "--id", "bad", "--verb", "apply"], capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0, "action lacks explicit apply guard")
        self.assertFalse(json.loads(p.stdout)["ok"])

    def test_catalog_is_bounded_and_has_unique_known_rows(self):
        self.assertTrue(callable(getattr(backend, "catalog", None)), "catalog behavior is missing")
        result = backend.catalog()
        self.assertEqual(result["actions"], ["apply", "restore", "confirm"])
        self.assertEqual(result["actionLabel"], "Apply")
        rows = result["rows"]
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertTrue(all(set(r) == {"id", "label", "detail"} for r in rows))

if __name__ == "__main__":
    unittest.main()
