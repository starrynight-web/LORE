# ==============================================================================
# LORE Enterprise — Background Services Shutdown (PowerShell)
# Stops Backend (Port 8000), MCP Server (Port 8001), and Frontend (Port 3000)
# ==============================================================================

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  Stopping LORE Enterprise Background Services..." -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$ports = @(8000, 8001, 3000)

foreach ($port in $ports) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($connections) {
            foreach ($conn in $connections) {
                $pidToKill = $conn.OwningProcess
                Write-Host "Stopping service on port $port (PID $pidToKill)..." -ForegroundColor Yellow
                Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
            }
        } else {
            Write-Host "Port $port is not running." -ForegroundColor Gray
        }
    } catch {
        # Fallback to netstat
        $lines = netstat -ano | Select-String ":$port\s+.*LISTENING"
        foreach ($line in $lines) {
            $parts = ($line -split '\s+') | Where-Object { $_ -ne '' }
            $pidToKill = $parts[-1]
            if ($pidToKill -match '^\d+$') {
                Write-Host "Stopping service on port $port (PID $pidToKill)..." -ForegroundColor Yellow
                Stop-Process -Id ([int]$pidToKill) -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Host "`n======================================================================" -ForegroundColor Green
Write-Host "  All LORE services have been stopped." -ForegroundColor Green
Write-Host "======================================================================`n" -ForegroundColor Green

