$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Spec = Join-Path $ProjectRoot "CourseLM.spec"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$StageDir = Join-Path $ReleaseRoot "CourseLM"
$ZipPath = Join-Path $ReleaseRoot "CourseLM-portable-windows-x64.zip"

if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    throw "Python runtime not found. Use the project .venv or install Python."
}

Write-Host "== 1. Run tests =="
& $Python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; portable build stopped." }

Write-Host "== 2. Clean old build output =="
foreach ($Target in @($DistDir, $BuildDir, $ReleaseRoot)) {
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
}

Write-Host "== 3. Build PyInstaller onedir =="
& $Python -m PyInstaller --noconfirm --clean $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$PyInstallerApp = Join-Path $DistDir "CourseLM"
if (-not (Test-Path -LiteralPath (Join-Path $PyInstallerApp "CourseLM.exe"))) {
    throw "PyInstaller did not create CourseLM.exe."
}

Write-Host "== 4. Assemble portable directory =="
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $StageDir "config") -Force | Out-Null
Copy-Item -Path (Join-Path $PyInstallerApp "*") -Destination $StageDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\config.portable.yaml") -Destination (Join-Path $StageDir "config\config.yaml")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\prompts.yaml") -Destination (Join-Path $StageDir "config\prompts.yaml")
$Instructions = Get-ChildItem -LiteralPath $ProjectRoot -File |
    Where-Object { $_.Extension -eq ".txt" } |
    Select-Object -First 1
if (-not $Instructions) { throw "Portable instructions file not found." }
$InstructionsName = ([char]0x4f7f) + ([char]0x7528) + ([char]0x8bf4) + ([char]0x660e) + ".txt"
Copy-Item -LiteralPath $Instructions.FullName -Destination (Join-Path $StageDir $InstructionsName)

foreach ($Directory in @("courses", "output", "logs", "user_data")) {
    New-Item -ItemType Directory -Path (Join-Path $StageDir $Directory) -Force | Out-Null
}

Write-Host "== 5. Privacy and browser dependency checks =="
$Sensitive = Get-ChildItem -LiteralPath $StageDir -File -Recurse | Where-Object {
    (
        $_.Name -match '^\.env$|\.key$|\.pem$|storage_state|cookies?'
    ) -and $_.FullName -notmatch '\\certifi\\cacert\.pem$'
}
if ($Sensitive) {
    $Names = ($Sensitive | Select-Object -ExpandProperty FullName) -join ([Environment]::NewLine)
    throw "Sensitive files found; build stopped:$([Environment]::NewLine)$Names"
}

$UserDataFiles = @(Get-ChildItem -LiteralPath (Join-Path $StageDir "user_data") -Force)
if ($UserDataFiles.Count -gt 0) { throw "Portable user_data must be empty." }

$BrowserNames = Get-ChildItem -LiteralPath $StageDir -File -Recurse | Where-Object {
    $_.Name -match 'chromium|firefox|webkit|headless_shell|ffmpeg'
}
if ($BrowserNames) {
    $Names = ($BrowserNames | Select-Object -ExpandProperty FullName) -join ([Environment]::NewLine)
    throw "Browser files that must not be bundled found:$([Environment]::NewLine)$Names"
}

Write-Host "== 6. Create ZIP =="
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = [System.IO.Compression.ZipFile]::Open(
    $ZipPath, [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    Get-ChildItem -LiteralPath $StageDir -Directory -Recurse | ForEach-Object {
        $Relative = $_.FullName.Substring($StageDir.Length).TrimStart("\").Replace("\", "/")
        $Archive.CreateEntry($Relative + "/") | Out-Null
    }
    Get-ChildItem -LiteralPath $StageDir -File -Recurse | ForEach-Object {
        $Relative = $_.FullName.Substring($StageDir.Length).TrimStart("\").Replace("\", "/")
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $Archive, $_.FullName, $Relative,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
} finally {
    $Archive.Dispose()
}

function Get-DirectoryBytes([string] $Path) {
    $Measure = Get-ChildItem -LiteralPath $Path -File -Recurse | Measure-Object -Property Length -Sum
    return [int64]$Measure.Sum
}

Write-Host "== 7. Size report =="
foreach ($Directory in @("CourseLM.exe", "_internal", "config", "courses", "output", "logs", "user_data")) {
    $Path = Join-Path $StageDir $Directory
    if (Test-Path -LiteralPath $Path -PathType Leaf) { $Bytes = (Get-Item -LiteralPath $Path).Length }
    else { $Bytes = Get-DirectoryBytes $Path }
    Write-Host ("{0,-18} {1,8:N2} MB" -f $Directory, ($Bytes / 1MB))
}

$StageBytes = Get-DirectoryBytes $StageDir
$ZipBytes = (Get-Item -LiteralPath $ZipPath).Length
Write-Host ("Unpacked directory {0,8:N2} MB" -f ($StageBytes / 1MB))
Write-Host ("Final ZIP          {0,8:N2} MB" -f ($ZipBytes / 1MB))
Write-Host "Top 20 files:"
Get-ChildItem -LiteralPath $StageDir -File -Recurse |
    Sort-Object Length -Descending |
    Select-Object -First 20 FullName, Length |
    Format-Table -AutoSize

Write-Host "Portable build complete: $ZipPath"
