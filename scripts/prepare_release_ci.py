"""Verify final release signing status; CI generates checksums after this step."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


SUFFIXES = {'win': {'.exe'}, 'mac': {'.dmg', '.zip'}, 'linux': {'.appimage', '.deb'}}


def safe_entry(path: Path, root: Path):
    """Inspect a bundle node without following symlinks or Windows junctions."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise RuntimeError(f'Release verification refuses linked/reparse entry: {path.name}')
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError:
        raise RuntimeError(f'Release verification path escapes output directory: {path.name}') from None
    return info


def windows_executables(directory: Path) -> list[Path]:
    unpacked = directory / 'win-unpacked'
    if not unpacked.is_dir():
        raise RuntimeError('Windows verification requires win-unpacked')
    pending = [unpacked]
    executables = []
    while pending:
        path = pending.pop()
        info = safe_entry(path, directory)
        if stat.S_ISDIR(info.st_mode):
            pending.extend(path.iterdir())
        elif stat.S_ISREG(info.st_mode) and path.suffix.lower() == '.exe':
            executables.append(path)
        elif not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f'Release verification refuses special entry: {path.name}')
    required = {unpacked / 'Mens.exe', unpacked / 'resources/backend/campus-backend.exe'}
    if not required.issubset(executables):
        raise RuntimeError('Windows verification requires Mens.exe and resources/backend/campus-backend.exe')
    return sorted(executables)


def prepare_release(directory: Path, target_os: str, arch: str, env=None) -> dict:
    env = os.environ if env is None else env
    directory = directory.absolute()
    safe_entry(directory, directory)
    status_path = directory / f'SIGNING-STATUS-{target_os}-{arch}.json'
    # A failed rerun must never leave a previous signed-and-verified receipt.
    status_path.unlink(missing_ok=True)
    files = sorted(path for path in directory.iterdir()
                   if path.suffix.lower() in SUFFIXES[target_os])
    if not files:
        raise RuntimeError(f'No {target_os} release packages found')
    for path in files:
        if not stat.S_ISREG(safe_entry(path, directory).st_mode):
            raise RuntimeError(f'Release package is not a regular file: {path.name}')
    pfx_base64 = env.get('WINDOWS_SIGNING_PFX_BASE64', '')
    password = env.get('WINDOWS_SIGNING_PASSWORD', '')
    configured = bool(pfx_base64 or password)
    verified = []
    if configured:
        if target_os != 'win':
            raise RuntimeError('Windows signing credentials cannot sign this platform')
        if not pfx_base64:
            raise RuntimeError('Windows signing was configured without a PFX certificate')
        try:
            certificate = base64.b64decode(pfx_base64, validate=True)
        except (ValueError, binascii.Error):
            raise RuntimeError('Windows signing PFX is not valid base64') from None
        if not certificate:
            raise RuntimeError('Windows signing PFX is empty')
        # Format validation only. The builder already used this identity; never
        # load a key, write a PFX, or mutate a package in this final verification step.
        del certificate
        targets = windows_executables(directory) + files
        powershell = shutil.which('pwsh') or shutil.which('powershell')
        if not powershell:
            raise RuntimeError('PowerShell is required for configured Windows verification')
        for path in targets:
            try:
                subprocess.run([
                    powershell, '-NoProfile', '-NonInteractive', '-File',
                    str(Path(__file__).resolve().with_name('sign_release.ps1')),
                    '-File', str(path), '-VerifyOnly',
                ], check=True)
            except subprocess.CalledProcessError as error:
                # Do not interpolate command/env or signing credentials into errors.
                raise RuntimeError(f'Signature verification failed for {path.name} '
                                   f'(exit {error.returncode})') from None
            verified.append(path.relative_to(directory).as_posix())
    status = {
        'platform': target_os, 'arch': arch,
        'status': 'signed-and-verified' if configured else 'unsigned',
        'artifacts': [path.name for path in files],
        'verified_files': verified,
        'timestamp_required': configured,
        'reason': ('All unpacked Windows EXEs and final installers passed trusted '
                   'Authenticode and timestamp verification.' if configured else
                   'No signing credentials configured; this build is unsigned and was not signature-verified.'),
    }
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='.signing-status-', suffix='.json', delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(json.dumps(status, indent=2) + '\n')
        temporary_path.replace(status_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    print(f"SIGNING STATUS: {status['status'].upper()} ({target_os}/{arch})")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', type=Path, default=Path('release'))
    parser.add_argument('--os', dest='target_os', choices=sorted(SUFFIXES), required=True)
    parser.add_argument('--arch', choices=['x64', 'arm64'], required=True)
    args = parser.parse_args()
    try:
        prepare_release(args.dir.absolute(), args.target_os, args.arch, os.environ)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'Release preparation failed: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
