@echo off
setlocal
rem Usage: quant.cmd <command> [options]. Optional QUANTMT5_PYTHON = python.exe path.
set "QM_DIR=%~dp0"
if defined QUANTMT5_PYTHON goto run
if exist "%QM_DIR%..\.venv\Scripts\python.exe" (
    set "QUANTMT5_PYTHON=%QM_DIR%..\.venv\Scripts\python.exe"
) else (
    set "QUANTMT5_PYTHON=python"
)
:run
"%QUANTMT5_PYTHON%" -I -X utf8 "%QM_DIR%run_quant.py" %*
exit /b %errorlevel%
