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
import shlex
import signal
import stat
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


def desktop_exec_path(content):
    section = None
    values = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line
        elif section == '[Desktop Entry]' and '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            if key in {'Type', 'Exec'}:
                if key in values:
                    raise ValueError('Duplicate desktop entry key')
                values[key] = value
    if values.get('Type') != 'Application':
        raise ValueError('Desktop entry is not an Application')
    words = shlex.split(values.get('Exec', ''), posix=True)
    if not words or not words[0].startswith('/opt/') or any(c in words[0] for c in ';|&`$<>\n\r'):
        raise ValueError('Desktop Exec must name one absolute /opt application executable')
    if any(word not in {'%U', '%u', '%F', '%f'} for word in words[1:]):
        raise ValueError('Unexpected desktop Exec arguments; no shell or arbitrary fallback')
    return words[0]


def installed_deb_executable(package, evidence=None):
    name = command(['dpkg-deb', '-f', package, 'Package']).stdout.strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', name):
        raise RuntimeError('Invalid actual deb package name')
    files = command(['dpkg-query', '-L', name]).stdout.splitlines()
    owned = {Path(value) for value in files if value.startswith('/')}
    desktops = sorted(path for path in owned if path.suffix == '.desktop')
    if evidence is not None:
        evidence.update(package=name, owned_file_count=len(owned), desktop_entries=[], candidates=[])
    candidates = []
    if not desktops or len(desktops) > 8:
        raise RuntimeError('Expected a bounded set of actual package-owned desktop entries')
    for desktop in desktops:
        row = {'desktop': str(desktop)}
        try:
            if not str(desktop).startswith(('/usr/share/applications/', '/opt/')) or desktop.resolve(strict=True) not in owned:
                raise ValueError('Desktop entry/resolved path is not an owned application file')
            if not desktop.is_file() or desktop.stat().st_size > 16384:
                raise ValueError('Desktop entry unavailable or exceeds 16 KiB')
            content = desktop.read_text(encoding='utf-8')
            row['exec_lines'] = [line[:1024] for line in content.splitlines() if line.startswith('Exec=')][:4]
            path = Path(desktop_exec_path(content))
            row['exec_executable'] = str(path)
            resolved = path.resolve(strict=True)
            row['resolved'] = str(resolved)
            if path not in owned or resolved not in owned or not resolved.is_relative_to('/opt'):
                raise ValueError('Desktop Exec executable/resolved path is not owned by this /opt package')
            if not resolved.is_file() or not os.access(resolved, os.X_OK):
                raise ValueError('Desktop Exec executable is not an executable file')
            with resolved.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    raise ValueError('Desktop Exec executable is not ELF')
            archive = resolved.parent / 'resources/app.asar'
            if archive not in owned or not archive.is_file() or archive.resolve(strict=True) not in owned:
                raise ValueError('Desktop Exec executable has no adjacent package-owned resources/app.asar')
            row['validated'] = True
            candidates.append(resolved)
        except (OSError, ValueError) as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
        if evidence is not None:
            evidence['desktop_entries'].append(row)
    candidates = sorted(set(candidates))
    if evidence is not None:
        evidence['candidates'] = [str(path) for path in candidates]
    if len(candidates) != 1:
        raise RuntimeError('Cannot identify exactly one validated package-owned desktop Exec executable')
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


def mac_outer_profile(actual_home):
    profile = '(version 1)\n(allow default)\n'
    profile += '(deny file-read* (subpath ' + json.dumps(str(actual_home)) + '))\n'
    profile += '(deny file-write* (subpath ' + json.dumps(str(actual_home)) + '))\n'
    return profile


def child_log_path(location, state, out):
    return (state if location == 'state' else out) / 'app-output.log'


def validate_mac_launch_mode(mode, diagnostic_only, child_log_location, platform, arguments, acceptance_run=False):
    if mode not in {'strict', 'standard-vm'}:
        raise ValueError('Unknown macOS launch mode')
    if mode == 'standard-vm' and (not (diagnostic_only or acceptance_run) or child_log_location != 'state'
                                  or platform != 'darwin' or arguments):
        raise ValueError('standard-vm requires macOS, explicit diagnostic-only or acceptance-run, private-state output, and no application arguments')


