@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo =================================================
echo   Wuthering Waves Echo Scanner - Installer
echo =================================================
echo.

echo [1/3] Checking Python 3.11 environment...

set "PY_CMD="

py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3.11"
    goto :PY_FOUND
)

python --version >nul 2>&1
if errorlevel 1 goto :NO_PYTHON

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_FULL_VER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PY_FULL_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

if "!PY_MAJOR!"=="3" if "!PY_MINOR!"=="11" (
    set "PY_CMD=python"
    goto :PY_FOUND
)

echo [!] Found Python !PY_FULL_VER!, but PaddlePaddle requires Python 3.11
echo     Will download and install Python 3.11 automatically...
echo.
goto :INSTALL_PYTHON

:NO_PYTHON
echo [!] Python not found, will download and install Python 3.11 automatically...
echo.

:INSTALL_PYTHON
set "PY_INSTALLER=%TEMP%\python-3.11.9-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

echo [*] Downloading Python 3.11.9 installer...

curl --version >nul 2>&1
if not errorlevel 1 (
    curl -L -o "!PY_INSTALLER!" "!PY_URL!"
) else (
    certutil -urlcache -split -f "!PY_URL!" "!PY_INSTALLER!"
)

if not exist "!PY_INSTALLER!" (
    echo [ERROR] Failed to download Python. Please install Python 3.11 manually:
    echo         https://www.python.org/downloads/release/python-3119/
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [*] Installing Python 3.11.9 (silent install, please wait)...
"!PY_INSTALLER!" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1

if errorlevel 1 (
    echo [ERROR] Python installation failed. Please install manually:
    echo         https://www.python.org/downloads/release/python-3119/
    pause
    exit /b 1
)

del "!PY_INSTALLER!" >nul 2>&1

set "PATH=%LOCALAPPDATA%\Programs\Python\Python311\;%LOCALAPPDATA%\Programs\Python\Python311\Scripts\;%PATH%"

py -3.11 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3.11"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=python"
    ) else (
        echo [ERROR] Python installed but not recognized. Please close this window and run again.
        pause
        exit /b 1
    )
)

echo [OK] Python 3.11 installed successfully
echo.

:PY_FOUND
for /f "tokens=*" %%v in ('!PY_CMD! --version 2^>^&1') do echo [OK] Using %%v
echo.

echo [2/3] Upgrading pip...
!PY_CMD! -m pip install --upgrade pip
echo.

echo [3/3] Installing dependencies (includes PaddlePaddle, may take a while)...
!PY_CMD! -m pip install --user -r "%~dp0requirements.txt"

if errorlevel 1 goto :INSTALL_FAIL

echo.
echo =================================================
echo   Installation complete!
echo.
echo   Run scanner:  !PY_CMD! -m scanner
echo =================================================
goto :END

:INSTALL_FAIL
echo.
echo -------------------------------------------------
echo [HINT] Installation failed. Common fixes:
echo.
echo   1. Network issue - just re-run this script
echo.
echo   2. Permission denied - right-click install.bat
echo      and select "Run as administrator"
echo.
echo   3. Manual install:
echo      !PY_CMD! -m pip install --user -r requirements.txt
echo -------------------------------------------------

:END
echo.
pause
