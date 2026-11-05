@echo off
call "%~dp0Manage.cmd" stop-knowledge %*
exit /b %errorlevel%
