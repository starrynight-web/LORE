@echo off
title Stop LORE Enterprise
echo ======================================================================
echo   Stopping LORE Enterprise Background Services...
echo ======================================================================

:: Kill processes listening on port 8000 (Backend)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do (
    echo Stopping Backend service on port 8000 (PID %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

:: Kill processes listening on port 8001 (MCP Server)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8001" ^| find "LISTENING"') do (
    echo Stopping MCP Server service on port 8001 (PID %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

:: Kill processes listening on port 3000 (Frontend)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":3000" ^| find "LISTENING"') do (
    echo Stopping Frontend service on port 3000 (PID %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo ======================================================================
echo   All LORE services have been stopped.
echo ======================================================================
ping -n 3 127.0.0.1 >nul
exit
