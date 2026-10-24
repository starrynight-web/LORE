# Install Lore Solo, serve the setup site, or hand it to an editor.
# The editor starts %USERPROFILE%\.lore\bin\lore-solo.exe directly. Docker is not required.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Prefix = Join-Path $env:USERPROFILE ".lore"
$Bin = Join-Path $Prefix "bin\lore-solo.exe"

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

function Install-Lore {
  Need-Uv
  $env:LORE_CHECKOUT = $Root
  uv run --python 3.12 --project $Root python -m lore install
  exit $LASTEXITCODE
}

function Require-Lore {
  if (-not (Test-Path $Bin)) {
    throw "Lore Solo is not installed. Run scripts/lore-solo.ps1 install"
  }
}

$Command = "setup"
if ($args.Count -gt 0) { $Command = $args[0] }

switch ($Command) {
  "install" { Install-Lore }
  { $_ -in "setup", "up" } {
    Require-Lore
    $env:LORE_COMMAND = $Bin
    $env:LORE_LAUNCHER = Join-Path $Root "scripts\lore-solo.ps1"
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
    $env:LORE_LAUNCHER = Join-Path $Root "scripts\lore-solo.ps1"
    $env:LORE_HOST_OS = "windows"
    & $Bin connect
    exit $LASTEXITCODE
  }
  default {
    Write-Error "usage: scripts/lore-solo.ps1 install|setup|mcp|connect"
    exit 2
  }
}
