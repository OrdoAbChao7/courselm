@echo off
cd /d "%~dp0"
title CourseLM Studio - 启动服务

echo ========================================================
echo               CourseLM Studio 启动服务
echo ========================================================
echo.

:: 1. 检查端口 8765 是否已在运行
set "RUNNING=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  set "RUNNING=1"
)

if "%RUNNING%"=="1" (
  echo [提示] CourseLM 工作台服务已在后台运行中！
  echo 正在为您打开浏览器: http://127.0.0.1:8765
  start http://127.0.0.1:8765
  echo.
  echo 如需关闭服务，请直接双击运行 [关闭CourseLM工作台.bat]
  echo.
  pause
  exit /b 0
)

:: 2. 选择 Python 解释器 (优先使用虚拟环境 .venv)
set "PY_EXE="
if exist ".venv\Scripts\python.exe" (
  set "PY_EXE=.venv\Scripts\python.exe"
) else (
  where python >nul 2>&1
  if %ERRORLEVEL% equ 0 (
    set "PY_EXE=python"
  )
)

if "%PY_EXE%"=="" (
  echo [错误] 未找到 Python 环境，请确认已安装 Python 或创建了 .venv 虚拟环境。
  pause
  exit /b 1
)

echo [信息] 使用 Python 解释器: %PY_EXE%
echo [信息] 正在启动 CourseLM Studio (http://127.0.0.1:8765)...
echo.
echo 提示：
echo - 浏览器将自动打开工作台页面。
echo - 保持此窗口打开可查看实时日志；关闭服务请双击 [关闭CourseLM工作台.bat]。
echo ========================================================
echo.

"%PY_EXE%" -m studio.server
if errorlevel 1 (
  echo.
  echo [错误] 启动异常退出。如果缺少依赖，请在终端执行：pip install -e ".[dev]"
  pause
)
