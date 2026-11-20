@echo off
setlocal enabledelayedexpansion
title LORE Enterprise Launcher
cd /d "%~dp0"

echo ======================================================================
echo   LORE Enterprise - Turnkey Unified Application Launcher
echo ======================================================================
echo.

:: 1. Verify Python availability or discover standard installations
echo [*] Checking Python environment...
where python >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts;!PATH!"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;!PATH!"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;!PATH!"
    ) else if exist "C:\Python314\python.exe" (
        set "PATH=C:\Python314;C:\Python314\Scripts;!PATH!"
    ) else if exist "C:\Python312\python.exe" (
        set "PATH=C:\Python312;C:\Python312\Scripts;!PATH!"
    )
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ======================================================================
    echo   [AUTO-SETUP] Python was not detected on this system.
    echo   Downloading and installing official Python 3.12 (silent setup)...
    echo   (This is an automated one-time setup for new Windows devices)
    echo ======================================================================
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe', '$env:TEMP\python_setup.exe')"
    if exist "%TEMP%\python_setup.exe" (
        echo [*] Installing Python 3.12 silently...
        "%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 SimpleInstall=1
        del "%TEMP%\python_setup.exe" >nul 2>&1
        for /f "tokens=*" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')"') do set "PATH=%%p;!PATH!"
        if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
            set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;!PATH!"
        )
    )
    where python >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Python auto-installation could not be completed.
        echo Please download and install Python manually from: https://www.python.org/downloads/
        echo (IMPORTANT: Make sure to check the box 'Add python.exe to PATH')
        echo.
        pause
        exit /b 1
    )
    echo [OK] Python installed and registered successfully.
) else (
    echo [OK] Python is available.
)

:: 2. Verify Node.js / npm availability or discover standard installations
echo [*] Checking Node.js environment...
where node >nul 2>&1
if %errorlevel% neq 0 (
    if exist "C:\Program Files\nodejs\node.exe" (
        set "PATH=C:\Program Files\nodejs;%APPDATA%\npm;!PATH!"
    ) else if exist "C:\Program Files (x86)\nodejs\node.exe" (
        set "PATH=C:\Program Files (x86)\nodejs;%APPDATA%\npm;!PATH!"
    )
)

where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo ======================================================================
    echo   [AUTO-SETUP] Node.js was not detected on this system.
    echo   Downloading and installing official Node.js LTS (silent setup)...
    echo   (This is an automated one-time setup for new Windows devices)
    echo ======================================================================
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://nodejs.org/dist/v20.18.1/node-v20.18.1-x64.msi', '$env:TEMP\node_setup.msi')"
    if exist "%TEMP%\node_setup.msi" (
        echo [*] Installing Node.js LTS silently...
        msiexec /i "%TEMP%\node_setup.msi" /qn
        del "%TEMP%\node_setup.msi" >nul 2>&1
        for /f "tokens=*" %%p in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')"') do set "PATH=%%p;!PATH!"
        if exist "C:\Program Files\nodejs\node.exe" (
            set "PATH=C:\Program Files\nodejs;%APPDATA%\npm;!PATH!"
        )
    )
    where npm >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Node.js auto-installation could not be completed.
        echo Please download and install Node.js manually from: https://nodejs.org
        echo.
        pause
        exit /b 1
    )
    echo [OK] Node.js and npm installed and registered successfully.
) else (
    echo [OK] Node.js is available.
)

:: 2.5 Auto-Setup for Fresh Devices: Verify Python packages
echo [*] Checking Python dependencies...
python -c "import django, rest_framework, corsheaders, pydantic, qdrant_client" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ======================================================================
    echo   [SETUP] Core Python dependencies missing or incomplete.
    echo   Installing packages from backend\requirements.txt...
    echo   (This is an automated one-time setup for fresh machines)
    echo ======================================================================
    python -m pip install --upgrade pip
    python -m pip install -r "%~dp0backend\requirements.txt"
    if !errorlevel! neq 0 (
        echo [*] Retrying core runtime dependencies installation...
        python -m pip install django djangorestframework djangorestframework-simplejwt django-cors-headers pydantic qdrant-client requests sentence-transformers
    )
    python -c "import django, rest_framework, corsheaders, pydantic" >nul 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Failed to install Python dependencies.
        echo Please check your internet connection or install manually with:
        echo   pip install -r backend\requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo [OK] Python dependencies installed successfully.
) else (
    echo [OK] Python dependencies verified.
)

:: 2.6 Auto-Setup for Fresh Devices: Initialize Database & Seed Demo Data
echo [*] Checking database schema ^& enterprise seed data...
cd /d "%~dp0backend"
python manage.py migrate --noinput
if %errorlevel% neq 0 (
    echo [ERROR] Django migrations failed to execute.
    pause
    exit /b 1
)
python manage.py seed_enterprise_demo >nul 2>&1
cd /d "%~dp0"
echo [OK] Database schema and enterprise demo data ready.

:: 2.7 Auto-Setup for Fresh Devices: Install frontend node_modules if Next.js CLI is missing
if not exist "%~dp0frontend\node_modules\.bin\next.cmd" (
    echo.
    echo ======================================================================
    echo   [SETUP] Frontend dependencies (Next.js) missing or incomplete.
    echo   Running 'npm install' in frontend directory...
    echo   (This is an automated one-time setup for fresh machines - please wait)
    echo ======================================================================
    cd /d "%~dp0frontend"
    call npm install
    cd /d "%~dp0"
    if not exist "%~dp0frontend\node_modules\.bin\next.cmd" (
        echo.
        echo [ERROR] 'npm install' failed to install Next.js CLI into frontend\node_modules.
        echo Please run manually to inspect errors:
        echo   cd frontend ^&^& npm install
        echo.
        pause
        exit /b 1
    )
    echo [OK] Frontend dependencies installed successfully.
) else (
    echo [OK] Frontend dependencies verified.
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

:: 6. Wait for servers to initialize and bind ports before launching browser
echo [4/4] Waiting for backend (8000) and frontend (3000) to initialize...
set /a WAIT_COUNT=0
:WAIT_SERVERS
netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    set /a WAIT_COUNT+=1
    if !WAIT_COUNT! leq 35 (
        ping -n 2 127.0.0.1 >nul
        goto :WAIT_SERVERS
    )
    echo [WARNING] Servers took longer than expected to bind ports. Opening browser anyway...
) else (
    echo [OK] All ports are live and listening!
)

:: 7. Launch Application Window (Edge App Mode or default browser)
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
echo   Live Docs:     http://localhost:3000/docs
echo   REST API:      http://127.0.0.1:8000/api/v1
echo   MCP Server:    http://127.0.0.1:8001/mcp
echo   Django Admin:  http://127.0.0.1:8000/admin
echo.
echo   Demo Login Credentials:
echo     Admin:       admin@northstar.demo    / Northstar2026!
echo     Reviewer:    reviewer@northstar.demo / Northstar2026!
echo     Viewer:      viewer@northstar.demo   / Northstar2026!
echo.
echo   Judge / Evaluator Passkey for Docs:
echo     Passkey:     LORE-JUDGE-2026
echo ----------------------------------------------------------------------
echo   To shut down all servers, run Stop_LORE.bat
echo ======================================================================
echo.
ping -n 3 127.0.0.1 >nul
exit
