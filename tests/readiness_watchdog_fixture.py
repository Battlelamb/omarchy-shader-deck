#!/usr/bin/python3
"""Slow the real readiness writer before its PID bytes become visible."""
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
real_fdopen = backend.os.fdopen
def delayed(fd, *args, **kwargs):
    path = os.readlink('/proc/self/fd/' + str(fd))
    if Path(path).name.startswith(('.ready-', '.watchdog-')):
        (Path.home() / 'readiness-paused').write_text(path)
        time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0.15)
    return real_fdopen(fd, *args, **kwargs)
backend.os.fdopen = delayed
backend.watchdog(sys.argv[1])
