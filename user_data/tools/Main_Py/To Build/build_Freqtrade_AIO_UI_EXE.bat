@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ====================================================================================
REM Freqtrade AIO UI v30 - job result safety + clear-history fix
REM - Starts in the folder where this BAT lives.
REM - Does NOT require Python 3.10 specifically.
REM - Tries installed Python versions: 3.14, 3.13, 3.12, 3.11, 3.10, then python/python3.
REM - Copies source to a temp no-space path before building to avoid "To Build" path bugs.
REM ====================================================================================

cd /d "%~dp0"

set "BUILD_CWD=%CD%"
set "APP_NAME=Freqtrade_AIO_UI"

REM ------------------------------------------------------------------------------------
REM Find source file in this BAT folder.
REM ------------------------------------------------------------------------------------
set "SCRIPT="
for %%F in (
    "Freqtrade_All_In_One_UI.py"
    "Freqtrade_AIO_UI.py"
) do (
    if not defined SCRIPT (
        if exist "%BUILD_CWD%\%%~F" set "SCRIPT=%BUILD_CWD%\%%~F"
    )
)

if not defined SCRIPT (
    echo [ERROR] Could not find AIO UI python file in:
    echo "%BUILD_CWD%"
    echo.
    echo Expected one of:
    echo   Freqtrade_All_In_One_UI.py
    echo   Freqtrade_AIO_UI.py
    echo.
    pause
    exit /b 1
)

set "OUT_DIR=%BUILD_CWD%\dist"
set "OUT_EXE=%OUT_DIR%\%APP_NAME%.exe"
set "TEMP_BUILD=%TEMP%\Freqtrade_AIO_UI_PyInstaller_%RANDOM%%RANDOM%"
set "TEMP_SRC_DIR=%TEMP_BUILD%\src"
set "TEMP_SRC=%TEMP_SRC_DIR%\Freqtrade_All_In_One_UI.py"

echo ============================================================
echo Building Freqtrade AIO UI
echo Script: "%SCRIPT%"
echo Build cwd: "%BUILD_CWD%"
echo Output: "%OUT_EXE%"
echo Temp build: "%TEMP_BUILD%"
echo ============================================================
echo.

REM ------------------------------------------------------------------------------------
REM Find usable Python. Do NOT hard-lock to py -3.10.
REM ------------------------------------------------------------------------------------
call :FindPython
if not defined PY_CMD (
    echo [ERROR] No usable Python runtime found.
    echo.
    echo Install Python, then run this BAT again.
    echo Recommended practical choices: Python 3.12 or 3.11.
    echo.
    pause
    exit /b 1
)

echo [1/5] Using Python command: %PY_CMD%
%PY_CMD% -c "import sys; print(sys.version)"
if errorlevel 1 (
    echo [ERROR] Selected Python failed to run.
    pause
    exit /b 1
)

echo.
echo [2/5] Installing / upgrading PyInstaller...
%PY_CMD% -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] PyInstaller install/upgrade failed.
    echo.
    echo Try manually:
    echo   %PY_CMD% -m pip install --upgrade pip pyinstaller
    echo.
    pause
    exit /b 1
)

echo.
echo [3/5] Cleaning old output/build folders...
if exist "%TEMP_BUILD%" rmdir /s /q "%TEMP_BUILD%" >nul 2>nul
mkdir "%TEMP_SRC_DIR%" >nul 2>nul
if exist "%OUT_EXE%" del /f /q "%OUT_EXE%" >nul 2>nul

copy /y "%SCRIPT%" "%TEMP_SRC%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy source to temp build folder.
    pause
    exit /b 1
)

echo.
echo [4/5] Building onefile windowed exe...
echo MAIN UI: no CMD window.
echo CHILD JOBS: CMD windows still launch for visible/minimized command runs.
echo.
%PY_CMD% -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%TEMP_BUILD%\dist" ^
    --workpath "%TEMP_BUILD%\build" ^
    --specpath "%TEMP_BUILD%\spec" ^
    "%TEMP_SRC%"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    echo Script used: "%SCRIPT%"
    echo Check the messages above.
    pause
    exit /b 1
)

echo.
echo [5/5] Copying exe back to local dist folder...
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%" >nul 2>nul
copy /y "%TEMP_BUILD%\dist\%APP_NAME%.exe" "%OUT_EXE%" >nul
if errorlevel 1 (
    echo [ERROR] Build succeeded but failed to copy exe to:
    echo "%OUT_EXE%"
    pause
    exit /b 1
)

echo.
echo ============================================================
echo DONE
echo EXE:
echo "%OUT_EXE%"
echo ============================================================
echo.
pause
exit /b 0


:FindPython
set "PY_CMD="

REM Prefer whatever is installed on this PC. Your other PC may have 3.14 but not 3.10.
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys" >nul 2>nul
    if !errorlevel! EQU 0 (
        set "PY_CMD=py -%%V"
        goto :eof
    )
)

python -c "import sys" >nul 2>nul
if !errorlevel! EQU 0 (
    set "PY_CMD=python"
    goto :eof
)

python3 -c "import sys" >nul 2>nul
if !errorlevel! EQU 0 (
    set "PY_CMD=python3"
    goto :eof
)

goto :eof
