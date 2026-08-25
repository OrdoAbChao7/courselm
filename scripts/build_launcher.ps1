$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到项目虚拟环境：$Python"
}

& $Python -m pip install pyinstaller
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name CourseLM `
    (Join-Path $ProjectRoot "launcher.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

Write-Host "构建完成：$(Join-Path $ProjectRoot 'dist\CourseLM.exe')"
