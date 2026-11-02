#!/usr/bin/python3
"""Disposable caller paused at an exact transaction boundary for group SIGKILL."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('backend', root / Path(json.loads((root / 'manifest.json').read_text())['entryPoints']['overlay']).parent / 'backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
home = Path(os.environ['HOME'])
stage, verb, row = sys.argv[1:]
backend.TRIAL_SECONDS = 1.2
backend.action('grayscale', 'apply')
recordfile = next((home / 'state').rglob('transaction.json'))
original = json.loads(recordfile.read_text())
(home / 'original-trial.json').write_text(json.dumps(original))
backend.TRIAL_SECONDS = 5

def pause():
    (home / '.interrupted.json').write_text(json.dumps({
        'stage': stage, 'pid': os.getpid(), 'pgid': os.getpgrp(),
        'ready': [p.read_text() for p in recordfile.parent.glob('.ready-*')],
        'journal': json.loads(recordfile.read_text())}))
    (home / '.interrupted.json').replace(home / 'interrupted.json')
    while True:
        time.sleep(0.1)

real_save = backend.save
def save(directory, record):
    if (stage == 'ready' and record.get('token') != original['token']
            and (directory / ('.ready-' + record.get('token', ''))).exists()):
        pause()
    real_save(directory, record)
    if stage == 'pending' and record['phase'] == 'pending':
        pause()
backend.save = save
real_popen = backend.subprocess.Popen
def launch(argv, **kwargs):
    if 'watchdog' in argv:
        if stage == 'startup':
            pause()
        if stage == 'spawned':
            (home / 'block-new-watchdog').write_text(str(original['watchdog_pid']))
            process = real_popen(argv, **kwargs)
            pause()
    return real_popen(argv, **kwargs)
backend.subprocess.Popen = launch
backend.action(row, verb)
raise SystemExit('interruption boundary not reached')