def validate_acceptance_run(acceptance_run, diagnostic_only, mac_mode, child_log_location, platform, arguments, package_kind):
    if not acceptance_run:
        return
    if diagnostic_only or child_log_location != 'state':
        raise ValueError('acceptance-run excludes diagnostic-only and requires private-state child output')
    if platform == 'darwin':
        if mac_mode != 'standard-vm' or package_kind != 'mac-dmg' or arguments:
            raise ValueError('Mac acceptance-run requires standard-vm DMG and no application arguments')
    elif platform == 'linux':
        expected = {'appimage': ['--appimage-extract-and-run', '--no-sandbox'], 'deb': ['--no-sandbox']}
        if mac_mode != 'strict' or arguments != expected.get(package_kind):
            raise ValueError('Linux acceptance-run requires the exact existing disposable-runner package arguments')
    else:
        raise ValueError('acceptance-run requires actual macOS or Linux')


MAC_APP_HOME_RELATIVES = (
    'Library/Application Support/CampusAgent', 'Library/Caches/CampusAgent',
    'Library/Logs/CampusAgent', 'Library/Application Support/Mens',
    'Library/Caches/Mens', 'Library/Logs/Mens',
    'Library/Preferences/edu.campus.agent.desktop.plist',
    'Library/Saved Application State/edu.campus.agent.desktop.savedState')
MAC_OS_PREFERENCES = 'Library/Preferences/edu.campus.agent.desktop.plist'


def mac_app_home_audit(home):
    # Metadata only. Never enumerate or read existing real-HOME application data.
    rows = []
    for relative in MAC_APP_HOME_RELATIVES:
        path = home / relative
        row = {'relative': relative, 'exists': False}
        try:
            info = path.lstat()
            row.update(exists=True, directory=stat.S_ISDIR(info.st_mode),
                       symlink=stat.S_ISLNK(info.st_mode), bytes=info.st_size,
                       modified_ns=info.st_mtime_ns, regular_file=stat.S_ISREG(info.st_mode),
                       uid=info.st_uid)
        except FileNotFoundError:
            pass
        rows.append(row)
    return rows


def require_fresh_standard_home(audit):
    if (len(audit) != len(MAC_APP_HOME_RELATIVES)
            or {row['relative'] for row in audit} != set(MAC_APP_HOME_RELATIVES)
            or any(row['exists'] for row in audit)):
        raise RuntimeError('standard-vm refuses launch unless all eight actual-HOME app-owned paths are absent')


def standard_home_after(before, after, own_uid):
    require_fresh_standard_home(before)
    result = {'passed': False, 'allowed_os_preferences_addition': None,
              'audit_scope': 'Metadata only; no real-HOME app-data or preferences contents read'}
    if len(after) != 8 or {row['relative'] for row in after} != set(MAC_APP_HOME_RELATIVES):
        result['error'] = 'Incomplete actual-HOME after audit'
        return result
    for row in after:
        if not row['exists']:
            continue
        if (row['relative'] == MAC_OS_PREFERENCES and row.get('regular_file') is True
                and row.get('directory') is False and row.get('symlink') is False
                and row.get('uid') == own_uid and 0 <= row.get('bytes', -1) <= 65536):
            result['allowed_os_preferences_addition'] = dict(row)
        else:
            result['error'] = 'Unexpected actual-HOME app-owned path creation or unsafe preferences metadata: ' + row['relative']
            return result
    result['passed'] = True
    return result


def fake_home_inventory(home, limit=300):
    # The newly created fake HOME belongs entirely to this launch; no file contents.
    rows = []
    for root, directories, files in os.walk(home, followlinks=False):
        for name in sorted(directories + files):
            path = Path(root) / name
            info = path.lstat()
            rows.append({'relative': str(path.relative_to(home)), 'bytes': info.st_size,
                         'directory': stat.S_ISDIR(info.st_mode), 'symlink': stat.S_ISLNK(info.st_mode)})
            if len(rows) >= limit:
                return {'entries': rows, 'truncated': True, 'limit': limit}
    return {'entries': rows, 'truncated': False, 'limit': limit}


def owned_crash_pid(header, own_pids, app_bundle):
    modern_pid = re.search(r'"pid"\s*:\s*(\d+)', header)
    modern_path = re.search(r'"procPath"\s*:\s*("(?:[^"\\]|\\.)*")', header)
    legacy_pid = re.search(r'^Process:\s+[^\n]+\[(\d+)\]', header, re.MULTILINE)
    legacy_path = re.search(r'^Path:\s+(.+)$', header, re.MULTILINE)
    pid = int(modern_pid[1]) if modern_pid else int(legacy_pid[1]) if legacy_pid else None
    path = json.loads(modern_path[1]) if modern_path else legacy_path[1].strip() if legacy_path else ''
    if pid in own_pids and path.startswith(str(app_bundle) + '/'):
        return pid
    return None


