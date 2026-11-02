@echo off
call "%~dp0Manage.cmd" stop-all %*
exit /b %errorlevel%
