@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =====================================================================================
REM Build Freqtrade All-In-One UI into one Windows .exe using PyInstaller
REM - Starts from this BAT folder
REM - Auto-detects Python
REM - Builds onefile/windowed exe
REM - Uses a temp no-space build folder so paths like "To Build" do not break
REM =====================================================================================

cd /d "%~dp0"

set "APP_NAME=Freqtrade_AIO_UI"
set "SRC="

for %%F in (
    "Freqtrade_All_In_One_UI.py"
    "Freqtrade_AIO_UI.py"
) do (
    if not defined SRC if exist "%%~F" set "SRC=%%~fF"
)

if not defined SRC (
    echo [ERROR] Could not find AIO Python source next to this BAT.
    echo Expected one of:
    echo   Freqtrade_All_In_One_UI.py
    echo   Freqtrade_AIO_UI.py
    pause
    exit /b 1
)

set "OUT_DIR=%CD%\dist"
set "TEMP_ROOT=%TEMP%\Freqtrade_AIO_UI_PyInstaller_%RANDOM%%RANDOM%"
set "TEMP_SRC_DIR=%TEMP_ROOT%\src"
set "TEMP_BUILD_DIR=%TEMP_ROOT%\build"
set "TEMP_DIST_DIR=%TEMP_ROOT%\dist"
set "TEMP_SPEC_DIR=%TEMP_ROOT%\spec"
set "TEMP_SRC=%TEMP_SRC_DIR%\Freqtrade_All_In_One_UI.py"

if exist "%TEMP_ROOT%" rmdir /s /q "%TEMP_ROOT%" >nul 2>nul
mkdir "%TEMP_SRC_DIR%" "%TEMP_BUILD_DIR%" "%TEMP_DIST_DIR%" "%TEMP_SPEC_DIR%" >nul 2>nul
copy /y "%SRC%" "%TEMP_SRC%" >nul

call :pick_python
if not defined PY_CMD (
    echo [ERROR] No usable Python found. Install Python 3.10+ or fix py launcher.
    pause
    exit /b 1
)

echo ============================================================
echo Building Freqtrade AIO UI
echo Script: "%SRC%"
echo Build cwd: "%CD%"
echo Output: "%OUT_DIR%\%APP_NAME%.exe"
echo Temp build: "%TEMP_ROOT%"
echo Python: %PY_CMD%
echo ============================================================
echo.

echo [1/5] Checking Python...
%PY_CMD% -c "import sys; print(sys.version)" || goto :fail

echo [2/5] Installing / upgrading PyInstaller...
%PY_CMD% -m pip install --upgrade pip pyinstaller || goto :fail

echo [3/5] Cleaning old output...
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%" >nul 2>nul

echo [4/5] Building onefile windowed exe...
echo MAIN UI: no CMD window.
echo CHILD JOBS: CMD windows still launch for visible/minimized command runs.
%PY_CMD% -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%TEMP_DIST_DIR%" ^
    --workpath "%TEMP_BUILD_DIR%" ^
    --specpath "%TEMP_SPEC_DIR%" ^
    "%TEMP_SRC%" || goto :fail

if not exist "%TEMP_DIST_DIR%\%APP_NAME%.exe" goto :fail
copy /y "%TEMP_DIST_DIR%\%APP_NAME%.exe" "%OUT_DIR%\%APP_NAME%.exe" >nul || goto :fail

echo [5/5] Cleanup temp build...
rmdir /s /q "%TEMP_ROOT%" >nul 2>nul

echo.
echo DONE.
echo EXE: "%OUT_DIR%\%APP_NAME%.exe"
start "" "%OUT_DIR%"
pause
exit /b 0

:pick_python
for %%P in ("py -3.14" "py -3.13" "py -3.12" "py -3.11" "py -3.10" "python" "python3") do (
    if not defined PY_CMD (
        %%~P -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY_CMD=%%~P"
    )
)
exit /b 0

:fail
echo.
echo [ERROR] Build failed.
echo Script used: "%SRC%"
echo Check the messages above.
if exist "%TEMP_ROOT%" echo Temp build kept/attempted at: "%TEMP_ROOT%"
pause
exit /b 1
