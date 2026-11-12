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
  param([string[]]$Rest)
  Need-Uv
  $env:LORE_CHECKOUT = $Root
  uv run --managed-python --python 3.12 --no-build --locked --project $Root python -m lore install @Rest
  exit $LASTEXITCODE
}

function Uninstall-Lore {
  Need-Uv
  $env:LORE_CHECKOUT = $Root
  uv run --managed-python --python 3.12 --no-build --locked --project $Root python -m lore uninstall
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
  "install" {
    $InstallArgs = @()
    if ($args.Count -gt 1) { $InstallArgs = $args[1..($args.Count - 1)] }
    Install-Lore -Rest $InstallArgs
  }
  "uninstall" { Uninstall-Lore }
  { $_ -in "setup", "up" } {
    Require-Lore
    $SetupArgs = @()
    if ($args.Count -gt 1) { $SetupArgs = $args[1..($args.Count - 1)] }
    $env:LORE_COMMAND = $Bin
    $env:LORE_LAUNCHER = Join-Path $Root "scripts\lore-solo.ps1"
    $env:LORE_PROJECT_NAME = Split-Path -Leaf (Get-Location)
    & $Bin setup @SetupArgs
    exit $LASTEXITCODE
  }
  "mcp" {
    Require-Lore
    if ($env:LORE_PROJECT) { Set-Location $env:LORE_PROJECT }
    $McpArgs = @()
    if ($args.Count -gt 1) { $McpArgs = $args[1..($args.Count - 1)] }
    & $Bin mcp @McpArgs
    exit $LASTEXITCODE
  }
  "connect" {
    Require-Lore
    $ConnectArgs = @()
    if ($args.Count -gt 1) { $ConnectArgs = $args[1..($args.Count - 1)] }
    $env:LORE_COMMAND = $Bin
    $env:LORE_LAUNCHER = Join-Path $Root "scripts\lore-solo.ps1"
    $env:LORE_HOST_OS = "windows"
    & $Bin connect @ConnectArgs
    exit $LASTEXITCODE
  }
  "map" {
    Require-Lore
    if ($env:LORE_PROJECT) { Set-Location $env:LORE_PROJECT }
    $MapArgs = @()
    if ($args.Count -gt 1) { $MapArgs = $args[1..($args.Count - 1)] }
    & $Bin map @MapArgs
    exit $LASTEXITCODE
  }
  "doctor" {
    Need-Uv
    $env:LORE_CHECKOUT = $Root
    $DoctorArgs = @()
    if ($args.Count -gt 1) { $DoctorArgs = $args[1..($args.Count - 1)] }
    if (Test-Path $Bin) {
      & $Bin doctor @DoctorArgs
      exit $LASTEXITCODE
    }
    uv run --managed-python --python 3.12 --no-build --locked --project $Root python -m lore doctor @DoctorArgs
    exit $LASTEXITCODE
  }
  default {
    Write-Error "usage: scripts/lore-solo.ps1 install|setup|uninstall|mcp|connect|map|doctor"
    exit 2
  }
}
