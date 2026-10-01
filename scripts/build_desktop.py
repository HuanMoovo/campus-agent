"""Build the Windows desktop installer, including the bundled Python backend."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def run(command, directory=ROOT, env=None):
    print('> ' + subprocess.list2cmdline([str(part) for part in command]), flush=True)
    subprocess.run([str(part) for part in command], cwd=directory, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-install', action='store_true', help='Use dependencies already installed locally')
    parser.add_argument('--full-rag', action='store_true', help='Bundle the optional vector libraries (large download and build)')
    parser.add_argument('--directory', action='store_true', help='Build win-unpacked without the NSIS installer')
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise RuntimeError('Build this package on 64-bit Windows.')
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10+ is required.')
    npm = shutil.which('npm.cmd')
    node = shutil.which('node')
    if not npm or not node:
        raise RuntimeError('Node.js 22+ and npm must be installed.')
    if int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0]) < 22:
        raise RuntimeError('Node.js 22+ is required.')
    backend, frontend, desktop = ROOT/'backend', ROOT/'frontend', ROOT/'desktop'
    python = backend/'.venv'/'Scripts'/'python.exe'
    if not python.exists():
        if args.skip_install:
            raise RuntimeError('Backend virtual environment is missing.')
        venv.create(backend/'.venv', with_pip=True)
    if not args.skip_install:
        run([python, '-m', 'pip', 'install', '-r', 'requirements-desktop.txt', '--no-cache-dir', '--disable-pip-version-check'], backend)
        if args.full_rag:
            run([python, '-m', 'pip', 'install', '-r', 'requirements-ai.txt', '--no-cache-dir', '--disable-pip-version-check'], backend)
        for directory in (frontend, desktop):
            run([npm, 'ci' if (directory/'package-lock.json').exists() else 'install', '--cache', '.npm-cache'], directory)
    run([python, '-c', 'import PyInstaller; from langgraph.graph import StateGraph; print("Packaging dependencies verified")'], backend)
    run([python, '-m', 'pytest', '-q'], backend)
    run([sys.executable, ROOT/'scripts'/'create_icon.py'])
    run([npm, 'test'], frontend)
    run([npm, 'run', 'build'], frontend)
    run([npm, 'test'], desktop)
    run([node, '--test', 'tests/backend.integration.cjs'], desktop)
    env = {**os.environ, 'CAMPUS_BUNDLE_RAG': '1' if args.full_rag else '0'}
    run([python, '-m', 'PyInstaller', '--noconfirm', '--distpath', ROOT/'build'/'backend',
         '--workpath', ROOT/'build'/'pyinstaller', desktop/'backend.spec'], ROOT, env)
    # Verify the actual frozen backend before producing the installer.
    run([node, '--test', 'tests/backend.integration.cjs'], desktop, {**os.environ, 'CAMPUS_TEST_PACKAGED': '1'})
    run([npm, 'run', 'pack' if args.directory else 'dist'], desktop)
    print(f'Build completed. Output: {ROOT / "release"}')
    print('The installed program includes Python and launches its local backend automatically.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Desktop build stopped: {error}', file=sys.stderr)
        sys.exit(1)
