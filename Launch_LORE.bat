@echo off
setlocal
title LORE Enterprise Launcher
cd /d "%~dp0"

echo ======================================================================
echo   LORE Enterprise - Unified Application Launcher
echo ======================================================================
echo.

:: 1. Verify Python availability
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.12 or 3.13 and ensure 'Add to PATH' is checked.
    echo.
    pause
    exit /b 1
)

:: 2. Verify Node / npm availability
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js / npm is not installed or not in PATH.
    echo Please install Node.js from https://nodejs.org
    echo.
    pause
    exit /b 1
)

:: 3. Launch Backend in its own titled window if not already listening
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/4] Backend is already running on port 8000.
) else (
    echo [1/4] Starting LORE Governance Engine on port 8000...
    start "LORE Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && echo Starting LORE Backend API Server on 127.0.0.1:8000... && python manage.py runserver 127.0.0.1:8000 --noreload"
)

:: 4. Launch MCP Server (Port 8001) in its own titled window if not already listening
netstat -ano | findstr /R /C:":8001 .*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [2/4] MCP Server is already running on port 8001.
) else (
    echo [2/4] Starting LORE MCP Streamable HTTP Server on port 8001...
    start "LORE MCP Server (Port 8001)" cmd /k "cd /d "%~dp0backend" && echo Starting LORE MCP Streamable HTTP Server on 0.0.0.0:8001... && python mcp_server.py --transport http --port 8001"
)

:: 5. Launch Frontend in its own titled window if not already listening
netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [3/4] Frontend is already running on port 3000.
) else (
    echo [3/4] Starting LORE Knowledge Grid Interface on port 3000...
    if exist "%~dp0frontend\.next" (
        start "LORE Frontend (Port 3000)" cmd /k "cd /d "%~dp0frontend" && echo Starting LORE Next.js Interface on port 3000... && npm start"
    ) else (
        start "LORE Frontend (Port 3000)" cmd /k "cd /d "%~dp0frontend" && echo Starting LORE Next.js Interface on port 3000... && npm run dev"
    )
)

:: 6. Wait for servers to initialize
echo [4/4] Waiting for servers to bind ports...
ping -n 5 127.0.0.1 >nul

:: 6. Launch Application Window (Edge App Mode or default browser)
echo.
echo Launching LORE in standalone application window...
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://localhost:3000 --window-size=1360,860
) else if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app=http://localhost:3000 --window-size=1360,860
) else if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:3000 --window-size=1360,860
) else (
    start "" http://localhost:3000
)

echo.
echo ======================================================================
echo   LORE Enterprise is running!
echo ----------------------------------------------------------------------
echo   Web UI:        http://localhost:3000
echo   REST API:      http://127.0.0.1:8000/api/v1
echo   Django Admin:  http://127.0.0.1:8000/admin
echo.
echo   Demo Login Credentials:
echo     Admin:    admin@northstar.demo    / Northstar2026!
echo     Reviewer: reviewer@northstar.demo / Northstar2026!
echo     Viewer:   viewer@northstar.demo   / Northstar2026!
echo ----------------------------------------------------------------------
echo   To shut down both servers, run Stop_LORE.bat
echo ======================================================================
echo.
ping -n 3 127.0.0.1 >nul
exit
