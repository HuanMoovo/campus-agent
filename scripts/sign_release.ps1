<#
.SYNOPSIS
  用代码签名证书给 Windows 产物签名并立即验签。

.DESCRIPTION
  正式分发需要 CA 签发的代码签名证书（OV/EV）。本脚本把签名与验签固定成一条可复现的流程：
  有证书时直接产出已签名安装包；没有证书时用自签名证书跑通同一条管线，仅用于验证流程本身，
  自签名产物不会被其他机器信任，因此不用于对外分发。

.EXAMPLE
  # 正式证书（.pfx）：
  .\scripts\sign_release.ps1 -File release\Mens-Setup-1.2.2-x64.exe -Pfx C:\certs\codesign.pfx -Password $env:CERT_PASS
  # 自签名演练（仅验证管线，不用于分发）：
  .\scripts\sign_release.ps1 -File release\Mens-Setup-1.2.2-x64.exe -SelfSignedDemo
  # 仅验证构建期已签名的文件，不加载 PFX 或改写文件：
  .\scripts\sign_release.ps1 -File release\win-unpacked\Mens.exe -VerifyOnly
#>
[CmdletBinding(DefaultParameterSetName = 'Pfx')]
param(
  [Parameter(Mandatory = $true)][string]$File,
  [Parameter(ParameterSetName = 'Pfx')][string]$Pfx,
  [Parameter(ParameterSetName = 'Pfx')][string]$Password,
  [Parameter(ParameterSetName = 'Pfx')][string]$TimestampUrl = 'http://timestamp.digicert.com',
  [Parameter(ParameterSetName = 'Demo')][switch]$SelfSignedDemo,
  [Parameter(ParameterSetName = 'Demo')][switch]$KeepCertificate,
  [Parameter(Mandatory = $true, ParameterSetName = 'Verify')][switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'

function Find-SignTool {
  $candidates = @()
  $kits = 'C:\Program Files (x86)\Windows Kits\10\bin'
  if (Test-Path $kits) {
    $candidates += Get-ChildItem -Path $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
  }
  $fromPath = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
  if ($fromPath) { $candidates += $fromPath }
  if (-not $candidates) { throw '未找到 signtool.exe（安装 Windows SDK 或在 PATH 中提供）' }
  return $candidates[0]
}

function Get-AuthenticodeTrustError([string]$Path) {
  # SignatureStatus.UnknownError covers many failures. Inspect the underlying
  # trust result so the demo can allow ONLY CERT_E_UNTRUSTEDROOT, not corruption
  # or an unrelated verification error. Cache-only verification never fetches
  # certificates, CRLs or timestamps and never changes the certificate stores.
  if (-not ('MensSigning.NativeTrust' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace MensSigning {
    public static class NativeTrust {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct FileInfo {
            public uint Size;
            [MarshalAs(UnmanagedType.LPWStr)] public string Path;
            public IntPtr File;
            public IntPtr KnownSubject;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct TrustData {
            public uint Size;
            public IntPtr PolicyCallbackData;
            public IntPtr SipClientData;
            public uint UIChoice;
            public uint RevocationChecks;
            public uint UnionChoice;
            public IntPtr FileInfo;
            public uint StateAction;
            public IntPtr StateData;
            public IntPtr URLReference;
            public uint ProviderFlags;
            public uint UIContext;
        }
        [DllImport("wintrust.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        private static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref TrustData data);
        public static int Verify(string path) {
            FileInfo file = new FileInfo { Size = (uint)Marshal.SizeOf(typeof(FileInfo)), Path = path };
            IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(FileInfo)));
            Marshal.StructureToPtr(file, pointer, false);
            TrustData data = new TrustData {
                Size = (uint)Marshal.SizeOf(typeof(TrustData)), UIChoice = 2,
                UnionChoice = 1, FileInfo = pointer, StateAction = 1,
                ProviderFlags = 0x1010 // CACHE_ONLY_URL_RETRIEVAL | REVOCATION_CHECK_NONE
            };
            Guid action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
            try { return WinVerifyTrust(new IntPtr(-1), ref action, ref data); }
            finally {
                data.StateAction = 2; // WTD_STATEACTION_CLOSE
                WinVerifyTrust(new IntPtr(-1), ref action, ref data);
                Marshal.DestroyStructure(pointer, typeof(FileInfo));
                Marshal.FreeHGlobal(pointer);
            }
        }
    }
}
'@
  }
  return [MensSigning.NativeTrust]::Verify($Path)
}

$signtool = Find-SignTool
Write-Host "signtool: $signtool"

$target = (Resolve-Path $File).Path
Write-Host "目标: $target"

$created = $null
$pfxPath = $null
$demoPrepared = $false
try {
  if ($SelfSignedDemo) {
    # 仅用于验证管线：生成自签名证书并导出临时 pfx
    $created = New-SelfSignedCertificate -Type CodeSigningCert `
      -Subject 'CN=Mens local signing pipeline test' -CertStoreLocation 'Cert:\CurrentUser\My' `
      -NotAfter (Get-Date).AddDays(7)
    $pfxPath = Join-Path $env:TEMP ('mens-demo-' + [guid]::NewGuid().ToString('N') + '.pfx')
    $demoPass = [guid]::NewGuid().ToString('N')
    $secure = ConvertTo-SecureString -String $demoPass -Force -AsPlainText
    Export-PfxCertificate -Cert $created -FilePath $pfxPath -Password $secure | Out-Null
    $demoPrepared = $true
    $Pfx = $pfxPath
    $Password = $demoPass
    Write-Host "已生成自签名证书（有效 7 天，仅本机测试）: $($created.Thumbprint)"
  }

  # The parameter set is the mode: -VerifyOnly:$false must still never sign.
  if ($PSCmdlet.ParameterSetName -ne 'Verify') {
    & $signtool sign /fd sha256 /f $Pfx /p $Password $(if ($TimestampUrl -and -not $SelfSignedDemo) { @('/tr', $TimestampUrl, '/td', 'sha256') }) $target
    if ($LASTEXITCODE -ne 0) { throw "signtool 退出码 $LASTEXITCODE" }
  }

  & $signtool verify /pa /v $target
  $verifyCode = $LASTEXITCODE

  $sig = Get-AuthenticodeSignature $target
  Write-Host ""
  Write-Host ("签名状态: {0}" -f $sig.Status)
  Write-Host ("签名主体: {0}" -f $sig.SignerCertificate.Subject)
  Write-Host ("指纹:     {0}" -f $sig.SignerCertificate.Thumbprint)
  if ($SelfSignedDemo) {
    if (-not $sig.SignerCertificate -or $sig.SignerCertificate.Thumbprint -ne $created.Thumbprint) {
      throw '自签名演练验签失败：签名证书与本次生成的证书不匹配。'
    }
    if ($sig.Status -eq 'Valid' -and $verifyCode -eq 0) {
      Write-Host '自签名演练验签通过。'
    }
    elseif ($sig.Status -in @('UnknownError', 'NotTrusted') -and
      (Get-AuthenticodeTrustError $target) -eq -2146762487) { # CERT_E_UNTRUSTEDROOT (0x800B0109)
      Write-Host '自签名演练通过完整性检查；证书链不受信任，仅用于本机测试，不用于对外分发。' -ForegroundColor Yellow
    }
    else {
      throw "自签名演练验签失败：signtool verify=$verifyCode，Authenticode=$($sig.Status)。"
    }
  }
  elseif ($verifyCode -ne 0 -or $sig.Status -ne 'Valid') {
    throw "发行验签失败：signtool verify=$verifyCode，Authenticode=$($sig.Status)。"
  }
  elseif (-not $sig.TimeStamperCertificate) {
    throw '发行验签失败：缺少可信签名时间戳证书。'
  }
  exit 0
}
finally {
  # KeepCertificate preserves a completed demo setup. A failed export must not
  # retain a half-created PFX or its certificate, even when retention was asked.
  if ($created -and (-not $KeepCertificate -or -not $demoPrepared)) {
    Remove-Item "Cert:\CurrentUser\My\$($created.Thumbprint)" -Force -ErrorAction SilentlyContinue
    if ($pfxPath -and (Test-Path $pfxPath)) { Remove-Item $pfxPath -Force -ErrorAction SilentlyContinue }
    Write-Host "已清理自签名证书与临时 pfx"
  }
}
