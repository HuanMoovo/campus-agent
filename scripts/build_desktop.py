"""Build the Mens desktop package (Windows installer, macOS app, Linux packages).

The same script drives all three platforms: it runs the test suites, freezes the Python
backend with PyInstaller (per-platform, since PyInstaller cannot cross-compile) and lets
electron-builder produce the platform's packages. Run it on the target platform, or let
the GitHub Actions workflow do it on windows-latest / macos-* / ubuntu-latest.
"""
import argparse
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


def default_arch():
    return 'x64' if platform.machine().lower() in {'amd64', 'x86_64'} else 'arm64'


def venv_python(root: Path) -> Path:
    return root / '.venv' / (Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python'))


def validate_target(target_os: str, arch: str, current: bool):
    expected = TARGETS.get(sys.platform, (None, None))[0]
    if target_os not in DIST_TARGETS:
        raise RuntimeError('Unsupported target platform: ' + str(target_os))
    if current and expected and target_os != expected:
        raise RuntimeError(f'Build the {target_os} package on {target_os} — the Python backend '
                           'cannot be frozen for another operating system.')
    if arch not in {'x64', 'arm64'}:
        raise RuntimeError('Unsupported architecture: ' + str(arch))


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
    arch = args.arch or default_arch()
    validate_target(target_os, arch, current=args.target_os is None)
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
        venv.create(backend/'.venv', with_pip=True)
        python = venv_python(backend)
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