def collect_mac_diagnostics(out, state, actual_home, executable, own_pids, launched_at):
    """Bounded own-app evidence only; no broad process logs or user configuration."""
    evidence = {'owned_pids': sorted(own_pids), 'crash_reports': [], 'errors': [],
                'crash_report_limit': 4, 'crash_report_byte_limit': 131072,
                'system_log_byte_limit': 262144, 'crash_header_byte_limit': 16384}
    bundle = next(parent for parent in executable.parents if parent.suffix == '.app')
    # On this disposable VM only our installed Mens app is launched. Candidate
    # metadata/header must additionally match a PID observed in our process group
    # and this exact copied bundle before any report body is retained.
    roots = (state / 'home/Library/Logs/DiagnosticReports',
             actual_home / 'Library/Logs/DiagnosticReports', Path('/Library/Logs/DiagnosticReports'))
    for root in roots:
        for pattern in ('Mens*.ips', 'Mens*.crash', 'campus-backend*.ips', 'campus-backend*.crash'):
            try:
                candidates = sorted(root.glob(pattern))
            except OSError as error:
                evidence['errors'].append(type(error).__name__ + ': crash directory unavailable')
                continue
            for path in candidates[:12]:
                if len(evidence['crash_reports']) >= evidence['crash_report_limit']:
                    break
                try:
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_mtime < launched_at:
                        continue
                    with path.open('rb') as stream:
                        header = stream.read(evidence['crash_header_byte_limit']).decode('utf-8', 'replace')
                        pid = owned_crash_pid(header, own_pids, bundle)
                        if pid is None:
                            continue
                        stream.seek(0)
                        content = stream.read(evidence['crash_report_byte_limit'])
                    name = 'own-crash-' + str(len(evidence['crash_reports']) + 1) + path.suffix
                    (out / name).write_bytes(content)
                    evidence['crash_reports'].append({'file': name, 'pid': pid, 'bytes': len(content),
                                                     'truncated': info.st_size > len(content)})
                except (OSError, ValueError) as error:
                    evidence['errors'].append(type(error).__name__ + ': own crash report unavailable')
    # Predicate is restricted before collection, and the time/bytes are bounded.
    # PID reuse is further bounded to this invocation's <=90 second launch window.
    predicate = 'processIdentifier IN {' + ','.join(map(str, sorted(own_pids))) + '}'
    log_args = ['/usr/bin/log', 'show', '--style', 'json', '--start',
                datetime.fromtimestamp(launched_at).strftime('%Y-%m-%d %H:%M:%S'),
                '--predicate', predicate]
    evidence['system_log_predicate'] = predicate
    try:
        result = command(log_args, timeout=15, check=False)
        content = result.stdout.encode('utf-8')[:evidence['system_log_byte_limit']]
        (out / 'own-system-log.json').write_bytes(content)
        evidence['system_log_returncode'] = result.returncode
        evidence['system_log_stderr'] = result.stderr[:2000]
        evidence['system_log_truncated'] = len(result.stdout.encode('utf-8')) > len(content)
    except (OSError, subprocess.TimeoutExpired) as error:
        evidence['errors'].append(type(error).__name__ + ': own PID-filtered system log unavailable')
    (out / 'mac-diagnostics.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--executable', type=Path)
    target.add_argument('--installed-deb', type=Path)
    parser.add_argument('--argument', action='append', default=[])
    parser.add_argument('--package-kind', choices=['mac-dmg', 'appimage', 'deb'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=90)
    parser.add_argument('--child-log-location', choices=['workspace', 'state'], default='workspace')
    parser.add_argument('--mac-launch-mode', choices=['strict', 'standard-vm'], default='strict')
    run_mode = parser.add_mutually_exclusive_group()
    run_mode.add_argument('--diagnostic-only', action='store_true')
    run_mode.add_argument('--acceptance-run', action='store_true')
    args = parser.parse_args()
    if args.child_log_location != 'workspace' and not (args.diagnostic_only or args.acceptance_run):
        parser.error('--child-log-location state requires explicit diagnostic-only or acceptance-run')
    try:
        validate_acceptance_run(args.acceptance_run, args.diagnostic_only, args.mac_launch_mode,
                                args.child_log_location, sys.platform, args.argument, args.package_kind)
        validate_mac_launch_mode(args.mac_launch_mode, args.diagnostic_only, args.child_log_location,
                                 sys.platform, args.argument, acceptance_run=args.acceptance_run)
    except ValueError as error:
        parser.error(str(error))
    if sys.platform not in {'darwin', 'linux'}:
        parser.error('Native smoke requires actual macOS or Linux; no simulated fallback')
    if (sys.platform == 'darwin') != (args.package_kind == 'mac-dmg'):
        parser.error('Package kind must match the actual operating system')
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('Evidence output must be new or empty')
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out.resolve()
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
              'diagnostic_only': args.diagnostic_only, 'acceptance_run': args.acceptance_run, 'accepted': False,
              'diagnostic_probe_requirements_met': False,
              'mac_launch_mode': args.mac_launch_mode if sys.platform == 'darwin' else None,
              'mac_outer_sandbox': ('deny-home' if args.mac_launch_mode == 'strict' else 'none-standard-vm-diagnostic') if sys.platform == 'darwin' else None,
              'product_sandbox_overrides_supplied': False if args.mac_launch_mode == 'standard-vm' else None,
              'child_log_location': args.child_log_location,
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
        if args.installed_deb:
            report['installed_deb_resolution'] = {}
            executable = installed_deb_executable(args.installed_deb, report['installed_deb_resolution'])
        else:
            executable = args.executable.resolve()
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
            actual_home = None
            audit_before = None
            if sys.platform == 'darwin':
                import pwd
                actual_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
                if executable.is_relative_to(actual_home):
                    raise RuntimeError('Copy the packaged macOS app outside the actual runner home before launch')
                audit_before = mac_app_home_audit(actual_home)
                report['actual_home_app_paths_before'] = audit_before
                report['fake_home_before'] = fake_home_inventory(home)
                if args.mac_launch_mode == 'standard-vm':
                    require_fresh_standard_home(audit_before)
                    report['standard_vm_fresh_actual_home_verified'] = True
                profile_text = mac_outer_profile(actual_home) if args.mac_launch_mode == 'strict' else None
                report['outer_sandbox_profile'] = profile_text
                report['outer_sandbox_applied'] = profile_text is not None
                if profile_text is not None:
                    sandbox = shutil.which('sandbox-exec')
                    if not sandbox:
                        raise RuntimeError('macOS outer isolation sandbox is unavailable')
                    profile = state / 'isolation.sb'
                    profile.write_text(profile_text, encoding='utf-8')
                    (out / 'outer-sandbox.sb').write_text(profile_text, encoding='utf-8')
                    report['outer_sandbox_profile_sha256'] = hashlib.sha256(profile_text.encode()).hexdigest()
                    launch = [sandbox, '-f', str(profile), *launch]
                source = state / 'window_probe.swift'
                source.write_text(SWIFT, encoding='utf-8')
                mac_probe = state / 'window_probe'
                compile_result = command(['xcrun', 'swiftc', '-framework', 'CoreGraphics', source, '-o', mac_probe], timeout=90, check=False)
                (out / 'native-probe-compile.log').write_text(compile_result.stdout + compile_result.stderr, encoding='utf-8')
                report['native_probe_compile_returncode'] = compile_result.returncode
                if compile_result.returncode:
                    raise RuntimeError('Native Swift window probe compilation failed')
                app_data = home / 'Library/Application Support/CampusAgent'
                report['actual_runner_home_denied_by_sandbox'] = str(actual_home) if args.mac_launch_mode == 'strict' else None
            else:
                for key in ('DISPLAY', 'XAUTHORITY'):
                    if key in os.environ:
                        env[key] = os.environ[key]
                if not env.get('DISPLAY'):
                    raise RuntimeError('A real X11 display is required; use Xvfb on the disposable runner')
                app_data = config / 'CampusAgent'
            report['isolated_state_root'] = str(state)
            report['expected_app_data'] = str(app_data)
            if os.path.lexists(app_data):
                raise RuntimeError('Expected isolated application data must be absent before launch')
            report['fresh_isolated_state_verified'] = True
            report['launch_environment_keys'] = sorted(env)
            report['launch_home'] = env['HOME']
            report['launch_cffixed_user_home'] = env['CFFIXED_USER_HOME']
            report['working_directory'] = str(state)
            report['command'] = launch
            launched_at = time.time()
            child_log = child_log_path(args.child_log_location, state, out)
            report['child_log_target'] = str(child_log)
            with child_log.open('w', encoding='utf-8') as log:
                # Both controls inherit exactly the same stdin; only fd 1/2's
                # backing file moves from the denied workspace to allowed /tmp.
                stdin_info = os.fstat(0)
                log_info = os.fstat(log.fileno())
                report['launch_fd_targets'] = {'0': {'target': 'inherited unchanged', 'device': stdin_info.st_dev,
                                                    'inode': stdin_info.st_ino, 'mode': stdin_info.st_mode},
                                               '1': {'target': str(child_log), 'device': log_info.st_dev, 'inode': log_info.st_ino},
                                               '2': {'target': str(child_log), 'device': log_info.st_dev, 'inode': log_info.st_ino}}
                if sys.platform == 'darwin':
                    fd0 = command(['lsof', '-a', '-p', str(os.getpid()), '-d', '0', '-Ffn'], check=False)
                    report['inherited_stdin_target_lsof'] = fd0.stdout[:2000]
                process = subprocess.Popen(launch, cwd=state, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                report['process_group'] = process.pid
                own_pids = {process.pid}
                try:
                    deadline = time.monotonic() + args.timeout
                    window = None
                    ready = None
                    while time.monotonic() < deadline:
                        window, group = native_window(process.pid, mac_probe)
                        own_pids.update(row['pid'] for row in group)
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
                    report['diagnostic_probe_requirements_met'] = True
                finally:
                    # This is the application outcome BEFORE our cleanup signals.
                    returncode = process.poll()
                    report['application_returncode_before_cleanup'] = returncode
                    report['application_running_before_cleanup'] = returncode is None
                    report['application_signal_before_cleanup'] = -returncode if returncode is not None and returncode < 0 else None
                    if sys.platform == 'darwin':
                        try:
                            own_pids.update(row['pid'] for row in processes(process.pid))
                            if returncode is not None and returncode < 0:
                                time.sleep(2)  # Allow the VM's own crash reporter to finish this app's report.
                            report['mac_diagnostics'] = collect_mac_diagnostics(out, state, actual_home, executable, own_pids, launched_at)
                        except Exception as error:
                            report['diagnostic_collection_error'] = type(error).__name__ + ': ' + str(error)
                    # Collection can take time. Poll again immediately before the
                    # first cleanup signal so a spontaneous exit is not attributed
                    # to our TERM/KILL sequence.
                    returncode = process.poll()
                    report['application_returncode_before_cleanup'] = returncode
                    report['application_running_before_cleanup'] = returncode is None
                    report['application_signal_before_cleanup'] = -returncode if returncode is not None and returncode < 0 else None
                    try:
                        remaining = stop_own_group(process)
                        report['application_returncode_after_cleanup'] = process.poll()
                        report['remaining_own_processes'] = remaining
                        if sys.platform == 'darwin':
                            report['fake_home_after'] = fake_home_inventory(home)
                            audit_after = mac_app_home_audit(actual_home)
                            report['actual_home_app_paths_after'] = audit_after
                            report['actual_home_app_paths_unchanged'] = audit_after == audit_before
                            if args.mac_launch_mode == 'standard-vm':
                                report['standard_vm_actual_home_audit'] = standard_home_after(audit_before, audit_after, os.getuid())
                                if not report['standard_vm_actual_home_audit']['passed']:
                                    report['status'] = 'failed'
                                    report['real_home_side_effect_error'] = report['standard_vm_actual_home_audit']['error']
                            elif audit_after != audit_before:
                                report['status'] = 'failed'
                                report['real_home_side_effect_error'] = 'Actual-HOME app-owned path metadata changed; no real-HOME data was read or removed'
                        if remaining:
                            report['status'] = 'failed'
                            report['cleanup_error'] = 'Some launched process-group members remain'
                    finally:
                        log.flush()
                        if child_log != out / 'app-output.log':
                            # Preserve owned output after process cleanup and before
                            # TemporaryDirectory removes the private state.
                            shutil.copyfile(child_log, out / 'app-output.log')
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
    if args.acceptance_run and report.get('application_running_before_cleanup') is not True:
        report['status'] = 'failed'
        report.setdefault('error', 'Packaged application was not running immediately before acceptance cleanup')
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['exit_code'] = 0 if report['status'].startswith('passed-') else 1
    report['native_evidence_requirements_met'] = (report['exit_code'] == 0
        and all(report[key] for key in ('native_window_verified', 'isolated_database_verified',
                                       'owned_backend_auth_verified', 'screenshot_captured'))
        and report.get('remaining_own_processes') == []
        and (sys.platform != 'darwin' or args.mac_launch_mode != 'standard-vm'
             or report.get('standard_vm_actual_home_audit', {}).get('passed') is True))
    report['native_evidence_status'] = 'passed-manual-ui-review-pending' if report['native_evidence_requirements_met'] else 'failed'
    if args.diagnostic_only and report['exit_code'] == 0:
        report['status'] = 'diagnostic-launch-evidence-collected-manual-review-required'
    (out / 'native-result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return report['exit_code']


if __name__ == '__main__':
    sys.exit(main())
