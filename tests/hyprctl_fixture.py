#!/usr/bin/python3
"""Offline CLI fixture: runs real Lua against fake hl, never connects IPC."""
import json
import os
from pathlib import Path
import subprocess
import sys

HOME = Path(os.environ['HOME'])
statefile = HOME / 'compositor.json'
args = sys.argv[1:]
with (HOME / 'calls.jsonl').open('a') as f:
    f.write(json.dumps(args) + '\n')
state = json.loads(statefile.read_text())
# Shared fake IPC outage also reaches detached children with a minimal environment.
if (HOME / 'ipc-outage').exists():
    with (HOME / 'outage-calls.jsonl').open('a') as f:
        f.write(json.dumps(args) + '\n')
    sys.exit(1)
if args[:1] == ['eval'] and (HOME / 'fail-next-setter').exists():
    (HOME / 'fail-next-setter').unlink()
    (HOME / 'ipc-outage').touch()
    (HOME / 'outage-start.json').write_text(json.dumps({
        'pid': os.getppid(), 'calls': (HOME / 'calls.jsonl').read_text()}))
    sys.exit(1)
if os.environ.get('FIXTURE_CLOSE_STDOUT'):
    os.close(1)
    os.close(2)
    import time
    time.sleep(20)
if os.environ.get('FIXTURE_FLOOD'):
    os.write(1, b'x' * 131072)
    sys.exit(0)
if os.environ.get('FIXTURE_HANG'):
    import time
    time.sleep(20)
if os.environ.get('FIXTURE_MALFORMED') and (args[-1:] == ['version'] or os.environ['FIXTURE_MALFORMED'] == 'option' and args[:2] == ['-j','getoption']):
    if os.environ['FIXTURE_MALFORMED'] != 'option' or args[:2] == ['-j','getoption']:
        print('[]')
        sys.exit(0)
if args == ['-j', 'version']:
    blocker = HOME / 'block-new-watchdog'
    if blocker.exists() and os.getppid() != int(blocker.read_text()):
        (HOME / 'blocked-watchdog').write_text(str(os.getppid()))
        import time
        while blocker.exists():
            time.sleep(0.01)
    print(json.dumps({'version': os.environ.get('FIXTURE_VERSION', '0.56.2')}))
elif args[:2] == ['-j', 'getoption']:
    key = args[2]
    value = state[key]
    if type(value) is bool: kind = 'bool'
    elif type(value) is int: kind = 'int'
    elif type(value) is list:
        kind, value = 'css', ' '.join(map(str, value))
    else: kind = 'str'
    # Model transport spelling independently from the actual Lua string value.
    if key == 'decoration.screen_shader' and value == '' and (HOME / 'empty-getoption-sentinel').exists():
        value = '[[EMPTY]]'
    print(json.dumps({'option': key, kind: value, 'set': True}))
elif args and args[0] == 'eval':
    countfile = HOME / 'eval-count'
    count = int(countfile.read_text()) + 1 if countfile.exists() else 1
    countfile.write_text(str(count))
    failures = {int(v) for v in os.environ.get('FIXTURE_FAILS', '').split(',') if v}
    fail_at = count if count in failures else int(os.environ.get('FIXTURE_FAIL_AT', '0'))
    if count == fail_at and os.environ.get('FIXTURE_DELAY_FAIL'):
        import time
        time.sleep(float(os.environ['FIXTURE_DELAY_FAIL']))
    if count == fail_at and (not os.environ.get('FIXTURE_FAIL_AFTER') or (failures and count != min(failures))):
        print('error: fixture rejected setter')
        sys.exit(0)
    def literal(value):
        if type(value) is bool: return str(value).lower()
        if type(value) is int: return str(value)
        if type(value) is list:
            return '{' + ','.join(k+'='+str(v) for k,v in zip(['top','right','bottom','left'],value)) + '}'
        return json.dumps(value, ensure_ascii=False)
    source = 'local current={' + ','.join('['+json.dumps(k)+']='+literal(v) for k,v in state.items()) + '}\n'
    source += '''hl={}
function hl.get_config(k) return current[k] end
function hl.config(t)
 for k,v in pairs(t) do
  if type(v)=="table" then
   io.write("SET\\t",k,"\\t[",v.top,",",v.right,",",v.bottom,",",v.left,"]\\n")
  elseif type(v)=="string" then
   io.write("SET\\t",k,"\\t",string.format("%q",v),"\\n")
  else io.write("SET\\t",k,"\\t",tostring(v),"\\n") end
  current[k]=v
 end
end
'''
    source += '\n' + args[1]
    p = subprocess.run(['/usr/bin/lua', '-'], input=source, text=True, capture_output=True, timeout=4)
    for line in p.stdout.splitlines():
        if line.startswith('SET\t'):
            _,key,value = line.split('\t',2)
            assigned = json.loads(value)
            with (HOME / 'assignments.jsonl').open('a') as f:
                f.write(json.dumps({'key': key, 'value': assigned}) + '\n')
            state[key] = assigned
            if key == 'decoration.screen_shader':
                # C++ stores the raw spelling; Lua push/renderer treat the sentinel as empty.
                marker = HOME / 'empty-getoption-sentinel'
                if assigned == '[[EMPTY]]':
                    state[key] = ''
                    marker.touch()
                else:
                    marker.unlink(missing_ok=True)
    statefile.write_text(json.dumps(state))
    if os.environ.get('FIXTURE_KILL_CALLER'):
        import signal
        os.kill(os.getppid(), signal.SIGKILL)
    if p.returncode or count == fail_at:
        print('error: ' + p.stderr[:150] if p.returncode else 'error: failure after mutation')
    else:
        print('ok')
else:
    print('error: unsupported shim argv')
    sys.exit(2)
