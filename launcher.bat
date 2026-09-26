@echo off
setlocal EnableDelayedExpansion
title HighSpeed - launcher
cd /d "%~dp0"

rem ============================================================================
rem  HighSpeed launcher - creates the venv, installs dependencies, builds the UI,
rem  migrates + seeds the 62 synthetic datasets, then serves API and SPA on one
rem  port. The System One engine warms up in the background and auto-runs the
rem  first use cases so the dashboard is alive on first open.
rem
rem  Overrides (set before running, or edit here):
rem    PORT=8010  HOST=127.0.0.1  SEED=20260926
rem    SYSTEMONE_PROFILE=gpu-nli|cpu-nli|gpu-en|cpu-en
rem    SYSTEMONE_MODELS_DIR=<path to the downloaded openjev model folder>
rem    FASTHS_AUTORUN=2   (use cases auto-decided after warm-up; 0 disables)
rem    SKIP_BROWSER=1     (do not auto-open the browser)
rem ============================================================================

if "%PORT%"=="" set "PORT=8010"
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%VENV%"=="" set "VENV=.venv"
if "%SEED%"=="" set "SEED=20260926"
set "ROOT=%CD%"
if "%SYSTEMONE_MODELS_DIR%"=="" set "SYSTEMONE_MODELS_DIR=%ROOT%\models"
if "%FASTHS_AUTORUN%"=="" set "FASTHS_AUTORUN=2"
set "PY=%ROOT%\%VENV%\Scripts\python.exe"
set "TMP_OUT=%TEMP%\highspeed_launcher.out"

echo.
echo  ============================================================
echo   HighSpeed - System One decision showcase (62 use cases)
echo  ============================================================
echo.

rem ---------------------------------------------------------------- python ----
where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python was not found on PATH. Install Python 3.11+ and re-run.
  pause
  exit /b 1
)

rem ------------------------------------------------------------------ venv ----
if not exist "%PY%" (
  echo [1/6] Creating virtual environment in %VENV%
  echo        ^(--system-site-packages reuses the CUDA build of torch instead of
  echo        re-downloading ~2.5 GB^)
  python -m venv --system-site-packages "%ROOT%\%VENV%"
  if errorlevel 1 (
    echo [X] venv creation failed.
    pause
    exit /b 1
  )
) else (
  echo [1/6] Virtual environment found: %VENV%
)

if not exist "%PY%" (
  echo [X] venv python not found at %PY%
  pause
  exit /b 1
)

rem ------------------------------------------------------- dependencies -----
if exist "%ROOT%\%VENV%\.deps-ok" (
  echo [2/6] Dependencies already installed ^(delete %VENV%\.deps-ok to force^)
) else (
  echo [2/6] Installing Python dependencies from requirements.txt
  "%PY%" -m pip install --quiet --disable-pip-version-check -r "%ROOT%\requirements.txt"
  if errorlevel 1 (
    echo [X] pip install failed.
    pause
    exit /b 1
  )
  echo ok> "%ROOT%\%VENV%\.deps-ok"
)

rem ------------------------------------------------------------- engine -----
echo [3/6] Checking the System One decision engine
if "%SYSTEMONE_PROFILE%"=="" (
  set "CUDA="
  "%PY%" -c "import torch;print(torch.cuda.is_available())" > "%TMP_OUT%" 2>nul
  if exist "%TMP_OUT%" set /p CUDA=<"%TMP_OUT%"
  if "!CUDA!"=="True" (
    set "SYSTEMONE_PROFILE=gpu-nli"
    echo        CUDA detected - profile gpu-nli ^(openjev NLI 0.8B on GPU^)
  ) else (
    set "SYSTEMONE_PROFILE=cpu-nli"
    echo        No CUDA GPU - profile cpu-nli ^(slower, same contract^)
  )
) else (
  echo        profile %SYSTEMONE_PROFILE% ^(from environment^)
)
if not exist "%SYSTEMONE_MODELS_DIR%" (
  echo [!] WARNING: models folder %SYSTEMONE_MODELS_DIR% not found.
  echo     Download the openjev NLI weights there first ^(see models\README.md^);
  echo     runs will report an engine error until the models exist.
) else if not exist "%SYSTEMONE_MODELS_DIR%\openjev\qwen3.5-0.8b-nli-v2s-long" (
  echo [!] WARNING: %SYSTEMONE_MODELS_DIR% exists but has no
  echo     openjev\qwen3.5-0.8b-nli-v2s-long folder; runs will error until the
  echo     weights are downloaded ^(see models\README.md^).
)

rem -------------------------------------------------------------- frontend --
if exist "%ROOT%\frontend\dist\index.html" (
  echo [4/6] Frontend bundle present ^(delete frontend\dist to rebuild^)
) else (
  echo [4/6] Building the React frontend
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [!] npm not found - skipping the UI build.
    echo     The API will still run at http://%HOST%:%PORT%/api/stats
  ) else (
    pushd "%ROOT%\frontend"
    if not exist node_modules (
      call npm install --no-fund --no-audit
      if errorlevel 1 ( popd & echo [X] npm install failed. & pause & exit /b 1 )
    )
    call npm run build
    if errorlevel 1 ( popd & echo [X] frontend build failed. & pause & exit /b 1 )
    popd
  )
)

rem -------------------------------------------------------------- database --
echo [5/6] Preparing the database
"%PY%" "%ROOT%\backend\manage.py" migrate --noinput
if errorlevel 1 (
  echo [X] migrate failed ^(see the Django output above^).
  pause
  exit /b 1
)

rem ------------------------------------------------------------------ seed --
set "RECORDS="
"%PY%" "%ROOT%\backend\manage.py" shell -c "from showcase.models import Record;print(Record.objects.count())" > "%TMP_OUT%" 2>nul
if exist "%TMP_OUT%" set /p RECORDS=<"%TMP_OUT%"
echo [6/6] Datasets: %RECORDS% record^(s^) present
if "%RECORDS%"=="0" (
   echo        Seeding 62 synthetic datasets, ~1,980 records ^(seed %SEED%^)
   "%PY%" "%ROOT%\backend\manage.py" seed_demo --seed %SEED% --reset
   if errorlevel 1 ( echo [X] seeding failed. & pause & exit /b 1 )
) else if "%RECORDS%"=="" (
   echo        Seeding 62 synthetic datasets, ~1,980 records ^(seed %SEED%^)
   "%PY%" "%ROOT%\backend\manage.py" seed_demo --seed %SEED% --reset
   if errorlevel 1 ( echo [X] seeding failed. & pause & exit /b 1 )
) else (
   echo        Reusing the existing datasets ^("Reseed datasets" button rebuilds them^)
)

rem ----------------------------------------------------------------- serve --
echo.
echo      Showcase  http://%HOST%:%PORT%/
echo      API       http://%HOST%:%PORT%/api/stats
echo      Admin     http://%HOST%:%PORT%/admin/
echo.
echo      The decision engine warms up in the background (~10-30 s GPU / ~60 s CPU,
echo      once), then auto-runs the first %FASTHS_AUTORUN% use case^(s^) so the
echo      dashboard shows live measured numbers. "Run full sweep" decides all
echo      ~1,980 records ^(background, roughly an hour on GPU^).
echo      Press Ctrl+C to stop.
echo.

if not "%SKIP_BROWSER%"=="1" start "" "http://%HOST%:%PORT%/"

set "DJANGO_SETTINGS_MODULE=highspeed.settings"
set "PYTHONPATH=%ROOT%\backend"
set "RUN_MAIN=true"
"%PY%" "%ROOT%\backend\manage.py" runserver %HOST%:%PORT% --noreload

endlocal
