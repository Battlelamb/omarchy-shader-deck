#!/usr/bin/python3
"""Constrained runtime presets. No startup config changes. GPL-3.0-only."""
import argparse
import json
import re
import sys
from pathlib import Path

SLUG = 'shader-deck'
DATA = Path(__file__).resolve().parent / 'data'
SCHEMAS = {
    'motion-presets': {'animations.enabled': 'bool', 'animations.workspace_wraparound': 'bool'},
    'workspace-profiles': {'general.gaps_in': 'gap', 'general.gaps_out': 'gap',
        'general.border_size': 'int', 'decoration.rounding': 'int',
        'decoration.blur.enabled': 'bool', 'decoration.shadow.enabled': 'bool'},
    'shader-deck': {'decoration.screen_shader': 'shader'},
}
SCHEMA = SCHEMAS[SLUG] if SLUG != 'TEMPLATE' else {}


def bounded_json(path):
    with open(path, 'rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Data exceeds 64 KiB limit')
    return json.loads(raw)


def valid_value(key, value, preset=False):
    kind = SCHEMA.get(key)
    if kind == 'bool':
        return type(value) is bool
    if kind == 'int':
        return type(value) is int and 0 <= value <= 100
    if kind == 'gap':
        return (type(value) is list and len(value) == 4
                and all(type(v) is int and 0 <= v <= 10000 for v in value))
    if kind == 'shader':
        if preset:
            return value in ('', '@grayscale.frag', '@warm.frag')
        return (type(value) is str and len(value) <= 4096
                and not any(ord(c) < 32 or ord(c) == 127 for c in value)
                and (value in ('', '[[EMPTY]]') or value.startswith('/')))
    return False


def validate_rows(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 64:
        raise ValueError('Expected 1–64 known preset rows')
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {'id', 'label', 'detail', 'settings'}:
            raise ValueError('Preset fields must be id, label, detail, settings only')
        for key, maximum in [('id', 64), ('label', 128), ('detail', 512)]:
            value = row[key]
            if type(value) is not str or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
                raise ValueError('Invalid preset text')
        if not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', row['id']) or row['id'] in seen:
            raise ValueError('Invalid or duplicate preset ID')
        seen.add(row['id'])
        values = row['settings']
        if type(values) is not dict or not values or not set(values) <= set(SCHEMA):
            raise ValueError('Unsupported preset settings')
        if any(not valid_value(k, v, True) for k, v in values.items()):
            raise ValueError('Invalid preset setting value')
        if SLUG == 'motion-presets' and values.get('animations.enabled') is True:
            raise ValueError('Motion presets cannot enable previously disabled animations')
    return rows


def load_rows():
    return validate_rows(bounded_json(DATA / 'presets.json'))


def catalog():
    return {'rows': [{k: r[k] for k in ('id', 'label', 'detail')} for r in load_rows()],
            'actions': ['apply', 'restore', 'confirm'], 'actionLabel': 'Apply',
            'message': 'Explicit runtime Apply only; Restore preserves prior values. Not enabled at startup.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['catalog', 'action', 'watchdog'])
    parser.add_argument('--token', default='')
    parser.add_argument('--id', default='')
    parser.add_argument('--verb', default='')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'watchdog':
            result = watchdog(args.token)
        elif args.command == 'catalog':
            result = catalog()
        else:
            if not args.apply:
                raise ValueError('Action requires explicit --apply')
            result = action(args.id, args.verb)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'message': str(error)[:300]}))
        return 1


# These helpers are copied locally into each independent plugin, not a runtime dependency.
import contextlib
import fcntl
import hashlib
import os
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time


