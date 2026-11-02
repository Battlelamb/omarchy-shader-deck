"""Shader Deck v0.3.0 offline behavioral evidence, not GPU qualification."""
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import time
import unittest
from unittest.mock import patch
import test_backend as base

backend = base.backend
RUNTIME = base.RUNTIME


class AdvancedTests(unittest.TestCase):
    home: pathlib.Path
    env: dict[str, str]
    setUp = base.BackendTests.setUp
    cli = base.BackendTests.cli
    values = base.BackendTests.values

    def test_every_runtime_and_test_python_source_compiles_without_bytecode_writes(self):
        files=[*RUNTIME.rglob('*.py'),*(base.ROOT/'tests').glob('*.py')]
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path.name):
                compile(path.read_bytes(),str(path),'exec')

    def test_recent_storage_failure_does_not_fabricate_apply_failure(self):
        ident=backend.load_rows()[0]['id']
        with patch.dict(os.environ,self.env,clear=True),patch.object(backend.preferences,'remember',side_effect=OSError('fixture write refusal')):
            result=backend.action(ident,'apply')
        self.assertTrue(result['ok'])
        self.assertIn('warning',result['message'].lower())
        self.assertNotEqual(self.values(),self.original)
        self.assertEqual(self.cli('action','--id','restore:last','--verb','restore','--apply')[0],0)
        self.assertEqual(self.values(),self.original)

    def test_large_valid_preferences_cannot_overflow_catalog_or_hide_confirmed_action(self):
        ids=[str(i).zfill(3)+'x'*200 for i in range(512)]
        with patch.dict(os.environ,self.env,clear=True):
            prefs=backend.preferences.change(backend.SLUG,backend.PREFERENCE_SCHEMA,{})
        prefs['collections']={'group-'+str(i):ids for i in range(16)}
        # Seed a validated legacy store; normal new writes correctly reject this size.
        path=self.home/'.config/omarchy/lego'/backend.SLUG/'preferences.json'
        path.write_text(json.dumps(prefs))
        self.assertGreater(path.stat().st_size,1048576)
        with patch.dict(os.environ,self.env,clear=True):
            self.assertEqual(backend.preferences.read(backend.SLUG,backend.PREFERENCE_SCHEMA),prefs)
        code,result=self.cli('catalog')
        self.assertNotEqual(code,0)
        self.assertFalse(result['ok'])
        self.assertIn('limit',result['message'].lower())
        ident=backend.load_rows()[0]['id']
        code,result=self.cli('action','--id',ident,'--verb','apply','--apply')
        self.assertEqual(code,0,result)
        self.assertTrue(result['ok'])
        self.assertIn('warning',result['message'].lower())
        self.assertNotEqual(self.values(),self.original)
        self.assertEqual(self.cli('action','--id','restore:last','--verb','restore','--apply')[0],0)
        self.assertEqual(self.values(),self.original)

    def test_json_file_reads_reject_symlinks_duplicates_and_special_files(self):
        data = self.home / 'source.json'
        data.write_text('{"valid":true}')
        link = self.home / 'link.json'
        link.symlink_to(data)
        with self.assertRaises(ValueError):
            backend.bounded_json(link)
        data.write_text('{"key":1,"key":2}')
        with self.assertRaises(ValueError):
            backend.bounded_json(data)
        fifo = self.home / 'pipe.json'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            backend.bounded_json(fifo)
        self.assertTrue(link.is_symlink())
        self.assertEqual(data.read_text(), '{"key":1,"key":2}')

    def test_unexpected_cli_options_fail_as_json_without_side_effects(self):
        for args in [('catalog', '--bogus'), ('catalog', '--payload', '{}'),
                     ('catalog', '--apply'), ('preferences', '--id', 'unknown'),
                     ('preferences', '--payload', '{"options":{}}'),
                     ('preferences', '--apply', '--payload', '{"recent":[]}')]:
            with self.subTest(args=args):
                code, result = self.cli(*args)
                self.assertNotEqual(code, 0)
                self.assertFalse(result['ok'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / '.config').exists())

    def test_compare_is_readonly_and_preview_has_real_independent_keep_restore(self):
        code, compared = self.cli('action', '--id', 'sepia', '--verb', 'compare', '--apply')
        self.assertEqual(code, 0, compared)
        self.assertEqual(pathlib.Path(compared['preview']).read_bytes(), (RUNTIME/'data/comparisons/sepia.png').read_bytes())
        self.assertIn('100%', compared['detail'])
        self.assertFalse((self.home / 'calls.jsonl').exists())
        self.assertFalse((self.home / 'state').exists())
        script = "import runpy,json,time; b=runpy.run_path(" + repr(str(RUNTIME/'backend.py')) + "); b['action'].__globals__['TRIAL_SECONDS']=0.8; print(json.dumps(b['action']('sepia','preview')),flush=True); time.sleep(30)"
        caller = subprocess.Popen(['/usr/bin/python3','-c',script],env=self.env,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            self.assertTrue(json.loads(caller.stdout.readline())['ok'])
            record = next((self.home / 'state').rglob('transaction.json'))
            owner = json.loads(record.read_text())
            self.assertNotEqual(os.getsid(owner['watchdog_pid']), caller.pid)
            os.killpg(caller.pid, signal.SIGKILL)
            caller.communicate(timeout=2)
            self.assertEqual(caller.returncode, -9)
            base.BackendTests.assert_timed_recovery(self, record)
        finally:
            if caller.poll() is None:
                os.killpg(caller.pid, signal.SIGKILL)
                caller.wait(timeout=2)
            caller.stdout.close()
            caller.stderr.close()
        self.assertEqual(self.cli('action', '--id', 'sepia', '--verb', 'preview', '--apply')[0], 0)
        self.assertEqual(self.cli('action', '--id', 'sepia', '--verb', 'confirm', '--apply')[0], 0)
        saved = self.values()
        path = next((self.home / 'state').rglob('transaction.json'))
        self.assertNotIn('token', json.loads(path.read_text()))
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        self.assertNotEqual(saved, self.original)

    def test_edited_generated_shader_blocks_restore_without_clobbering(self):
        self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"options":{"intensity":50}}')[0], 0)
        self.assertEqual(self.cli('action', '--id', 'dim', '--verb', 'apply', '--apply')[0], 0)
        self.assertEqual(self.cli('action', '--id', 'dim', '--verb', 'confirm', '--apply')[0], 0)
        shader = pathlib.Path(self.values()['decoration.screen_shader'])
        original = shader.read_bytes()
        shader.write_bytes(original + b'\n// external edit\n')
        receipt = next((self.home / 'state').rglob('transaction.json'))
        saved, count, current = receipt.read_bytes(), (self.home / 'eval-count').read_bytes(), self.values()
        code, result = self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')
        self.assertNotEqual(code, 0)
        self.assertIn('shader', result['message'].lower())
        self.assertEqual(receipt.read_bytes(), saved)
        self.assertEqual((self.home / 'eval-count').read_bytes(), count)
        self.assertEqual(self.values(), current)
        self.assertEqual(shader.read_bytes(), original + b'\n// external edit\n')
        shader.write_bytes(original)
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)

    def test_saved_intensity_generates_bounded_shader_and_independent_rollback(self):
        code, prefs = self.cli('preferences')
        self.assertEqual(code, 0, prefs)
        self.assertEqual(prefs['preferences']['options']['intensity'], 100)
        self.assertFalse((self.home / '.config').exists())
        code, prefs = self.cli('preferences', '--apply', '--payload', '{"options":{"intensity":50}}')
        self.assertEqual(code, 0, prefs)
        with patch.dict(os.environ, self.env, clear=True), patch.object(backend, 'TRIAL_SECONDS', 0.7):
            result = backend.action('cool', 'apply')
        self.assertTrue(result['ok'])
        selected = pathlib.Path(self.values()['decoration.screen_shader'])
        source = selected.read_text()
        self.assertIn('mix(pix.rgb, filtered.rgb, 0.50)', source)
        self.assertIn('pix.a', source)
        self.assertLess(len(source.encode()), 16384)
        self.assertEqual(selected.stat().st_mode & 0o777, 0o600)
        record = next((self.home / 'state').rglob('transaction.json'))
        base.BackendTests.assert_timed_recovery(self, record)
        self.assertEqual(self.cli('preferences')[1]['preferences']['recent'][0], 'cool')
        self.assertEqual(self.cli('preferences', '--apply', '--payload', '{"options":{"intensity":0}}')[0], 0)
        self.assertEqual(self.cli('action', '--id', 'dim', '--verb', 'apply', '--apply')[0], 0)
        self.assertEqual(self.values()['decoration.screen_shader'], '')
        self.assertEqual(self.cli('action', '--id', 'restore:last', '--verb', 'restore', '--apply')[0], 0)
        self.assertEqual(self.values(), self.original)
        self.assertEqual(self.cli('action', '--id', 'sepia', '--verb', 'favorite', '--apply')[0], 0)
        self.assertTrue(next(r for r in self.cli('catalog')[1]['rows'] if r['id']=='sepia')['favorite'])

    def test_five_shader_variants_have_real_local_comparison_images(self):
        code, result = self.cli('catalog')
        self.assertEqual(code, 0, result)
        rows = {r['id']:r for r in result['rows']}
        required = {'cool', 'sepia', 'softcontrast', 'dim', 'grayscale'}
        self.assertTrue(required <= rows.keys(), required - rows.keys())
        hashes = set()
        for key in sorted(required):
            row = rows[key]
            path = pathlib.Path(row['preview'])
            self.assertTrue(path.is_absolute())
            data = path.read_bytes()
            self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
            hashes.add(hashlib.sha256(data).hexdigest())
            self.assertIn('reference', row['detail'].lower())
            shader = RUNTIME / 'data/shaders' / (key + '.frag')
            self.assertTrue(shader.is_file())
            self.assertIn('pix.a', shader.read_text())
        self.assertEqual(len(hashes), 5)
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / 'calls.jsonl').exists())
