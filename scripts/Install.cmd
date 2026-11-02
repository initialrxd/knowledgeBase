@echo off
call "%~dp0Manage.cmd" install %*
exit /b %errorlevel%
