@echo off
:: ==============================================================================
:: LEVIX PRODUCTION SERVER BOOT ENGINE (LOCAL WINDOWS TESTING)
:: Domain Target: https://levixapp.in
:: Author: Senior Publisher Developer
:: ==============================================================================

echo ====================================================================
echo           L E V I X   T E C H N O L O G I E S   L A U N C H E R    
echo ====================================================================

:: 1. Load local environment configurations if they exist
if exist "config\.env" (
    echo [LAUNCH] Loading configurations from config\.env...
    for /f "usebackq tokens=*" %%i in ("config\.env") do (
        echo %%i | findstr /r "^#" >nul
        if errorlevel 1 (
            set %%i
        )
    )
) else if exist ".env" (
    echo [LAUNCH] Loading configurations from .env...
    for /f "usebackq tokens=*" %%i in (".env") do (
        echo %%i | findstr /r "^#" >nul
        if errorlevel 1 (
            set %%i
        )
    )
) else (
    echo [LAUNCH] No local .env file found. Running on system defaults.
)

:: 2. Set Server Ports & Defaults
if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=127.0.0.1
if "%WORKERS%"=="" set WORKERS=2

echo [LAUNCH] Target domain: https://levixapp.in
echo [LAUNCH] Active worker processes: %WORKERS%
echo [LAUNCH] Binding to local interface: http://%HOST%:%PORT%

:: 3. Run high-performance production server on Windows
echo [LAUNCH] Starting Uvicorn on Windows...
uvicorn app.main:app --host %HOST% --port %PORT% --workers %WORKERS% --proxy-headers --forwarded-allow-ips="*" --log-level info
