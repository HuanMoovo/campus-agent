"""Native packaged-window probe. No browser automation or debugging protocol.

Requires macOS WindowServer/CoreGraphics or Linux X11. Missing native evidence is
a failure. A pass covers launch/window/fresh local database only, not UI features,
Gatekeeper, signing, notarization, production file editing, or provider requests.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SWIFT = r'''
import Foundation
import CoreGraphics
let pids = Set(CommandLine.arguments.dropFirst().compactMap { Int($0) })
guard let entries = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
    fputs("CoreGraphics window inspection unavailable\n", stderr); exit(2)
}
let windows: [[String: Any]] = entries.compactMap { entry in
    guard let pid = entry[kCGWindowOwnerPID as String] as? Int, pids.contains(pid),
          let id = entry[kCGWindowNumber as String] as? Int,
          let layer = entry[kCGWindowLayer as String] as? Int, layer == 0,
          let bounds = entry[kCGWindowBounds as String] as? [String: Any],
          let width = bounds["Width"] as? Double, let height = bounds["Height"] as? Double,
          width > 100, height > 100 else { return nil }
    return ["pid": pid, "id": id, "layer": layer, "bounds": bounds,
            "owner": entry[kCGWindowOwnerName as String] as? String ?? "",
            "title": entry[kCGWindowName as String] as? String ?? ""]
}
let data = try JSONSerialization.data(withJSONObject: windows, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
'''


def parse_process_group(output, group_id):
    result = []
    for line in output.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) == 4 and all(part.isdigit() for part in fields[:3]):
            pid, parent, group = map(int, fields[:3])
            if group == group_id:
                result.append({'pid': pid, 'ppid': parent, 'pgid': group, 'command': fields[3]})
    return result


def parse_x11_window(window_id, properties, geometry, pids):
    owner = re.search(r'_NET_WM_PID\([^)]*\)\s*=\s*(\d+)', properties)
    width = re.search(r'Width:\s*(\d+)', geometry)
    height = re.search(r'Height:\s*(\d+)', geometry)
    if not owner or int(owner[1]) not in pids or 'Map State: IsViewable' not in geometry:
        return None
    if not width or not height or int(width[1]) <= 100 or int(height[1]) <= 100:
        return None
    if 'mens' not in properties.lower():
        return None
    return {'id': window_id, 'pid': int(owner[1]), 'width': int(width[1]),
            'height': int(height[1]), 'mapped': True, 'native_properties': properties}


def parse_loopback_listeners(output, pids):
    result = []
    pid = None
    for line in output.splitlines():
        if re.fullmatch(r'p\d+', line):
            pid = int(line[1:])
        elif pid in pids and re.fullmatch(r'n127\.0\.0\.1:\d+', line):
            result.append({'pid': pid, 'port': int(line.rsplit(':', 1)[1])})
    return result


def command(args, timeout=20, check=True):
    return subprocess.run([str(arg) for arg in args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=check)


def processes(group_id):
    return parse_process_group(command(['ps', '-axo', 'pid=,ppid=,pgid=,command=']).stdout, group_id)


def backend_readiness(group):
    pids = {row['pid'] for row in group if 'campus-backend' in row['command'] and '--desktop' in row['command']}
    if not pids:
        return None
    result = command(['lsof', '-nP', '-a', '-p', ','.join(map(str, sorted(pids))), '-iTCP', '-sTCP:LISTEN', '-Fpn'], check=False)
    for listener in parse_loopback_listeners(result.stdout, pids):
        connection = http.client.HTTPConnection('127.0.0.1', listener['port'], timeout=3)
        try:
            connection.request('GET', '/api/health')
            response = connection.getresponse()
            response.read(1024)
            if response.status == 401:
                return {**listener, 'address': '127.0.0.1', 'route': '/api/health',
                        'unauthenticated_status': 401, 'desktop_token_supplied': False,
                        'ownership_source': 'lsof socket owned by frozen-backend PID in launched process group'}
        except OSError:
            continue
        finally:
            connection.close()
    return None


def native_window(group_id, mac_probe=None):
    group = processes(group_id)
    pids = {row['pid'] for row in group}
    if not pids:
        return None, group
    if sys.platform == 'darwin':
        result = command([mac_probe, *sorted(pids)])
        windows = json.loads(result.stdout)
        selected = [row for row in windows if 'mens' in (row['owner'] + ' ' + row['title']).lower()]
        return (selected[0] if selected else None), group
    tree = command(['xwininfo', '-root', '-tree']).stdout
    for window_id in dict.fromkeys(re.findall(r'^\s*(0x[0-9a-fA-F]+)\b', tree, re.MULTILINE)):
        properties = command(['xprop', '-id', window_id, '_NET_WM_PID', '_NET_WM_NAME', 'WM_NAME', 'WM_CLASS'], check=False)
        geometry = command(['xwininfo', '-id', window_id], check=False)
        if properties.returncode or geometry.returncode:
            continue
        window = parse_x11_window(window_id, properties.stdout, geometry.stdout, pids)
        if window:
            return window, group
    return None, group


def installed_deb_executable(package):
    name = command(['dpkg-deb', '-f', package, 'Package']).stdout.strip()
    files = command(['dpkg-query', '-L', name]).stdout.splitlines()
    candidates = [Path(value) for value in files if value.startswith('/opt/')
                  and (Path(value).parent / 'resources/app.asar').is_file()
                  and Path(value).is_file() and os.access(value, os.X_OK)
                  and Path(value).name not in {'chrome-sandbox', 'chrome_crashpad_handler'}]
    candidates = [path for path in candidates if path.read_bytes()[:4] == b'\x7fELF']
    if len(candidates) != 1:
        raise RuntimeError('Cannot identify exactly one actual installed deb application executable')
    return candidates[0]


def stop_own_group(process):
    group_id = process.pid
    assert group_id != os.getpgrp(), 'Refusing to signal the caller process group'
    remaining = processes(group_id)
    for sig, duration in ((signal.SIGTERM, 8), (signal.SIGKILL, 3)):
        if not remaining:
            break
        try:
            os.killpg(group_id, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            process.poll()  # Reap the launched group leader where possible.
            remaining = processes(group_id)
            if not remaining:
                break
            time.sleep(.25)
    process.poll()
    return processes(group_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--executable', type=Path)
    target.add_argument('--installed-deb', type=Path)
    parser.add_argument('--argument', action='append', default=[])
    parser.add_argument('--package-kind', choices=['mac-dmg', 'appimage', 'deb'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=90)
    args = parser.parse_args()
    if sys.platform not in {'darwin', 'linux'}:
        parser.error('Native smoke requires actual macOS or Linux; no simulated fallback')
    if (sys.platform == 'darwin') != (args.package_kind == 'mac-dmg'):
        parser.error('Package kind must match the actual operating system')
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('Evidence output must be new or empty')
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out.resolve()
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
              'platform': sys.platform, 'package_kind': args.package_kind,
              'native_window_verified': False, 'isolated_database_verified': False, 'owned_backend_auth_verified': False,
              'screenshot_captured': False, 'browser_automation_used': False,
              'debugging_protocol_used': False, 'ui_feature_interactions_verified': False,
              'signing_notarization_gatekeeper_verified': False, 'fully_loaded_ui_verified': False,
              'screenshot_manual_content_review': 'pending',
              'manual_ui_review_pending': True, 'electron_sandbox_verified': False,
              'linux_no_sandbox_launch': '--no-sandbox' in args.argument,
              'cleanup_scope': 'Observed launched process-group members only; detached descendants are not verified or terminated',
              'cursor_included': False, 'only_own_process_group_signaled': True}
    process = None
    try:
        executable = installed_deb_executable(args.installed_deb) if args.installed_deb else args.executable.resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError('Actual packaged application executable is unavailable')
        report['executable'] = str(executable)
        report['executable_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='mens-native-', dir='/tmp') as temporary:
            state = Path(temporary).resolve()
            home, config, cache, tmp = [state / name for name in ('home', 'config', 'cache', 'tmp')]
            for path in (home, config, cache, tmp):
                path.mkdir()
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'en_US.UTF-8',
                   'HOME': str(home), 'CFFIXED_USER_HOME': str(home), 'TMPDIR': str(tmp),
                   'XDG_CONFIG_HOME': str(config), 'XDG_CACHE_HOME': str(cache), 'XDG_DATA_HOME': str(state / 'data'),
                   'CAMPUS_CONFIG_FILE': str(state / 'empty.env'), 'CAMPUS_DATA_DIR': str(state / 'data'),
                   'ADMIN_TOKEN': 'test-admin-token', 'ENABLE_RAG': 'false', 'QWEN_API_KEY': '', 'DEEPSEEK_API_KEY': '',
                   'LANGSMITH_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false', 'PYTHONNOUSERSITE': '1'}
            (state / 'empty.env').write_text('', encoding='utf-8')
            launch = [str(executable), *args.argument]
            mac_probe = None
            if sys.platform == 'darwin':
                import pwd
                actual_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
                if executable.is_relative_to(actual_home):
                    raise RuntimeError('Copy the packaged macOS app outside the actual runner home before launch')
                sandbox = shutil.which('sandbox-exec')
                if not sandbox:
                    raise RuntimeError('macOS home-isolation sandbox is unavailable')
                profile = state / 'isolation.sb'
                profile.write_text('(version 1)\n(allow default)\n(deny file-read* (subpath ' + json.dumps(str(actual_home)) + '))\n(deny file-write* (subpath ' + json.dumps(str(actual_home)) + '))\n', encoding='utf-8')
                launch = [sandbox, '-f', str(profile), *launch]
                source = state / 'window_probe.swift'
                source.write_text(SWIFT, encoding='utf-8')
                mac_probe = state / 'window_probe'
                compile_result = command(['xcrun', 'swiftc', '-framework', 'CoreGraphics', source, '-o', mac_probe], timeout=90)
                (out / 'native-probe-compile.log').write_text(compile_result.stdout + compile_result.stderr, encoding='utf-8')
                app_data = home / 'Library/Application Support/CampusAgent'
                report['actual_runner_home_denied_by_sandbox'] = str(actual_home)
            else:
                for key in ('DISPLAY', 'XAUTHORITY'):
                    if key in os.environ:
                        env[key] = os.environ[key]
                if not env.get('DISPLAY'):
                    raise RuntimeError('A real X11 display is required; use Xvfb on the disposable runner')
                app_data = config / 'CampusAgent'
            report['isolated_state_root'] = str(state)
            report['expected_app_data'] = str(app_data)
            report['command'] = launch
            with (out / 'app-output.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen(launch, cwd=state, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                report['process_group'] = process.pid
                try:
                    deadline = time.monotonic() + args.timeout
                    window = None
                    ready = None
                    while time.monotonic() < deadline:
                        window, group = native_window(process.pid, mac_probe)
                        ready = backend_readiness(group)
                        if window and ready and (app_data / 'campus.db').is_file():
                            break
                        if process.poll() is not None and not group:
                            raise RuntimeError('Packaged application exited before native window/database evidence')
                        time.sleep(1)
                    if not window:
                        raise RuntimeError('No visible native application window owned by the launched process group')
                    if not ready:
                        raise RuntimeError('No owned frozen backend with exact loopback listener and unauthenticated HTTP 401 health response')
                    database = app_data / 'campus.db'
                    if not database.is_file() or database.read_bytes()[:16] != b'SQLite format 3\x00':
                        raise RuntimeError('Backend did not create a real database in the isolated application data directory')
                    report['window'] = window
                    report['processes'] = group
                    report['native_window_verified'] = True
                    report['isolated_database_verified'] = True
                    report['owned_backend_auth_verified'] = True
                    report['backend'] = ready
                    report['database_bytes'] = database.stat().st_size
                    # Allow the actual renderer to paint after ready-to-show.
                    time.sleep(3)
                    screenshot = out / 'native-window.png'
                    if sys.platform == 'darwin':
                        command(['screencapture', '-x', '-l', str(window['id']), screenshot])
                    else:
                        command(['import', '-window', 'root', screenshot])
                    if not screenshot.is_file() or screenshot.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n' or screenshot.stat().st_size < 1000:
                        raise RuntimeError('Native cursor-free screenshot was not captured')
                    report['screenshot_captured'] = True
                    report['screenshot'] = screenshot.name
                    report['screenshot_sha256'] = hashlib.sha256(screenshot.read_bytes()).hexdigest()
                    final_window, final_group = native_window(process.pid, mac_probe)
                    if not final_window or not backend_readiness(final_group):
                        raise RuntimeError('Native application window/backend disappeared during capture')
                    report['status'] = 'passed-native-window-backend-and-isolated-db-manual-screenshot-review-required'
                finally:
                    remaining = stop_own_group(process)
                    report['remaining_own_processes'] = remaining
                    if remaining:
                        report['status'] = 'failed'
                        report['cleanup_error'] = 'Some launched process-group members remain'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['exit_code'] = 0 if report['status'].startswith('passed-') else 1
    (out / 'native-result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return report['exit_code']


if __name__ == '__main__':
    sys.exit(main())
