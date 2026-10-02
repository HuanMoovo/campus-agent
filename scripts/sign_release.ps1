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
#>
[CmdletBinding(DefaultParameterSetName = 'Pfx')]
param(
  [Parameter(Mandatory = $true)][string]$File,
  [Parameter(ParameterSetName = 'Pfx')][string]$Pfx,
  [Parameter(ParameterSetName = 'Pfx')][string]$Password,
  [Parameter(ParameterSetName = 'Pfx')][string]$TimestampUrl = 'http://timestamp.digicert.com',
  [Parameter(ParameterSetName = 'Demo')][switch]$SelfSignedDemo,
  [switch]$KeepCertificate
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

$signtool = Find-SignTool
Write-Host "signtool: $signtool"

$target = (Resolve-Path $File).Path
Write-Host "目标: $target"

$created = $null
if ($SelfSignedDemo) {
  # 仅用于验证管线：生成自签名证书并导出临时 pfx
  $created = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject 'CN=Mens local signing pipeline test' -CertStoreLocation 'Cert:\CurrentUser\My' `
    -NotAfter (Get-Date).AddDays(7)
  $pfxPath = Join-Path $env:TEMP ('mens-demo-' + [guid]::NewGuid().ToString('N') + '.pfx')
  $demoPass = [guid]::NewGuid().ToString('N')
  $secure = ConvertTo-SecureString -String $demoPass -Force -AsPlainText
  Export-PfxCertificate -Cert $created -FilePath $pfxPath -Password $secure | Out-Null
  $Pfx = $pfxPath
  $Password = $demoPass
  Write-Host "已生成自签名证书（有效 7 天，仅本机测试）: $($created.Thumbprint)"
}

try {
  & $signtool sign /fd sha256 /f $Pfx /p $Password $(if ($TimestampUrl -and -not $SelfSignedDemo) { @('/tr', $TimestampUrl, '/td', 'sha256') }) $target
  if ($LASTEXITCODE -ne 0) { throw "signtool 退出码 $LASTEXITCODE" }

  & $signtool verify /pa /v $target
  $verifyCode = $LASTEXITCODE

  $sig = Get-AuthenticodeSignature $target
  Write-Host ""
  Write-Host ("签名状态: {0}" -f $sig.Status)
  Write-Host ("签名主体: {0}" -f $sig.SignerCertificate.Subject)
  Write-Host ("指纹:     {0}" -f $sig.SignerCertificate.Thumbprint)
  if ($SelfSignedDemo) {
    Write-Host "提示: 自签名证书的链不受信任，Status 为 UnknownError 属预期；对外分发需 CA 签发的证书。" -ForegroundColor Yellow
  }
  elseif ($verifyCode -ne 0) {
    Write-Host "提示: signtool verify 返回 $verifyCode，请确认证书链与时间戳服务。" -ForegroundColor Yellow
  }
  exit 0
}
finally {
  if ($created -and -not $KeepCertificate) {
    Remove-Item "Cert:\CurrentUser\My\$($created.Thumbprint)" -Force -ErrorAction SilentlyContinue
    if ($pfxPath -and (Test-Path $pfxPath)) { Remove-Item $pfxPath -Force -ErrorAction SilentlyContinue }
    Write-Host "已清理自签名证书与临时 pfx"
  }
}