def run_hypr(*args):
    tool = shutil.which('hyprctl')
    if not tool:
        raise ValueError('hyprctl is unavailable; install a compatible Omarchy session separately')
    p = subprocess.Popen([tool, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    collected = bytearray()
    deadline = time.monotonic() + 3
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('hyprctl timed out; snapshot retained for Restore')
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                    collected.extend(data)
                    if len(collected) > 65536:
                        raise ValueError('hyprctl output exceeded 64 KiB')
            p.wait(timeout=max(0.001, deadline - time.monotonic()))
        if p.returncode:
            raise ValueError('hyprctl failed; check compositor availability')
        return collected.decode('utf-8').strip()
    except subprocess.TimeoutExpired:
        raise ValueError('hyprctl timed out; snapshot retained for Restore') from None
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        p.stdout.close()


def session():
    instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if not re.fullmatch('[a-zA-Z0-9_.-]{1,128}', instance):
        raise ValueError('No valid Hyprland session; open from your compositor session')
    info = json.loads(run_hypr('-j', 'version'))
    if type(info) is not dict or info.get('version') != '0.56.2':
        raise ValueError('Adapter requires qualified Hyprland Lua 0.56.2; other versions fail closed')
    return instance


def read_values():
    result = {}
    for key, kind in SCHEMA.items():
        row = json.loads(run_hypr('-j', 'getoption', key))
        if type(row) is not dict or row.get('option') != key:
            raise ValueError('Unexpected compositor option response')
        field = {'gap': 'css', 'shader': 'str'}.get(kind, kind)
        value = row.get(field)
        if kind == 'gap' and type(value) is str and re.fullmatch(r'\d+( \d+){3}', value):
            value = [int(x) for x in value.split()]

        if not valid_value(key, value):
            raise ValueError('Unsupported stored compositor value; no mutation performed')
        result[key] = value
    return result


def lua_literal(value):
    if type(value) is bool:
        return str(value).lower()
    if type(value) is int:
        return str(value)
    if type(value) is list:
        return '{' + ','.join(k + '=' + str(v) for k, v in zip(('top','right','bottom','left'), value)) + '}'
    # Lua supports escaped UTF-8 bytes and decimal escapes, not JSON \u escapes.
    return '"' + ''.join('\\%03d' % b for b in value.encode('utf-8')) + '"'


def write_value(key, value, expected):
    if key not in SCHEMA or not valid_value(key, value):
        raise ValueError('Rejected unsupported compositor mutation')
    guards = []
    for name, old in expected.items():
        guards.append('local v=hl.get_config(' + lua_literal(name) + ');')
        if type(old) is list:
            check = 'type(v)=="table" and ' + ' and '.join('v.' + k + '==' + str(v) for k, v in zip(('top','right','bottom','left'), old))
        else:
            check = 'v==' + lua_literal('' if old == '[[EMPTY]]' else old)
        guards.append('assert(' + check + ',"Preset conflict: external edit");')
    code = ''.join(guards) + 'hl.config({[' + lua_literal(key) + ']=' + lua_literal(value) + '});'
    if run_hypr('eval', code) != 'ok':
        raise ValueError('Compositor rejected setting or detected an external edit')


def state_dir(instance):
    root = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    if not root.is_absolute():
        raise ValueError('XDG_STATE_HOME must be absolute')
    root = root / ('omarchy-' + SLUG)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise ValueError('Unsafe preset state directory')
    directory = root / hashlib.sha256(instance.encode()).hexdigest()[:24]
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise ValueError('Unsafe session state directory')
    return directory


@contextlib.contextmanager
def locked(directory):
    fd = os.open(directory / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BusyError('Another preset action is in progress; retry') from None
        yield
    finally:
        os.close(fd)


def save(directory, record):
    fd, temporary = tempfile.mkstemp(prefix='.transaction-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'transaction.json')
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_state(directory, instance):
    path = directory / 'transaction.json'
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError('Unsafe snapshot symlink')
    record = bounded_json(path)
    if type(record) is not dict or record.get('instance') != instance:
        raise ValueError('Invalid session snapshot')
    if type(record.get('id')) is not str or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', record['id']):
        raise ValueError('Invalid snapshot preset ID')
    if record.get('phase') not in ('pending', 'active'):
        raise ValueError('Invalid snapshot phase')
    for field in ('before', 'expected', 'previous'):
        values = record.get(field)
        if type(values) is not dict or set(values) != set(SCHEMA) or any(not valid_value(k, v) for k, v in values.items()):
            raise ValueError('Invalid snapshot values')
    if 'token' in record:
        import math
        if (not re.fullmatch('[a-f0-9]{32}', str(record['token']))
                or type(record.get('deadline')) not in (int, float)
                or not math.isfinite(record['deadline'])
                or not 0 <= record['deadline'] <= time.monotonic() + 30):
            raise ValueError('Invalid watchdog snapshot')
    return record


def apply_transaction(directory, instance, row_id, current, target, old_record, restoring):
    record = {'instance': instance, 'id': row_id, 'phase': 'pending',
              'before': old_record['before'] if old_record else dict(current),
              'previous': dict(current), 'expected': dict(target)}
    if old_record and old_record.get('token'):
        record.update({k: old_record[k] for k in ('token', 'deadline', 'watchdog_pid') if k in old_record})
    save(directory, record)
    try:
        if not restoring and target['decoration.screen_shader']:
            start_watchdog(directory, record)
        for key, value in target.items():
            if current[key] != value:
                write_value(key, value, current)
                current[key] = value
        if read_values() != target:
            raise ValueError('Compositor readback did not confirm settings')
        if restoring:
            (directory / 'transaction.json').unlink()
        else:
            record['phase'] = 'active'
            record['previous'] = dict(target)
            if not target['decoration.screen_shader']:
                record = {k: v for k, v in record.items() if k not in ('token', 'deadline', 'watchdog_pid')}
            save(directory, record)
    except (ValueError, OSError, subprocess.SubprocessError) as failure:
        try:
            actual = read_values()
            previous = record['previous'] if record['phase'] == 'pending' else (old_record['expected'] if old_record else record['before'])
            # Restore only values this transaction could have written, never a divergent external value.
            for key in reversed(list(target)):
                if actual[key] != previous[key]:
                    if actual[key] != target[key]:
                        raise ValueError('External edit conflicts with rollback')
                    write_value(key, previous[key], actual)
                    actual[key] = previous[key]
            if read_values() != previous:
                raise ValueError('Rollback readback failed')
            if old_record:
                if old_record.get('token') and not restoring:
                    start_watchdog(directory, old_record, preserve_deadline=True)
                save(directory, old_record)
            else:
                (directory / 'transaction.json').unlink()
        except (ValueError, OSError, subprocess.SubprocessError):
            raise ValueError('Preset failed; rollback could not complete. Snapshot retained; resolve external edits and use Restore.') from None
        raise ValueError('Preset failed; rollback confirmed previous compositor values.') from failure


def action(row_id, verb):
    rows = {r['id']: r for r in load_rows()}
    if row_id not in rows or verb not in ('apply', 'restore', 'confirm'):
        raise ValueError('Unknown preset ID or action; refresh catalogue')
    instance = session()
    directory = state_dir(instance)
    with locked(directory):
        current = read_values()
        record = load_state(directory, instance)
        if record:
            if record['phase'] == 'pending':
                if verb != 'restore':
                    raise ValueError('Interrupted action; use Restore before applying another preset')
                acceptable = all(current[k] in (record['previous'][k], record['expected'][k]) for k in SCHEMA)
            else:
                acceptable = current == record['expected']
            if not acceptable:
                raise ValueError('External edit conflicts with snapshot; refusing to overwrite it')
        if verb == 'confirm':
            if (not record or record['id'] != row_id or not record.get('token')
                    or record['deadline'] <= time.monotonic()):
                raise ValueError('No matching unexpired shader trial; select the active effect and Apply again')
            kept = {k: v for k, v in record.items() if k not in ('token', 'deadline', 'watchdog_pid')}
            try:
                save(directory, kept)
                if load_state(directory, instance) != kept:
                    raise ValueError('Keep snapshot readback failed')
            except (ValueError, OSError):
                try:
                    start_watchdog(directory, record, preserve_deadline=True)
                except (ValueError, OSError):
                    apply_transaction(directory, instance, row_id, current, record['before'], record, True)
                raise ValueError('Keep failed; timed restore rearmed or original values restored') from None
            return {'ok': True, 'message': 'Effect kept for this compositor session; original Restore snapshot retained.'}
        if verb == 'restore':
            if not record:
                raise ValueError('No snapshot for this session')
            target = record['before']
        else:
            target = dict(current)
            for key, value in rows[row_id]['settings'].items():
                if type(value) is str and value.startswith('@'):
                    value = shader_path(value)
                target[key] = value
        apply_transaction(directory, instance, row_id, current, target, record, verb == 'restore')
        return {'ok': True, 'message': 'Previous compositor values restored.' if verb == 'restore'
                else 'Runtime preset applied and read back; Restore is available.'}

TRIAL_SECONDS = 15


class BusyError(ValueError):
    pass


def shader_path(marker):
    path = DATA / 'shaders' / marker[1:]
    if marker not in ('@grayscale.frag', '@warm.frag') or path.is_symlink() or not path.is_file():
        raise ValueError('Bundled shader is missing or unsafe')
    with path.open('rb') as stream:
        contents = stream.read(16385)
    if len(contents) > 16384:
        raise ValueError('Bundled shader exceeds 16 KiB')
    return str(path.resolve())


def start_watchdog(directory, record, preserve_deadline=False):
    import secrets
    import threading
    token = secrets.token_hex(16)
    trial_deadline = record['deadline'] if preserve_deadline else time.monotonic() + TRIAL_SECONDS
    ready = directory / ('.ready-' + token)
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR',
           'HYPRLAND_INSTANCE_SIGNATURE', 'LANG') if k in os.environ}
    process = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).resolve()), 'watchdog', '--token', token],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True, env=env)
    threading.Thread(target=process.wait, daemon=True).start()
    deadline = time.monotonic() + 2
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError('Independent shader watchdog failed to start; effect refused')
            if ready.exists():
                if ready.is_symlink() or ready.read_text() != str(process.pid):
                    raise ValueError('Shader watchdog readiness mismatch')
                # Publish authority only after the independent successor is ready.
                replacement = dict(record, token=token, deadline=trial_deadline, watchdog_pid=process.pid)
                save(directory, replacement)
                record.update(replacement)
                return
            time.sleep(0.01)
        raise ValueError('Shader watchdog readiness timed out; effect refused')
    finally:
        with contextlib.suppress(FileNotFoundError):
            ready.unlink()


