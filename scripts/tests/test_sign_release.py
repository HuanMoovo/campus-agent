"""Offline behavior regressions for sign_release.ps1 (Windows, stdlib only).

Run: python -m unittest discover -s scripts/tests -p test_sign_release.py -v
Only external signing/certificate APIs are replaced. The production script and
native executable argument marshalling run for real. No store, key or network is
accessed. The native stub is reused from the 2026-11-01 offline N01 harness.
Set MENS_SIGN_TEST_ARTIFACTS to retain configs, traces and complete process logs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "sign_release.ps1"

NATIVE_STUB = r'''
// OFFLINE STUB ONLY. Never signs, loads certificates or uses a network.
using System;
using System.IO;
using System.Text;
public static class SignToolAcceptanceStub {
    private static string Json(string value) {
        StringBuilder result = new StringBuilder("\"");
        foreach (char c in value) {
            switch (c) {
                case '\\': result.Append("\\\\"); break;
                case '"': result.Append("\\\""); break;
                case '\n': result.Append("\\n"); break;
                case '\r': result.Append("\\r"); break;
                case '\t': result.Append("\\t"); break;
                default:
                    if (c < 32) result.Append("\\u" + ((int)c).ToString("x4"));
                    else result.Append(c);
                    break;
            }
        }
        return result.Append('"').ToString();
    }
    public static int Main(string[] args) {
        string operation = args.Length > 0 ? args[0] : "unknown";
        string trace = Environment.GetEnvironmentVariable("MENS_ACCEPTANCE_TRACE");
        string configured = Environment.GetEnvironmentVariable(operation == "sign" ? "MENS_ACCEPTANCE_SIGN_EXIT" : "MENS_ACCEPTANCE_VERIFY_EXIT");
        int code;
        if (String.IsNullOrEmpty(trace) || !Int32.TryParse(configured, out code)) return 91;
        string[] safe = (string[])args.Clone();
        for (int i = 0; i < safe.Length - 1; i++)
            if (safe[i] == "/p") safe[i + 1] = "[fixture password omitted]";
        StringBuilder array = new StringBuilder("[");
        for (int i = 0; i < safe.Length; i++) {
            if (i != 0) array.Append(',');
            array.Append(Json(safe[i]));
        }
        array.Append(']');
        File.AppendAllText(trace, "{\"kind\":" + Json("signtool_" + operation + "_stub") +
            ",\"data\":{\"arguments\":" + array + ",\"exit_code\":" + code +
            ",\"real_signature\":false}}\n", new UTF8Encoding(false));
        Console.WriteLine("OFFLINE STUB signtool " + operation + ": " + code);
        return code;
    }
}
'''

WRAPPER = r'''
param([string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$global:AcceptanceConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$global:AcceptanceTrace = $global:AcceptanceConfig.TracePath
$env:MENS_ACCEPTANCE_TRACE = $global:AcceptanceTrace
$env:MENS_ACCEPTANCE_SIGN_EXIT = [string]$global:AcceptanceConfig.SignExit
$env:MENS_ACCEPTANCE_VERIFY_EXIT = [string]$global:AcceptanceConfig.VerifyExit
$env:MENS_ACCEPTANCE_TRUST_ERROR = [string]$global:AcceptanceConfig.TrustError
# Replace only the OS trust API. No production test hooks are needed.
Add-Type -TypeDefinition @'
namespace MensSigning {
    public static class NativeTrust {
        public static int Verify(string path) {
            return int.Parse(System.Environment.GetEnvironmentVariable("MENS_ACCEPTANCE_TRUST_ERROR"));
        }
    }
}
'@
function global:Add-AcceptanceTrace([string]$Kind, $Data) {
    [pscustomobject]@{ kind = $Kind; data = $Data } | ConvertTo-Json -Compress -Depth 8 |
        Add-Content -LiteralPath $global:AcceptanceTrace -Encoding utf8
}
function global:Test-Path {
    [CmdletBinding()]param([Parameter(Position = 0)][string]$Path)
    if ($Path -eq 'C:\Program Files (x86)\Windows Kits\10\bin') { return $false }
    return Microsoft.PowerShell.Management\Test-Path -LiteralPath $Path
}
function global:Get-Command {
    [CmdletBinding()]param([Parameter(Position = 0)][string]$Name)
    if ($Name -ne 'signtool.exe') { throw "Unexpected discovery: $Name" }
    if ($global:AcceptanceConfig.ToolAvailable) {
        return [pscustomobject]@{ Source = $global:AcceptanceConfig.StubPath }
    }
    return $null
}
function global:Get-AuthenticodeSignature {
    [CmdletBinding()]param([Parameter(Position = 0)][string]$FilePath)
    Add-AcceptanceTrace 'authenticode_stub' @{ status = $global:AcceptanceConfig.Status }
    $cert = $null
    if ($global:AcceptanceConfig.SignerThumbprint) {
        $cert = [pscustomobject]@{ Subject = 'CN=OFFLINE STUB ONLY'; Thumbprint = $global:AcceptanceConfig.SignerThumbprint }
    }
    $timestamp = if ($global:AcceptanceConfig.HasTimestamp) { [pscustomobject]@{ Subject = 'CN=OFFLINE TIMESTAMP STUB' } } else { $null }
    return [pscustomobject]@{ Status = $global:AcceptanceConfig.Status; SignerCertificate = $cert; TimeStamperCertificate = $timestamp }
}
function global:New-SelfSignedCertificate {
    [CmdletBinding()]param([string]$Type, [string]$Subject, [string]$CertStoreLocation, [datetime]$NotAfter)
    Add-AcceptanceTrace 'create_certificate_stub' @{ real_store_accessed = $false }
    return [pscustomobject]@{ Subject = $Subject; Thumbprint = 'STUB_ONLY_NO_CERTIFICATE_CREATED' }
}
function global:Export-PfxCertificate {
    [CmdletBinding()]param($Cert, [string]$FilePath, [System.Security.SecureString]$Password)
    $resolved = [IO.Path]::GetFullPath($FilePath)
    if (-not $resolved.StartsWith($global:AcceptanceConfig.CaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'PFX escaped test directory' }
    [IO.File]::WriteAllText($resolved, 'OFFLINE STUB - NOT A PFX')
    Add-AcceptanceTrace 'export_pfx_stub' @{ path = $resolved }
    if ($global:AcceptanceConfig.ExportFails) { throw 'Injected offline PFX export failure after a partial file write' }
}
function global:Remove-Item {
    [CmdletBinding()]param([Parameter(Position = 0)][string]$Path, [switch]$Force)
    if ($Path.StartsWith('Cert:', [StringComparison]::OrdinalIgnoreCase)) {
        if ($Path -ne 'Cert:\CurrentUser\My\STUB_ONLY_NO_CERTIFICATE_CREATED') { throw "Unexpected certificate path: $Path" }
        Add-AcceptanceTrace 'remove_certificate_stub' @{ real_store_accessed = $false }
        return
    }
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($global:AcceptanceConfig.CaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Cleanup escaped test directory' }
    Add-AcceptanceTrace 'remove_fixture_file' @{ path = $resolved }
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $resolved -Force:$Force
}
try {
    Write-Host 'OFFLINE SIMULATION: signing, certificates and OS trust are STUBS.'
    $invokeArgs = @{ File = $global:AcceptanceConfig.Target }
    if ($global:AcceptanceConfig.VerifyOnly) {
        $invokeArgs.VerifyOnly = $true
    } elseif ($global:AcceptanceConfig.Demo) {
        $invokeArgs.SelfSignedDemo = $true
        if ($global:AcceptanceConfig.KeepCertificate) { $invokeArgs.KeepCertificate = $true }
    } else {
        $invokeArgs.Pfx = $global:AcceptanceConfig.PfxPath
        $invokeArgs.Password = 'PUBLIC_DUMMY_FIXTURE_PASSWORD'
        $invokeArgs.TimestampUrl = $global:AcceptanceConfig.TimestampUrl
    }
    if ($global:AcceptanceConfig.ExtraArguments) {
        foreach ($property in $global:AcceptanceConfig.ExtraArguments.PSObject.Properties) {
            $invokeArgs[$property.Name] = $property.Value
        }
    }
    & $global:AcceptanceConfig.ScriptPath @invokeArgs
    exit $global:LASTEXITCODE
} catch {
    Add-AcceptanceTrace 'script_exception' @{ message = $_.Exception.Message }
    Write-Error $_ -ErrorAction Continue
    exit 1
}
'''


@unittest.skipUnless(os.name == "nt", "Authenticode script regression requires Windows")
class SigningReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = shutil.which("pwsh") or shutil.which("powershell.exe")
        compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        if not cls.ps or not compiler.is_file():
            raise RuntimeError("Windows signing regressions require PowerShell and .NET Framework csc.exe")
        retained = os.environ.get("MENS_SIGN_TEST_ARTIFACTS")
        cls.temp = None if retained else tempfile.TemporaryDirectory(prefix="mens-sign-offline-")
        cls.root = Path(retained or cls.temp.name).resolve()
        cls.root.mkdir(parents=True, exist_ok=True)
        cls.wrapper = cls.root / "offline_signing_wrapper.ps1"
        cls.wrapper.write_text(WRAPPER, encoding="utf-8")
        source = cls.root / "signtool_OFFLINE_STUB.cs"
        source.write_text(NATIVE_STUB, encoding="utf-8")
        cls.stub = cls.root / "signtool_OFFLINE_STUB.exe"
        proc = subprocess.run([str(compiler), "/noconfig", "/nologo", "/target:exe", "/out:" + str(cls.stub), str(source)],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode:
            raise RuntimeError(proc.stdout + proc.stderr)

    @classmethod
    def tearDownClass(cls):
        if cls.temp:
            cls.temp.cleanup()

    def run_case(self, suffix="", **options):
        root = self.root / (self.id().split(".")[-1] + suffix)
        root.mkdir(parents=True, exist_ok=True)
        trace = root / "trace.jsonl"
        trace.unlink(missing_ok=True)
        target = root / "Mens fixture NOT AN INSTALLER.exe"
        if not options.pop("missing_target", False):
            target.write_bytes(b"OFFLINE STUB ONLY - never execute\n")
        pfx = root / "OFFLINE_NOT_A_CERTIFICATE.pfx"
        pfx.write_text("OFFLINE STUB ONLY\n", encoding="utf-8")
        config = dict(ScriptPath=str(SCRIPT), StubPath=str(self.stub), TracePath=str(trace),
                      CaseRoot=str(root), Target=str(target), PfxPath=str(pfx),
                      ToolAvailable=True, SignExit=0, VerifyExit=0, Status="Valid", Demo=False,
                      KeepCertificate=False, TimestampUrl="", ExportFails=False,
                      VerifyOnly=False, HasTimestamp=True, ExtraArguments={},
                      SignerThumbprint="STUB_ONLY_NO_CERTIFICATE_CREATED", TrustError=0)
        config.update(options)
        path = root / "config.json"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        temp = root / "temp"
        temp.mkdir(exist_ok=True)
        # No user API keys, credentials or .env are inherited/read by the child.
        env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
               "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
               "PATH": str(Path(self.ps).parent) + r";C:\Windows\System32;C:\Windows",
               "PATHEXT": ".COM;.EXE;.BAT;.CMD", "TEMP": str(temp), "TMP": str(temp)}
        argv = [self.ps, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(self.wrapper), "-ConfigPath", str(path)]
        proc = subprocess.run(argv, cwd=root, env=env, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=45)
        log = dict(argv=argv, exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                   simulation=True, real_certificate_store_access=False)
        (root / "process.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        self.output = proc.stdout + proc.stderr
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8-sig").splitlines()] if trace.exists() else []
        return proc.returncode, events

    def assert_success(self, code):
        self.assertEqual(code, 0, self.output)

    def assert_failure(self, code):
        self.assertNotEqual(code, 0, self.output)

    def test_release_valid_signature_succeeds(self):
        code, events = self.run_case()
        self.assert_success(code)
        calls = [e for e in events if e["kind"].startswith("signtool_")]
        self.assertEqual([e["kind"] for e in calls], ["signtool_sign_stub", "signtool_verify_stub"])
        self.assertEqual(calls[0]["data"]["arguments"][:3], ["sign", "/fd", "sha256"])
        self.assertEqual(calls[1]["data"]["arguments"][:3], ["verify", "/pa", "/v"])

    def test_release_failed_native_verification_is_fatal_even_when_authenticode_valid(self):
        code, _ = self.run_case(VerifyExit=23)
        self.assert_failure(code)

    def test_verify_only_verifies_without_signing_certificate_access_or_file_mutation(self):
        code, events = self.run_case(VerifyOnly=True)
        self.assert_success(code)
        self.assertEqual([e['kind'] for e in events], ['signtool_verify_stub', 'authenticode_stub'])
        target = self.root / self.id().split('.')[-1] / 'Mens fixture NOT AN INSTALLER.exe'
        self.assertEqual(target.read_bytes(), b'OFFLINE STUB ONLY - never execute\n')

    def test_verify_parameter_set_cannot_sign_when_switch_is_explicitly_false(self):
        code, events = self.run_case(VerifyOnly=True, ExtraArguments={'VerifyOnly': False})
        self.assert_success(code)
        self.assertEqual([e['kind'] for e in events], ['signtool_verify_stub', 'authenticode_stub'])

    def test_formal_sign_and_verify_only_reject_missing_timestamp(self):
        for verify in (False, True):
            with self.subTest(verify_only=verify):
                code, _ = self.run_case('_verify' if verify else '_sign', VerifyOnly=verify, HasTimestamp=False)
                self.assert_failure(code)

    def test_verify_only_rejects_signing_parameters_before_any_external_call(self):
        combinations = [{'Pfx': 'NOT_A_REAL_CERT.pfx'}, {'Password': 'PUBLIC_FIXTURE'},
                        {'SelfSignedDemo': True}, {'KeepCertificate': True},
                        {'TimestampUrl': 'https://timestamp.invalid/OFFLINE'}]
        for index, extra in enumerate(combinations):
            with self.subTest(parameters=list(extra)):
                code, events = self.run_case('_' + str(index), VerifyOnly=True, ExtraArguments=extra)
                self.assert_failure(code)
                self.assertFalse(any(e['kind'] != 'script_exception' for e in events), events)

    def test_verify_only_keeps_native_and_authenticode_failure_gates(self):
        for index, options in enumerate(({'VerifyExit': 23}, {'Status': 'HashMismatch'},
                                         {'Status': 'NotTrusted'}, {'Status': 'NotSigned'})):
            with self.subTest(options=options):
                code, events = self.run_case('_' + str(index), VerifyOnly=True, **options)
                self.assert_failure(code)
                self.assertFalse(any(e['kind'] == 'signtool_sign_stub' for e in events))

    def test_release_requires_valid_authenticode_even_when_signtool_passes(self):
        for status in ("HashMismatch", "NotSigned", "UnknownError", "NotTrusted", "NotSupportedFileFormat", "Incompatible"):
            with self.subTest(status=status):
                code, _ = self.run_case("_" + status, Status=status)
                self.assert_failure(code)

    def test_failed_signing_does_not_continue_to_verification(self):
        code, events = self.run_case(SignExit=20)
        self.assert_failure(code)
        self.assertFalse(any(e["kind"] == "signtool_verify_stub" for e in events))

    def test_missing_target_is_fatal_before_signing(self):
        code, events = self.run_case(missing_target=True)
        self.assert_failure(code)
        self.assertFalse(any(e["kind"] == "signtool_sign_stub" for e in events))

    def test_missing_signtool_is_fatal(self):
        code, _ = self.run_case(ToolAvailable=False)
        self.assert_failure(code)

    def test_release_timestamp_parameters_are_forwarded(self):
        code, events = self.run_case(TimestampUrl="https://timestamp.invalid/OFFLINE-STUB-ONLY")
        self.assert_success(code)
        args = next(e["data"]["arguments"] for e in events if e["kind"] == "signtool_sign_stub")
        self.assertIn("/tr", args)
        self.assertIn("https://timestamp.invalid/OFFLINE-STUB-ONLY", args)
        self.assertEqual(args[args.index("/td") + 1], "sha256")

    def test_demo_permits_only_precisely_identified_untrusted_root(self):
        for status in ("UnknownError", "NotTrusted"):
            with self.subTest(status=status):
                code, events = self.run_case("_" + status, Demo=True, VerifyExit=1, Status=status,
                                             TrustError=-2146762487, HasTimestamp=False)
                self.assert_success(code)
                args = next(e["data"]["arguments"] for e in events if e["kind"] == "signtool_sign_stub")
                self.assertNotIn("/tr", args)
                self.assertNotIn("/td", args)
                self.assertTrue(any(e["kind"] == "remove_certificate_stub" for e in events))
                exported = next(e["data"]["path"] for e in events if e["kind"] == "export_pfx_stub")
                self.assertFalse(Path(exported).exists())

    def test_demo_generic_unknown_error_is_fatal(self):
        code, _ = self.run_case(Demo=True, VerifyExit=1, Status="UnknownError", TrustError=-2147467259)
        self.assert_failure(code)

    def test_demo_signature_corruption_or_absence_is_fatal_despite_untrusted_root(self):
        for status in ("HashMismatch", "NotSigned", "NotSupportedFileFormat", "Incompatible"):
            with self.subTest(status=status):
                code, _ = self.run_case("_" + status, Demo=True, VerifyExit=1, Status=status, TrustError=-2146762487)
                self.assert_failure(code)

    def test_demo_must_use_the_certificate_created_for_this_run(self):
        for thumb in ("DIFFERENT_CERTIFICATE", ""):
            with self.subTest(thumbprint=thumb):
                code, _ = self.run_case("_" + (thumb or "missing"), Demo=True, SignerThumbprint=thumb)
                self.assert_failure(code)

    def test_demo_valid_signature_requires_native_verification_success(self):
        code, _ = self.run_case(Demo=True, VerifyExit=27)
        self.assert_failure(code)

    def test_demo_cleans_up_after_failed_sign_or_verification(self):
        for name, options in (("sign", {"SignExit": 20}), ("verify", {"Status": "HashMismatch"})):
            with self.subTest(failure=name):
                code, events = self.run_case("_" + name, Demo=True, **options)
                self.assert_failure(code)
                self.assertTrue(any(e["kind"] == "remove_certificate_stub" for e in events))
                exported = next(e["data"]["path"] for e in events if e["kind"] == "export_pfx_stub")
                self.assertFalse(Path(exported).exists())

    def test_keep_certificate_explicitly_retains_demo_fixture(self):
        code, events = self.run_case(Demo=True, KeepCertificate=True)
        self.assert_success(code)
        self.assertFalse(any(e["kind"] == "remove_certificate_stub" for e in events))
        exported = next(e["data"]["path"] for e in events if e["kind"] == "export_pfx_stub")
        self.assertTrue(Path(exported).exists())

    def test_demo_export_failure_cleans_all_temporary_material(self):
        for keep in (False, True):
            with self.subTest(keep_certificate=keep):
                code, events = self.run_case("_keep" if keep else "_default", Demo=True,
                                             KeepCertificate=keep, ExportFails=True)
                self.assert_failure(code)
                self.assertTrue(any(e["kind"] == "create_certificate_stub" for e in events))
                self.assertFalse(any(e["kind"] == "signtool_sign_stub" for e in events))
                exported = next(e["data"]["path"] for e in events if e["kind"] == "export_pfx_stub")
                cleaned_certificate = any(e["kind"] == "remove_certificate_stub" for e in events)
                self.assertEqual((cleaned_certificate, Path(exported).exists()), (True, False), self.output)


if __name__ == "__main__":
    unittest.main()
