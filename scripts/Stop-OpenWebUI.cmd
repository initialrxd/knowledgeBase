@echo off
call "%~dp0OpenWebUI.cmd" stop %*
exit /b %errorlevel%
