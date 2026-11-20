@echo off
title Stop LORE Enterprise
echo ======================================================================
echo   Stopping LORE Enterprise Background Services...
echo ======================================================================

powershell -NoProfile -Command "$ports = 8000, 8001, 3000; foreach ($p in $ports) { $pids = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($id in $pids) { Write-Host \"Stopping process on port $p (PID $id)...\"; Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } }"

echo.
echo ======================================================================
echo   All LORE services have been stopped.
echo ======================================================================
ping -n 3 127.0.0.1 >nul
exit
