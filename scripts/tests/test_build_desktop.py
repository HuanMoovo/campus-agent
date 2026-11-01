"""Guard desktop build selection without installing dependencies or packaging."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('build_desktop', ROOT / 'scripts' / 'build_desktop.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class DesktopBuildTargetTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix='mens-build-guard-'))
        self.root = Path(temporary)
        self.python = build.venv_python(self.root / 'backend')
        self.python.parent.mkdir(parents=True)
        self.python.touch()
        self.commands = []
        self.probes = []
        self.launcher_probes = []
        self.runtime = {
            'sys_platform': 'win32', 'machine': 'AMD64',
            'sysconfig_platform': 'win-amd64', 'pointer_bits': 64,
            'multiarch': '', 'host_gnu_type': '',
        }
        self.launcher_runtime = dict(self.runtime)
        self.probe_output = None
        self.probe_error = None
        self.enterContext(mock.patch.object(build, 'ROOT', self.root))
        self.enterContext(mock.patch.object(build.sys, 'platform', 'win32'))
        self.enterContext(mock.patch.object(build.platform, 'machine', return_value='AMD64'))
        self.enterContext(mock.patch.object(build, 'npm_command', return_value='npm-stub'))
        self.enterContext(mock.patch.object(build.shutil, 'which', return_value='node-stub'))
        self.enterContext(mock.patch.object(build.subprocess, 'check_output', side_effect=self.check_output))
        self.enterContext(mock.patch.object(build, 'run', side_effect=self.record_command))
        self.enterContext(mock.patch.object(build.venv, 'create', side_effect=AssertionError('unexpected venv creation')))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    # unittest.TestCase.enterContext was introduced in Python 3.11; builds support 3.10.
    def enterContext(self, context):
        result = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return result

    def check_output(self, command, **kwargs):
        if command == ['node-stub', '--version']:
            return 'v22.0.0\n'
        if str(command[0]) == sys.executable:
            self.launcher_probes.append(command)
            return json.dumps(self.launcher_runtime)
        if str(command[0]) == str(self.python):
            self.probes.append(command)
            if self.probe_error:
                raise self.probe_error
            return self.probe_output if self.probe_output is not None else json.dumps(self.runtime)
        raise AssertionError('Unexpected external process: ' + str(command[0]))

    def record_command(self, command, *args, **kwargs):
        self.commands.append([str(part) for part in command])

    def invoke(self, *arguments, skip_install=True):
        options = ['--skip-install'] if skip_install else []
        with mock.patch.object(build.sys, 'argv', ['build_desktop.py', *options, *arguments]):
            build.main()

    def assert_rejected_before_build(self, pattern, *arguments):
        with self.assertRaisesRegex(RuntimeError, pattern):
            self.invoke(*arguments)
        self.assertEqual(self.commands, [], 'No install, test, freeze or packaging command may run')

    def test_explicit_linux_or_mac_target_cannot_bypass_windows_host_check(self):
        for target in ['linux', 'mac']:
            with self.subTest(target=target):
                self.assert_rejected_before_build('cannot be frozen', '--os', target)
        self.assertEqual(self.probes, [], 'Reject foreign OS before consulting the backend')

    def test_default_target_rejects_unknown_host_platform(self):
        with mock.patch.object(build.sys, 'platform', 'freebsd14'):
            self.assert_rejected_before_build('Unsupported build platform')

    def test_explicit_target_rejects_unknown_host_platform(self):
        with mock.patch.object(build.sys, 'platform', 'freebsd14'):
            self.assert_rejected_before_build('Unsupported build platform', '--os', 'linux')

    def test_explicit_architecture_must_match_backend_python(self):
        self.assert_rejected_before_build('architecture', '--os', 'win', '--arch', 'arm64')

    def test_default_architecture_uses_backend_python_instead_of_launcher_machine(self):
        with mock.patch.object(build.platform, 'machine', return_value='ARM64'):
            self.invoke('--os', 'win')
        self.assertIn('--x64', self.commands[-1])
        self.assertNotIn('--arm64', self.commands[-1])
        self.assertTrue(self.probes, 'Selection must inspect the interpreter used to freeze the backend')

    def test_backend_windows_build_tag_takes_precedence_over_os_machine(self):
        self.runtime['machine'] = 'ARM64'
        self.invoke('--os', 'win', '--arch', 'x64')
        self.assertIn('--x64', self.commands[-1])
        self.assertTrue(self.probes)

    def test_arm64_backend_is_allowed_even_when_launcher_machine_is_x64(self):
        self.runtime.update(machine='ARM64', sysconfig_platform='win-arm64')
        self.invoke('--os', 'win')
        self.assertIn('--arm64', self.commands[-1])
        self.assertEqual(self.launcher_probes, [], 'An existing venv remains authoritative')

    def assert_rejected_before_venv_creation(self, pattern, *arguments):
        self.python.unlink()
        creations = []

        def create_venv(directory, **kwargs):
            creations.append({'directory': str(directory), **kwargs})
            self.python.touch()

        with mock.patch.object(build.venv, 'create', side_effect=create_venv):
            with self.assertRaisesRegex(RuntimeError, pattern):
                self.invoke(*arguments, skip_install=False)
        self.assertEqual(creations, [], 'Reject before venv.create can bootstrap pip')
        self.assertFalse(self.python.exists(), 'A rejected target must not create a venv')
        self.assertEqual(self.commands, [], 'No dependency installation or build may run')

    def test_missing_venv_rejects_32_bit_launcher_before_creating_or_bootstrapping_pip(self):
        self.runtime.update(pointer_bits=32, sysconfig_platform='win32', machine='x86')
        self.launcher_runtime = dict(self.runtime)
        self.assert_rejected_before_venv_creation('64-bit', '--os', 'win')

    def test_missing_venv_rejects_architecture_mismatch_before_creating_or_bootstrapping_pip(self):
        self.assert_rejected_before_venv_creation('architecture', '--os', 'win', '--arch', 'arm64')

    def test_32_bit_backend_is_rejected(self):
        self.runtime.update(pointer_bits=32, sysconfig_platform='win32', machine='x86')
        self.assert_rejected_before_build('64-bit')

    def test_unknown_backend_architecture_is_not_guessed_as_arm64(self):
        self.runtime.update(sysconfig_platform='win-s390x', machine='s390x')
        self.assert_rejected_before_build('architecture')

    def test_backend_from_another_os_is_rejected(self):
        self.runtime.update(sys_platform='linux', sysconfig_platform='linux-x86_64',
                            machine='x86_64', multiarch='x86_64-linux-gnu')
        self.assert_rejected_before_build('backend Python.*platform')

    def test_unknown_backend_os_is_rejected(self):
        self.runtime['sys_platform'] = 'freebsd14'
        self.assert_rejected_before_build('backend Python.*platform')

    def test_malformed_probe_response_fails_closed(self):
        for output in ['not json', '[]', '{}', '{"pointer_bits": "64"}']:
            with self.subTest(output=output):
                self.probe_output = output
                self.assert_rejected_before_build('backend Python')

    def test_probe_failure_does_not_expose_subprocess_output(self):
        self.probe_error = subprocess.CalledProcessError(
            7, ['python', 'private-fixture-value'], output='private-fixture-value', stderr='private-fixture-value')
        with self.assertRaises(RuntimeError) as error:
            self.invoke()
        self.assertNotIn('private-fixture-value', str(error.exception))
        self.assertIn('backend Python', str(error.exception))
        self.assertEqual(self.commands, [])

    def test_missing_probe_interpreter_fails_closed(self):
        self.probe_error = OSError('private-fixture-value')
        with self.assertRaises(RuntimeError) as error:
            self.invoke()
        self.assertNotIn('private-fixture-value', str(error.exception))
        self.assertIn('backend Python', str(error.exception))
        self.assertEqual(self.commands, [])

    def test_mac_universal2_defaults_to_the_running_backend_architecture(self):
        for machine, expected in [('x86_64', '--x64'), ('arm64', '--arm64')]:
            with self.subTest(machine=machine), mock.patch.object(build.sys, 'platform', 'darwin'):
                self.runtime.update(sys_platform='darwin', machine=machine,
                                    sysconfig_platform='macosx-12.0-universal2')
                self.invoke('--os', 'mac')
                self.assertIn(expected, self.commands[-1])

    def test_mac_unknown_running_architecture_is_rejected(self):
        with mock.patch.object(build.sys, 'platform', 'darwin'):
            self.runtime.update(sys_platform='darwin', machine='unknown',
                                sysconfig_platform='macosx-12.0-universal2')
            self.assert_rejected_before_build('architecture', '--os', 'mac')

    def test_linux_uses_interpreter_build_architecture_instead_of_kernel_machine(self):
        with mock.patch.object(build.sys, 'platform', 'linux'):
            self.runtime.update(sys_platform='linux', machine='aarch64',
                                sysconfig_platform='linux-aarch64', multiarch='x86_64-linux-gnu',
                                host_gnu_type='x86_64-pc-linux-gnu')
            self.invoke('--os', 'linux')
            self.assertIn('--x64', self.commands[-1])
            self.assertTrue(self.probes)

    def test_linux_unknown_or_conflicting_build_architecture_is_rejected(self):
        for multiarch, host in [('s390x-linux-gnu', ''), ('', ''),
                                ('x86_64-linux-gnu', 'aarch64-linux-gnu')]:
            with self.subTest(multiarch=multiarch, host=host), \
                    mock.patch.object(build.sys, 'platform', 'linux'):
                self.runtime.update(sys_platform='linux', machine='x86_64',
                                    sysconfig_platform='linux-x86_64', multiarch=multiarch, host_gnu_type=host)
                self.assert_rejected_before_build('architecture', '--os', 'linux')


if __name__ == '__main__':
    unittest.main()
