#!/usr/bin/python3
"""Test-owned caller paused after real compensation or before predecessor publication."""
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
stage, publication, operation = sys.argv[1:]
backend.TRIAL_SECONDS = 1.2
backend.action('grayscale', 'apply')
path = next((home / 'state').rglob('transaction.json'))
original = json.loads(path.read_text())
backend.TRIAL_SECONDS = 1.8
failed = False
owner = None


def pause(candidate=None):
    evidence = {'pid': os.getpid(), 'pgid': os.getpgrp(), 'stage': stage,
                'publication': publication, 'operation': operation, 'original': original,
                'owner': owner, 'candidate': candidate, 'journal': json.loads(path.read_text())}
    (home / '.compensation-paused.json').write_text(json.dumps(evidence))
    (home / '.compensation-paused.json').replace(home / 'compensation-paused.json')
    while True:
        time.sleep(0.1)


real_save = backend.save

def save(directory, record):
    global failed, owner
    if stage == 'rearm' and failed and record['phase'] == 'active':
        pause(record)
    if operation != 'restore' and record['phase'] == 'active' and not failed:
        owner = json.loads(path.read_text())
        failed = True
        if publication == 'after':
            real_save(directory, record)
        raise OSError('active publication failed')
    return real_save(directory, record)


real_unlink = Path.unlink

def unlink(self, *args, **kwargs):
    global failed, owner
    if operation == 'restore' and self == path and not failed:
        owner = json.loads(path.read_text())
        failed = True
        if publication == 'after':
            real_unlink(self, *args, **kwargs)
        raise OSError('restore journal removal failed')
    return real_unlink(self, *args, **kwargs)


real_write = backend.write_value

def write(key, value, expected):
    result = real_write(key, value, expected)
    if failed and stage == 'compensation':
        pause()
    return result


backend.save = save
backend.write_value = write
Path.unlink = unlink
backend.action('grayscale' if operation == 'restore' else ('disable' if operation == 'disable' else 'warm'),
               'restore' if operation == 'restore' else 'apply')
raise SystemExit('compensation boundary not reached')
