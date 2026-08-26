# -*- mode: python ; coding: utf-8 -*-
"""CourseLM Portable onedir build: external config/data, no browser binaries."""

from pathlib import Path

project_root = Path(SPECPATH)
hiddenimports = [
    "main",
    "modules.browser_check",
    "modules.config",
    "modules.file_manager",
    "modules.logging_setup",
    "modules.markdown_generator",
    "modules.markdown_sanitizer",
    "modules.network",
    "modules.notebooklm",
    "modules.obsidian_sync",
    "modules.path_manager",
    "modules.prompt_runner",
    "modules.prompts",
]

a = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "coverage", "mypy", "ruff", "black", "IPython", "jupyter", "notebooklm.tests"],
    noarchive=False,
)

# Playwright's hook also collects CLI dashboards, trace viewers, install
# scripts and type declarations. Python browser control only needs the driver
# core, so remove those optional assets without removing the driver itself.
_optional_playwright_prefixes = (
    "playwright/driver/package/bin/",
    "playwright/driver/package/lib/vite/",
    "playwright/driver/package/lib/tools/",
    "playwright/driver/package/lib/server/chromium/",
    "playwright/driver/package/types/",
)
a.datas = [
    item for item in a.datas
    if not item[0].replace("\\", "/").startswith(_optional_playwright_prefixes)
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="CourseLM", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CourseLM",
)
