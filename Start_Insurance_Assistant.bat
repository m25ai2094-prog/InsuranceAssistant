@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Insurance Assistant

pushd "%~dp0"
if errorlevel 1 goto :folder_error

if not exist "run.py" (
    echo Move this file into the extracted Insurance_Assistant folder beside run.py.
    goto :failed
)
if not exist "models\insurance-rasa.tar.gz" (
    echo The bundled model is missing. Extract the full Insurance Assistant ZIP and try again.
    goto :failed
)

rem Prefer the short Python environment used in the Windows setup.
set "INSURANCE_PYTHON=%USERPROFILE%\ia-venv\Scripts\python.exe"
if not exist "%INSURANCE_PYTHON%" set "INSURANCE_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%INSURANCE_PYTHON%" (
    echo Python environment missing. Follow the Windows setup in README.md.
    echo Expected ia-venv in your user folder or .venv inside this project.
    goto :failed
)

echo Starting the Insurance Assistant. Keep this window open.
echo The browser opens when startup is complete. Press Ctrl+C here to stop.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "& $env:INSURANCE_PYTHON -u 'run.py' | ForEach-Object { Write-Host $_; if ($_ -eq 'Insurance Assistant ready at http://127.0.0.1:8000') { Start-Process 'http://127.0.0.1:8000' } }; exit $LASTEXITCODE"
if errorlevel 1 (
    echo.
    echo Startup failed. Review the message above and check instance\rasa.log if present.
    goto :failed
)
popd
exit /b 0

:failed
echo.
pause
popd
exit /b 1

:folder_error
echo Could not open the folder that contains this launcher.
pause
exit /b 1
