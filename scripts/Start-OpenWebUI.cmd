@echo off
call "%~dp0Manage.cmd" start-openwebui %*
exit /b %errorlevel%
