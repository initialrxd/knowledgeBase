@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
if exist "%~dp0..\.venv\Scripts\python.exe" goto project_python
if /i "%~1"=="install" goto find_python
>&2 echo Project Python environment is missing. Run scripts\Install.cmd first.
exit /b 1

:project_python
"%~dp0..\.venv\Scripts\python.exe" -X utf8 "%~dp0manage.py" %*
exit /b %errorlevel%

:find_python
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python311
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python312
python -c "import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))" >nul 2>&1
if not errorlevel 1 goto python_path
>&2 echo Python 3.11 or 3.12 is required. Install Python with the py launcher or add it to PATH.
exit /b 1

:python311
py -3.11 -X utf8 "%~dp0manage.py" %*
exit /b %errorlevel%

:python312
py -3.12 -X utf8 "%~dp0manage.py" %*
exit /b %errorlevel%

:python_path
python -X utf8 "%~dp0manage.py" %*
exit /b %errorlevel%
