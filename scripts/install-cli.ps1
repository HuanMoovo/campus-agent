<#
.SYNOPSIS
  安装 Mens 命令行工具（Windows）。

.DESCRIPTION
  下载源码到 %LOCALAPPDATA%\Mens\cli，创建独立虚拟环境并安装依赖，
  生成 mens.cmd 启动脚本并加入用户 PATH。不改动系统 Python，卸载只需删目录。

.EXAMPLE
  irm https://raw.githubusercontent.com/HuanMoovo/campus-agent/main/scripts/install-cli.ps1 | iex
#>
$ErrorActionPreference = 'Stop'

$root = Join-Path $env:LOCALAPPDATA 'Mens\cli'
$shimDir = Join-Path $env:LOCALAPPDATA 'Mens\bin'
$zip = Join-Path $env:TEMP ("mens-src-" + [guid]::NewGuid().ToString('N') + ".zip")
$work = Join-Path $env:TEMP ("mens-cli-" + [guid]::NewGuid().ToString('N'))

function Find-Python {
  foreach ($candidate in @('python', 'py')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $command) { continue }
    $args = if ($candidate -eq 'py') { @('-3', '-c') } else { @('-c') }
    try {
      $version = & $candidate @args 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
      if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]'3.10') {
        return @{ Exe = $candidate; Prefix = $args[0..($args.Length - 2)] }
      }
    } catch { }
  }
  return $null
}

$python = Find-Python
if (-not $python) {
  throw '未找到 Python 3.10+，请先安装（https://www.python.org/downloads/，安装时勾选 Add to PATH）'
}

Write-Host "1/4 下载源码…" -ForegroundColor Cyan
Invoke-WebRequest -Uri 'https://github.com/HuanMoovo/campus-agent/archive/refs/heads/main.zip' -OutFile $zip

Write-Host "2/4 解压到 $root …" -ForegroundColor Cyan
Expand-Archive -Path $zip -DestinationPath $work -Force
New-Item -ItemType Directory -Force -Path (Split-Path $root) | Out-Null
if (Test-Path $root) { Remove-Item $root -Recurse -Force }
Move-Item (Join-Path $work 'campus-agent-main') $root
Remove-Item $zip, $work -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "3/4 创建虚拟环境并安装依赖（约 1-3 分钟）…" -ForegroundColor Cyan
& $python.Exe @($python.Prefix) -m venv (Join-Path $root '.venv')
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $root 'backend\requirements.txt') --quiet

Write-Host "4/4 生成 mens 命令…" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
$shim = @"
@echo off
pushd "%~dp0..\cli\backend" || exit /b 1
"%~dp0..\cli\.venv\Scripts\python.exe" -m app.cli %*
popd
"@
Set-Content -Path (Join-Path $shimDir 'mens.cmd') -Value $shim -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$shimDir*") {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;$shimDir", 'User')
  Write-Host "已把 $shimDir 加入用户 PATH（新开的终端生效）" -ForegroundColor Yellow
}
$env:Path = "$env:Path;$shimDir"

Write-Host ''
Write-Host "安装完成。验证：" -ForegroundColor Green
& (Join-Path $shimDir 'mens.cmd') --version
Write-Host '试试： mens ask "图书馆开放时间"' -ForegroundColor Green
Write-Host "卸载：删除 $root 与 $shimDir 即可" -ForegroundColor DarkGray
