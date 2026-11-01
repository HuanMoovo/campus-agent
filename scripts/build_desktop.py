"""Build the Mens desktop package (Windows installer, macOS app, Linux packages).

The same script drives all three platforms: it runs the test suites, freezes the Python
backend with PyInstaller (per-platform, since PyInstaller cannot cross-compile) and lets
electron-builder produce the platform's packages. Run it on the target platform, or let
the GitHub Actions workflow do it on windows-latest / macos-* / ubuntu-latest.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'win32': ('win', 'x64'),
    'darwin': ('mac', 'arm64'),
    'linux': ('linux', 'x64'),
}
# electron-builder target list per platform (used when producing installers).
DIST_TARGETS = {'win': 'nsis', 'mac': 'dmg zip', 'linux': 'AppImage deb'}


def run(command, directory=ROOT, env=None):
    print('> ' + subprocess.list2cmdline([str(part) for part in command]), flush=True)
    subprocess.run([str(part) for part in command], cwd=directory, env=env, check=True)


def npm_command():
    return shutil.which('npm.cmd') or shutil.which('npm') or shutil.which('npm.exe')


def default_arch(machine=None):
    name = (platform.machine() if machine is None else machine).lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(name)
    if not arch:
        raise RuntimeError('Unsupported backend Python architecture; use a 64-bit x64 or arm64 interpreter.')
    return arch


def venv_python(root: Path) -> Path:
    return root / '.venv' / (Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python'))


def validate_target(target_os: str, arch=None):
    expected = TARGETS.get(sys.platform, (None, None))[0]
    if not expected:
        raise RuntimeError('Unsupported build platform; use Windows, macOS or Linux.')
    if target_os not in DIST_TARGETS:
        raise RuntimeError('Unsupported target platform: ' + str(target_os))
    if target_os != expected:
        raise RuntimeError(f'Build the {target_os} package on {target_os} — the Python backend '
                           'cannot be frozen for another operating system.')
    if arch is not None and arch not in {'x64', 'arm64'}:
        raise RuntimeError('Unsupported architecture: ' + str(arch))


def backend_target(python: Path, backend: Path):
    """Inspect an interpreter's build/runtime identity without importing app code."""
    probe = (
        'import json,platform,struct,sys,sysconfig; '
        'print(json.dumps({"sys_platform":sys.platform,"machine":platform.machine(),'
        '"sysconfig_platform":sysconfig.get_platform(),"pointer_bits":struct.calcsize("P")*8,'
        '"multiarch":getattr(sys.implementation,"_multiarch","") or "",'
        '"host_gnu_type":sysconfig.get_config_var("HOST_GNU_TYPE") or ""}))'
    )
    try:
        output = subprocess.check_output([str(python), '-I', '-c', probe], cwd=backend,
                                         text=True, stderr=subprocess.PIPE, timeout=10)
        runtime = json.loads(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        # Interpreter errors/output can contain local configuration; do not echo them.
        raise RuntimeError('Cannot determine backend Python platform and architecture.') from None
    fields = ('sys_platform', 'machine', 'sysconfig_platform', 'multiarch', 'host_gnu_type')
    if not isinstance(runtime, dict) or any(not isinstance(runtime.get(key), str) for key in fields):
        raise RuntimeError('Cannot determine backend Python platform and architecture.')
    target_os = TARGETS.get(runtime['sys_platform'], (None, None))[0]
    if not target_os:
        raise RuntimeError('Unsupported backend Python platform.')
    if type(runtime.get('pointer_bits')) is not int or runtime['pointer_bits'] != 64:
        raise RuntimeError('The backend Python interpreter must be 64-bit.')
    if target_os == 'win':
        # platform.machine() can describe the host CPU rather than an emulated Python.
        arch = {'win-amd64': 'x64', 'win-arm64': 'arm64'}.get(runtime['sysconfig_platform'].lower())
    elif target_os == 'mac':
        # A universal2 interpreter freezes its current process architecture by default.
        arch = default_arch(runtime['machine']) if runtime['sysconfig_platform'].startswith('macosx-') else None
    else:
        # Under emulation uname/get_platform can describe the kernel instead of Python.
        tags = [runtime[key].lower() for key in ('multiarch', 'host_gnu_type') if runtime[key]]
        arches = {default_arch(tag.split('-', 1)[0]) for tag in tags}
        arch = arches.pop() if len(arches) == 1 else None
    if not arch:
        raise RuntimeError('Unsupported backend Python architecture; use a 64-bit x64 or arm64 interpreter.')
    return target_os, arch


def validate_backend_target(python: Path, backend: Path, target_os: str, arch=None):
    backend_os, backend_arch = backend_target(python, backend)
    if backend_os != target_os:
        raise RuntimeError('The backend Python platform must match the target platform.')
    if arch is not None and arch != backend_arch:
        raise RuntimeError('The target architecture must match the backend Python architecture; '
                           'use a matching 64-bit interpreter and virtual environment.')
    return arch or backend_arch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-install', action='store_true', help='Use dependencies already installed locally')
    parser.add_argument('--full-rag', action='store_true', help='Bundle the optional vector libraries (large download and build)')
    parser.add_argument('--directory', action='store_true', help='Produce only the unpacked application directory')
    parser.add_argument('--os', dest='target_os', choices=sorted(DIST_TARGETS), default=None,
                        help='Target platform (defaults to the current one)')
    parser.add_argument('--arch', choices=['x64', 'arm64'], default=None,
                        help='Target architecture (defaults to the current one)')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10+ is required.')
    target_os = args.target_os or TARGETS.get(sys.platform, (None, None))[0]
    validate_target(target_os, args.arch)
    npm = npm_command()
    node = shutil.which('node')
    if not npm or not node:
        raise RuntimeError('Node.js 22+ and npm must be installed.')
    if int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0]) < 22:
        raise RuntimeError('Node.js 22+ is required.')
    backend, frontend, desktop = ROOT/'backend', ROOT/'frontend', ROOT/'desktop'
    python = venv_python(backend)
    if not python.exists():
        if args.skip_install:
            raise RuntimeError('Backend virtual environment is missing.')
        # venv.create(with_pip=True) runs ensurepip, so reject an incompatible creator first.
        validate_backend_target(Path(sys.executable), backend, target_os, args.arch)
        venv.create(backend/'.venv', with_pip=True)
        python = venv_python(backend)
    arch = validate_backend_target(python, backend, target_os, args.arch)
    if not args.skip_install:
        run([python, '-m', 'pip', 'install', '-r', 'requirements-desktop.txt', '--no-cache-dir', '--disable-pip-version-check'], backend)
        run([python, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-build.txt'), '--no-cache-dir', '--disable-pip-version-check'], backend)
        if args.full_rag:
            run([python, '-m', 'pip', 'install', '-r', 'requirements-ai.txt', '--no-cache-dir', '--disable-pip-version-check'], backend)
        for directory in (frontend, desktop):
            run([npm, 'ci' if (directory/'package-lock.json').exists() else 'install', '--cache', '.npm-cache'], directory)
    run([python, '-c', 'import PyInstaller; from langgraph.graph import StateGraph; print("Packaging dependencies verified")'], backend)
    run([python, '-m', 'pytest', '-q'], backend)
    run([python, ROOT/'scripts'/'create_icon.py'])
    run([npm, 'test'], frontend)
    run([npm, 'run', 'build'], frontend)
    run([npm, 'test'], desktop)
    run([node, '--test', 'tests/backend.integration.cjs'], desktop)
    env = {**os.environ, 'CAMPUS_BUNDLE_RAG': '1' if args.full_rag else '0'}
    run([python, '-m', 'PyInstaller', '--noconfirm', '--distpath', ROOT/'build'/'backend',
         '--workpath', ROOT/'build'/'pyinstaller', desktop/'backend.spec'], ROOT, env)
    # Verify the actual frozen backend before producing the packages.
    run([node, '--test', 'tests/backend.integration.cjs'], desktop, {**os.environ, 'CAMPUS_TEST_PACKAGED': '1'})
    # Electron 42+ no longer downloads its binary during npm install; electron-builder reads it from
    # node_modules/electron/dist (electronDist in desktop/package.json), so prepare it explicitly.
    run([npm, 'exec', '--', 'install-electron'], desktop)
    builder_env = {**os.environ}
    if target_os == 'mac':
        # Unsigned local/CI builds must not fail while looking for a signing identity.
        builder_env.setdefault('CSC_IDENTITY_AUTO_DISCOVERY', 'false')
    targets = [] if args.directory else DIST_TARGETS[target_os].split()
    # The release workflow attaches the artefacts itself, and electron-builder would otherwise
    # start publishing them on its own the moment a matching tag exists (it then aborts with
    # "GitHub Personal Access Token is not set"), so publishing stays explicitly off.
    run([npm, 'run', 'pack' if args.directory else 'dist', '--',
         f'--{target_os}', *targets, f'--{arch}', '--publish', 'never'], desktop, builder_env)
    print(f'Build completed. Output: {ROOT / "release"}')
    print('The installed program includes Python and launches its local backend automatically.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Desktop build stopped: {error}', file=sys.stderr)
        sys.exit(1)