def watchdog(token):
    if SLUG != 'shader-deck' or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Invalid watchdog token')
    instance = session()
    directory = state_dir(instance)
    record = load_state(directory, instance)
    if not record:
        return {'ok': True, 'message': 'Expired watchdog; no changes.'}
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    ready = directory / ('.ready-' + token)
    fd = os.open(ready, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(str(os.getpid()))
    wait_limit = time.monotonic() + 30
    failures = 0
    while time.monotonic() < wait_limit:
        try:
            with locked(directory):
                record = load_state(directory, instance)
                if not record or record.get('token') != token:
                    return {'ok': True, 'message': 'Superseded watchdog; no changes.'}
                if record['deadline'] > time.monotonic():
                    wait_limit = record['deadline'] + 30
                    raise BusyError('Shader trial has not expired')
                current = read_values()
                acceptable = current == record['expected'] or (record['phase'] == 'pending' and all(
                    current[k] in (record['previous'][k], record['expected'][k]) for k in SCHEMA))
                if not acceptable:
                    raise ValueError('External edit prevents timed restore; snapshot retained')
                apply_transaction(directory, instance, record['id'], current, record['before'], record, True)
                return {'ok': True, 'message': 'Timed shader restore confirmed.'}
        except BusyError:
            time.sleep(0.1)
        except (ValueError, OSError, subprocess.SubprocessError):
            failures += 1
            if failures == 4:
                raise ValueError('Timed restore could not complete; use explicit Restore after checking IPC and external edits') from None
            time.sleep(0.2)
    raise ValueError('Timed restore lock remained busy; snapshot retained for explicit Restore')


if __name__ == '__main__':
    sys.exit(main())
