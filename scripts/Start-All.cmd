@echo off
call "%~dp0Manage.cmd" start-all %*
exit /b %errorlevel%
