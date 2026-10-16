@echo off
cd /d "%~dp0"
title CourseLM Studio - 关闭服务

echo ========================================================
echo               CourseLM Studio 关闭服务
echo ========================================================
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  set FOUND=1
  echo [正在停止] 检测到服务进程 PID: %%a
  taskkill /f /pid %%a >nul 2>&1
  if errorlevel 1 (
    echo [警告] 进程 %%a 停止失败，可能需要管理员权限。
  ) else (
    echo [成功] 已关闭服务进程 PID: %%a
  )
)

if "%FOUND%"=="0" (
  echo [提示] 未检测到正在运行的 CourseLM 服务（端口 8765 未占用）。
) else (
  echo.
  echo [完成] CourseLM 工作台服务已成功关闭。
)

echo.
echo 按任意键退出...
pause >nul
