@echo off
cd /d "%~dp0"
title CourseLM Studio - 服务控制面板

:menu
cls
echo ========================================================
echo             CourseLM Studio 服务控制面板
echo ========================================================
echo.

set "PID_LIST="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  set "PID_LIST=%%a"
)

if not "%PID_LIST%"=="" (
  echo 当前服务状态: [正在运行]  (端口: 8765, 进程 PID: %PID_LIST%)
  echo 访问地址:     http://127.0.0.1:8765
) else (
  echo 当前服务状态: [未运行]
)

echo.
echo --------------------------------------------------------
echo   [1] 启动服务 (在后台静默运行)
echo   [2] 启动服务 (在前台运行 / 实时查看日志)
echo   [3] 关闭服务
echo   [4] 重启服务
echo   [5] 打开浏览器访问工作台
echo   [0] 退出
echo --------------------------------------------------------
echo.
set /p choice=请输入选项编号 [0-5]: 

if "%choice%"=="1" goto start_bg
if "%choice%"=="2" goto start_fg
if "%choice%"=="3" goto stop
if "%choice%"=="4" goto restart
if "%choice%"=="5" goto open_browser
if "%choice%"=="0" exit /b 0

echo [提示] 无效选项，请重新输入。
ping -n 2 127.0.0.1 >nul
goto menu

:get_py
set "PY_EXE="
if exist ".venv\Scripts\python.exe" (
  set "PY_EXE=.venv\Scripts\python.exe"
) else (
  set "PY_EXE=python"
)
goto :eof

:start_bg
call :get_py
if not "%PID_LIST%"=="" (
  echo.
  echo [提示] 服务已在运行中，无需重复启动。
  ping -n 2 127.0.0.1 >nul
  goto menu
)
echo.
echo 正在后台启动 CourseLM Studio...
start "CourseLM Studio Server" /min "%PY_EXE%" -m studio.server
ping -n 3 127.0.0.1 >nul
start http://127.0.0.1:8765
goto menu

:start_fg
call :get_py
if not "%PID_LIST%"=="" (
  echo.
  echo [提示] 服务已在运行中，请先关闭现有服务再进行前台调试。
  pause
  goto menu
)
echo.
echo 正在前台启动服务，按 Ctrl+C 可停止...
echo.
"%PY_EXE%" -m studio.server
pause
goto menu

:stop
echo.
echo 正在停止 8765 端口服务...
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  taskkill /f /pid %%a >nul 2>&1
  echo [成功] 已关闭服务进程 PID: %%a
)
if "%FOUND%"=="0" (
  echo [提示] 服务尚未运行。
)
ping -n 2 127.0.0.1 >nul
goto menu

:restart
echo.
echo 正在重启服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  taskkill /f /pid %%a >nul 2>&1
)
ping -n 2 127.0.0.1 >nul
call :get_py
start "CourseLM Studio Server" /min "%PY_EXE%" -m studio.server
ping -n 3 127.0.0.1 >nul
echo [成功] 服务已重启。
ping -n 2 127.0.0.1 >nul
goto menu

:open_browser
echo.
echo 正在打开工作台网页...
start http://127.0.0.1:8765
goto menu
