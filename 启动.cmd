@echo off
chcp 65001 >nul
setlocal
set "SF_ROOT=%~dp0"
set "SF_PYTHON="
if defined STOCKFOLD_PYTHON if exist "%STOCKFOLD_PYTHON%" set "SF_PYTHON=%STOCKFOLD_PYTHON%"
if not defined SF_PYTHON if exist "%~dp0.runtime\python.exe" set "SF_PYTHON=%~dp0.runtime\python.exe"
if not defined SF_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "SF_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined SF_PYTHON for /f "delims=" %%P in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined SF_PYTHON set "SF_PYTHON=%%P"
if not defined SF_PYTHON (
  echo 未找到 Python。请安装 Python 3.12 或设置 STOCKFOLD_PYTHON 为 python.exe 完整路径。
  pause
  exit /b 1
)
if not exist "%~dp0data" mkdir "%~dp0data"
powershell.exe -NoProfile -Command "Start-Process -FilePath $env:SF_PYTHON -ArgumentList @('-m','app.server') -WorkingDirectory $env:SF_ROOT -WindowStyle Hidden"
endlocal
