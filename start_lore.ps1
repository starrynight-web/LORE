# ==============================================================================
# LORE Enterprise — Unified Application Launcher (PowerShell)
# Starts Backend (Port 8000), MCP Server (Port 8001), and Frontend (Port 3000)
# ==============================================================================

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $ScriptDir

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "  Starting LORE Enterprise (Zero-Docker Native Host Mode)..." -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

function Test-PortListening([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $conn)
    } catch {
        $found = netstat -ano | Select-String ":$Port\s+.*LISTENING"
        return ($null -ne $found)
    }
}

# 1. Verify Prerequisites
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.12+ and ensure 'Add to PATH' is checked." -ForegroundColor Yellow
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Node.js / npm is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Node.js from https://nodejs.org" -ForegroundColor Yellow
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

# 2. Start Django Backend Server (Port 8000)
if (Test-PortListening 8000) {
    Write-Host "[1/4] Backend is already running on port 8000." -ForegroundColor Green
} else {
    Write-Host "[1/4] Starting LORE Governance Engine on port 8000..." -ForegroundColor Yellow
    $backendPath = Join-Path $ScriptDir "backend"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$backendPath'; `$host.UI.RawUI.WindowTitle = 'LORE Backend (Port 8000)'; Write-Host '--- LORE Enterprise Backend (Port 8000) ---' -ForegroundColor Green; python manage.py runserver 127.0.0.1:8000 --noreload"
}

# 3. Start MCP Streamable HTTP Server (Port 8001)
if (Test-PortListening 8001) {
    Write-Host "[2/4] MCP Server is already running on port 8001." -ForegroundColor Green
} else {
    Write-Host "[2/4] Starting LORE MCP Streamable HTTP Server on port 8001..." -ForegroundColor Yellow
    $backendPath = Join-Path $ScriptDir "backend"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$backendPath'; `$host.UI.RawUI.WindowTitle = 'LORE MCP Server (Port 8001)'; Write-Host '--- LORE Enterprise MCP Server (Port 8001) ---' -ForegroundColor Green; python mcp_server.py --transport http --port 8001"
}

# 4. Start Next.js Frontend Server (Port 3000)
if (Test-PortListening 3000) {
    Write-Host "[3/4] Frontend is already running on port 3000." -ForegroundColor Green
} else {
    Write-Host "[3/4] Starting LORE Knowledge Grid Interface on port 3000..." -ForegroundColor Yellow
    $frontendPath = Join-Path $ScriptDir "frontend"
    $nextBuild = Join-Path $frontendPath ".next"
    $frontendCmd = if (Test-Path $nextBuild) { "npm start" } else { "npm run dev" }
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Set-Location '$frontendPath'; `$host.UI.RawUI.WindowTitle = 'LORE Frontend (Port 3000)'; Write-Host '--- LORE Enterprise Frontend (Port 3000) ---' -ForegroundColor Green; $frontendCmd"
}

# 5. Wait for servers to initialize
Write-Host "[4/4] Waiting for servers to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# 6. Open Dedicated App Window (Edge / Chrome App Mode or default browser)
$edgePaths = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)

$appLaunched = $false
foreach ($path in $edgePaths) {
    if (Test-Path $path) {
        Start-Process $path -ArgumentList "--app=http://localhost:3000", "--window-size=1360,860"
        $appLaunched = $true
        break
    }
}
if (-not $appLaunched) {
    foreach ($path in $chromePaths) {
        if (Test-Path $path) {
            Start-Process $path -ArgumentList "--app=http://localhost:3000", "--window-size=1360,860"
            $appLaunched = $true
            break
        }
    }
}
if (-not $appLaunched) {
    Start-Process "http://localhost:3000"
}

Write-Host "`n========================================================================" -ForegroundColor Green
Write-Host "  LORE Enterprise is running!" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Green
Write-Host "  Frontend Web UI:   http://localhost:3000" -ForegroundColor White
Write-Host "  Backend REST API:  http://127.0.0.1:8000/api/v1" -ForegroundColor White
Write-Host "  MCP Server (HTTP): http://127.0.0.1:8001/mcp" -ForegroundColor White
Write-Host "  Django Admin:      http://127.0.0.1:8000/admin" -ForegroundColor White
Write-Host "------------------------------------------------------------------------" -ForegroundColor Gray
Write-Host "  Demo Login Credentials:" -ForegroundColor Cyan
Write-Host "    Admin:    admin@northstar.demo    / Northstar2026!" -ForegroundColor White
Write-Host "    Reviewer: reviewer@northstar.demo / Northstar2026!" -ForegroundColor White
Write-Host "    Viewer:   viewer@northstar.demo   / Northstar2026!" -ForegroundColor White
Write-Host "------------------------------------------------------------------------" -ForegroundColor Gray
Write-Host "  To stop all services, run Stop_LORE.bat or Stop_LORE.ps1" -ForegroundColor Yellow
Write-Host "========================================================================`n" -ForegroundColor Green
