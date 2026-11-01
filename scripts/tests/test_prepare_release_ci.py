"""Final release verification regressions; OS trust/provider boundaries are offline stubs."""
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/prepare_release_ci.py'
spec = importlib.util.spec_from_file_location('prepare_release_ci', SCRIPT)
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)

class ReleasePreparationTests(unittest.TestCase):
    def test_checksums_cli_uses_utf8_with_legacy_captured_windows_pipes(self):
        payload = b'PUBLIC OWNED CHECKSUM FIXTURE\x00\xff'
        env = dict(os.environ, PYTHONIOENCODING='cp1252', PYTHONUTF8='0')
        for name in ('Mens-Setup-fixture.exe', 'Mens-\u5b89\u88c5\u5305.exe'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='mens-checksum-encoding-') as temporary:
                directory = Path(temporary)
                package = directory / name
                package.write_bytes(payload)
                manifest = directory / 'SHA256SUMS.txt'
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/release_checksums.py'),
                                         '--dir', str(directory), '--out', str(manifest)],
                                        env=env, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                self.assertEqual(result.stderr, b'')
                output = result.stdout.decode('utf-8')
                self.assertIn(name, output)
                self.assertIn('\u6e05\u5355\u5df2\u5199\u5165', output)
                expected = hashlib.sha256(payload).hexdigest() + '  ' + name + os.linesep
                self.assertEqual(manifest.read_bytes(), expected.encode('utf-8'))
                self.assertEqual(package.read_bytes(), payload)
                missing = directory / '\u4e0d\u5b58\u5728\u7684\u4ea7\u7269'
                rejected = subprocess.run([sys.executable, str(ROOT / 'scripts/release_checksums.py'),
                                           '--dir', str(missing)], env=env, capture_output=True, timeout=20)
                self.assertEqual(rejected.returncode, 1)
                self.assertIn('\u76ee\u5f55\u4e0d\u5b58\u5728\uff1a' + str(missing), rejected.stderr.decode('utf-8'))

    def signing_env(self):
        return {'WINDOWS_SIGNING_PFX_BASE64': base64.b64encode(b'PUBLIC_NOT_A_PFX').decode(),
                'WINDOWS_SIGNING_PASSWORD': 'PUBLIC_FIXTURE_PASSWORD'}

    def packages(self, directory):
        names = ['win-unpacked/Mens.exe', 'win-unpacked/resources/backend/campus-backend.exe',
                 'win-unpacked/resources/elevate.exe', 'win-unpacked/resources/extra/worker.EXE',
                 'Mens-Setup-test-x64.exe']
        for name in names:
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('PUBLIC UNSIGNED OS-VERIFIER FIXTURE ' + name).encode())
        return names

    def test_configured_build_verifies_internal_before_outer_without_loading_pfx_or_mutation(self):
        with tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
            release = Path(temporary)
            names = self.packages(release)
            before = {name: (release / name).read_bytes() for name in names}
            verified = []
            def os_verifier(command, **kwargs):
                self.assertEqual(command[:4], ['stub-powershell', '-NoProfile', '-NonInteractive', '-File'])
                self.assertEqual(Path(command[4]), ROOT / 'scripts/sign_release.ps1')
                self.assertEqual(command[-1], '-VerifyOnly')
                self.assertNotIn('-Pfx', command)
                self.assertNotIn('-Password', command)
                verified.append(Path(command[6]).relative_to(release).as_posix())
                self.assertTrue(kwargs['check'])
                self.assertFalse((release / 'SIGNING-STATUS-win-x64.json').exists())
                return subprocess.CompletedProcess(command, 0)
            with mock.patch('shutil.which', return_value='stub-powershell'), \
                    mock.patch('subprocess.run', side_effect=os_verifier), \
                    mock.patch('tempfile.TemporaryDirectory', side_effect=AssertionError('Do not materialize a PFX')):
                status = preparation.prepare_release(release, 'win', 'x64', self.signing_env())
            self.assertEqual(verified, names)
            self.assertEqual(status['status'], 'signed-and-verified')
            self.assertEqual(status['verified_files'], names)
            self.assertTrue(status['timestamp_required'])
            self.assertEqual(before, {name: (release / name).read_bytes() for name in names})
            self.assertFalse(list(release.rglob('*.pfx')))
            subprocess.run([sys.executable, str(ROOT / 'scripts/release_checksums.py'), '--dir', str(release),
                            '--out', str(release / 'SHA256SUMS.txt')], check=True, capture_output=True)
            self.assertEqual((release / 'SHA256SUMS.txt').read_text(),
                             hashlib.sha256(before[names[-1]]).hexdigest() + '  ' + names[-1] + '\n')

    def test_internal_or_outer_failure_clears_old_success_and_never_leaks_credentials(self):
        for failure in ('campus-backend.exe', 'elevate.exe', 'Mens-Setup-test-x64.exe'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
                release = Path(temporary)
                self.packages(release)
                status_path = release / 'SIGNING-STATUS-win-x64.json'
                status_path.write_text('{"status":"signed-and-verified"}')
                targets = []
                def reject(command, **kwargs):
                    target = Path(command[6])
                    targets.append(target.name)
                    if target.name == failure:
                        raise subprocess.CalledProcessError(23, command)
                    return subprocess.CompletedProcess(command, 0)
                with mock.patch('shutil.which', return_value='stub-powershell'), \
                        mock.patch('subprocess.run', side_effect=reject):
                    with self.assertRaises(RuntimeError) as error:
                        preparation.prepare_release(release, 'win', 'x64', self.signing_env())
                self.assertIn('23', str(error.exception))
                self.assertNotIn('PUBLIC_FIXTURE_PASSWORD', str(error.exception))
                self.assertNotIn(self.signing_env()['WINDOWS_SIGNING_PFX_BASE64'], str(error.exception))
                self.assertFalse(status_path.exists())
                if failure != 'Mens-Setup-test-x64.exe':
                    self.assertNotIn('Mens-Setup-test-x64.exe', targets)

    def test_missing_required_exe_fails_before_any_verification(self):
        for missing in ('win-unpacked', 'win-unpacked/Mens.exe', 'win-unpacked/resources/backend/campus-backend.exe'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
                release = Path(temporary)
                self.packages(release)
                if missing == 'win-unpacked':
                    (release / missing).rename(release / 'not-win-unpacked')
                else:
                    (release / missing).unlink()
                with mock.patch('subprocess.run', side_effect=AssertionError('Fail before OS verification')):
                    with self.assertRaises(RuntimeError):
                        preparation.prepare_release(release, 'win', 'x64', self.signing_env())
                self.assertFalse((release / 'SIGNING-STATUS-win-x64.json').exists())

    def test_optional_elevate_absence_is_explicit_in_verified_scope(self):
        with tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
            release = Path(temporary)
            self.packages(release)
            (release / 'win-unpacked/resources/elevate.exe').unlink()
            with mock.patch('shutil.which', return_value='stub-powershell'), \
                    mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
                status = preparation.prepare_release(release, 'win', 'x64', self.signing_env())
            self.assertIsInstance(status.get('verified_files'), list)
            self.assertNotIn('win-unpacked/resources/elevate.exe', status['verified_files'])
            self.assertEqual(len(status['verified_files']), 4)

    def test_symbolic_link_mode_is_rejected_before_following_the_entry(self):
        with tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
            release = Path(temporary)
            self.packages(release)
            link = release / 'win-unpacked/resources/escape.exe'
            link.write_bytes(b'PUBLIC FIXTURE; lstat supplies symbolic-link mode')
            original = Path.lstat
            # Windows hosts may lack symlink-creation privilege. Substitute only
            # this OS metadata boundary, while real enumeration/control flow runs.
            def lstat(path, *args, **kwargs):
                if path == link:
                    return mock.Mock(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
                return original(path, *args, **kwargs)
            with mock.patch.object(Path, 'lstat', lstat), \
                    mock.patch('subprocess.run', side_effect=AssertionError('Reject link before verification')):
                with self.assertRaises(RuntimeError):
                    preparation.prepare_release(release, 'win', 'x64', self.signing_env())
            self.assertFalse((release / 'SIGNING-STATUS-win-x64.json').exists())

    def test_reparse_point_is_rejected_without_traversing_it(self):
        with tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
            release = Path(temporary)
            self.packages(release)
            original = Path.lstat
            def lstat(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                if path == release / 'win-unpacked/resources':
                    return mock.Mock(st_mode=result.st_mode, st_file_attributes=0x400)
                return result
            with mock.patch.object(Path, 'lstat', lstat), \
                    mock.patch('subprocess.run', side_effect=AssertionError('Reject reparse before verification')):
                with self.assertRaises(RuntimeError):
                    preparation.prepare_release(release, 'win', 'x64', self.signing_env())

    def test_partial_or_malformed_credentials_cannot_fall_back_to_unsigned(self):
        for env in ({'WINDOWS_SIGNING_PASSWORD': 'PUBLIC_FIXTURE_PASSWORD'},
                    {'WINDOWS_SIGNING_PFX_BASE64': 'not valid base64!'}):
            with self.subTest(env=list(env)), tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
                release = Path(temporary)
                self.packages(release)
                with self.assertRaises(RuntimeError):
                    preparation.prepare_release(release, 'win', 'x64', env)
                self.assertFalse((release / 'SIGNING-STATUS-win-x64.json').exists())

    def test_windows_credentials_cannot_claim_to_sign_mac(self):
        with tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
            release = Path(temporary)
            (release / 'Mens-test-arm64.dmg').write_bytes(b'PUBLIC MAC PACKAGE')
            with self.assertRaises(RuntimeError):
                preparation.prepare_release(release, 'mac', 'arm64', self.signing_env())

    def test_no_credentials_records_unsigned_without_implying_verification(self):
        with tempfile.TemporaryDirectory(prefix='mens-ci-test-') as temporary:
            release = Path(temporary)
            (release / 'Mens-Setup-test-x64.exe').write_bytes(b'unsigned-installer')
            with mock.patch('subprocess.run', side_effect=AssertionError('Unsigned cannot call verifier')):
                status = preparation.prepare_release(release, 'win', 'x64', {})
            self.assertEqual(status['status'], 'unsigned')
            self.assertEqual(status['artifacts'], ['Mens-Setup-test-x64.exe'])
            self.assertEqual(status.get('verified_files'), [])
            self.assertIs(status.get('timestamp_required'), False)

    def test_workflow_builder_credentials_and_verification_precede_checksums(self):
        # Validate the workflow boundary contract/order; do not run or contact CI.
        workflow = (ROOT / '.github/workflows/build-desktop.yml').read_text(encoding='utf-8')
        build_start = workflow.index('      - name: Build (')
        verify_start = workflow.index('      - name: Sign and verify')
        build = workflow[build_start:verify_start]
        self.assertIn("WIN_CSC_LINK: ${{ matrix.target_os == 'win' && secrets.WINDOWS_SIGNING_PFX_BASE64 || '' }}", build)
        self.assertIn("WIN_CSC_KEY_PASSWORD: ${{ matrix.target_os == 'win' && secrets.WINDOWS_SIGNING_PASSWORD || '' }}", build)
        self.assertLess(build.index('WIN_CSC_LINK:'), build.index('python scripts/build_desktop.py'))
        prepare = workflow.index('python scripts/prepare_release_ci.py', verify_start)
        checksum = workflow.index('python scripts/release_checksums.py', prepare)
        self.assertLess(prepare, checksum)
        self.assertLess(checksum, workflow.index('      - name: Upload packages', checksum))

if __name__ == '__main__':
    unittest.main()
