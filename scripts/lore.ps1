# Install Lore, serve the setup site, or hand Lore to an editor.
# The editor starts %USERPROFILE%\.lore\bin\lore.exe directly. Docker is not required.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Prefix = Join-Path $env:USERPROFILE ".lore"
$Bin = Join-Path $Prefix "bin\lore.exe"

function Need-Uv {
  if (Get-Command uv -ErrorAction SilentlyContinue) { return }
  $LocalUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
  if (Test-Path $LocalUv) {
    $env:Path = "$(Split-Path $LocalUv);$env:Path"
    return
  }
  Write-Output "Installing uv..."
  irm https://astral.sh/uv/install.ps1 | iex
  $env:Path = "$(Join-Path $env:USERPROFILE '.local\bin');$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv could not be installed."
  }
}

function Build-Site {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Output "Node.js was not found. The agent can use Lore. The setup site needs Node.js."
    return
  }
  Push-Location (Join-Path $Root "web")
  try {
    npm ci
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  } finally {
    Pop-Location
  }
  $Standalone = Join-Path $Root "web\.next\standalone"
  $Static = Join-Path $Root "web\.next\static"
  if (Test-Path $Static) {
    $Dest = Join-Path $Standalone ".next\static"
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Copy-Item -Recurse $Static $Dest
  }
  $Public = Join-Path $Root "web\public"
  if (Test-Path $Public) {
    $DestPublic = Join-Path $Standalone "public"
    if (Test-Path $DestPublic) { Remove-Item -Recurse -Force $DestPublic }
    Copy-Item -Recurse $Public $DestPublic
  }
}

function Install-Lore {
  Need-Uv
  New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
  $env:UV_TOOL_DIR = Join-Path $Prefix "tools"
  $env:UV_TOOL_BIN_DIR = Join-Path $Prefix "bin"
  uv tool install --python 3.12 --force --editable $Root
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Build-Site
  Write-Output "Lore is installed at $Bin"
}

function Require-Lore {
  if (-not (Test-Path $Bin)) {
    throw "Lore is not installed. Run scripts/lore.ps1 install"
  }
}

$Command = "setup"
if ($args.Count -gt 0) { $Command = $args[0] }

switch ($Command) {
  "install" { Install-Lore }
  { $_ -in "setup", "up" } {
    Require-Lore
    $env:LORE_COMMAND = $Bin
    $env:LORE_LAUNCHER = Join-Path $Root "scripts\lore.ps1"
    $env:LORE_PROJECT_NAME = Split-Path -Leaf (Get-Location)
    & $Bin setup
    exit $LASTEXITCODE
  }
  "mcp" {
    Require-Lore
    if ($env:LORE_PROJECT) { Set-Location $env:LORE_PROJECT }
    & $Bin mcp
    exit $LASTEXITCODE
  }
  "connect" {
    Require-Lore
    $env:LORE_COMMAND = $Bin
    $env:LORE_LAUNCHER = Join-Path $Root "scripts\lore.ps1"
    $env:LORE_HOST_OS = "windows"
    & $Bin connect
    exit $LASTEXITCODE
  }
  default {
    Write-Error "usage: scripts/lore.ps1 install|setup|mcp|connect"
    exit 2
  }
}
