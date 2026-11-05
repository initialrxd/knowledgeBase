@echo off
call "%~dp0Manage.cmd" stop-manager %*
exit /b %errorlevel%
