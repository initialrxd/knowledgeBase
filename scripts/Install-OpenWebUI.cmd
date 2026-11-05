@echo off
call "%~dp0OpenWebUI.cmd" install %*
exit /b %errorlevel%
