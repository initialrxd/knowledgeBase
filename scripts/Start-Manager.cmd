@echo off
call "%~dp0Manage.cmd" start-manager %*
exit /b %errorlevel%
