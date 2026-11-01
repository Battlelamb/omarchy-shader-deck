#!/usr/bin/python3
"""Run backend tests offline. No compositor socket, GUI, real HOME or network."""
import pathlib
import re
import subprocess
import sys

project = pathlib.Path(__file__).resolve().parents[1]
label = sys.argv[1] if len(sys.argv) == 2 else ''
if not re.fullmatch('[a-z0-9-]{1,64}', label):
    raise SystemExit('Usage: python3 tests/run-sandbox.py <unique-receipt-label>')
output = project / 'release-output'
output.mkdir(exist_ok=True)
receipt = output / (label + '.log')
if receipt.exists():
    raise SystemExit('Receipt already exists; use a new label (failed evidence is immutable)')
command = ['/usr/bin/timeout', '--kill-after=2', '90', '/usr/bin/bwrap',
    '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
    '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
    '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
    '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run',
    '--dir', '/home/test', '--ro-bind', str(project), '/src',
    '--setenv', 'HOME', '/home/test', '--setenv', 'TMPDIR', '/tmp',
    '--setenv', 'PATH', '/usr/bin', '--setenv', 'LANG', 'C.UTF-8',
    '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '--chdir', '/src',
    '/usr/bin/env', '-u', 'PYTHONPATH', '/usr/bin/python3', '-m', 'unittest',
    'discover', '-s', 'tests', '-p', 'test_*.py', '-v']
result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=98)
with receipt.open('xb') as stream:
    stream.write(result.stdout + b'\nWRAPPER_EXIT=' + str(result.returncode).encode() + b'\n')
print(result.stdout.decode(errors='replace'))
print('Receipt:', receipt, 'Exit:', result.returncode)
sys.exit(result.returncode)
