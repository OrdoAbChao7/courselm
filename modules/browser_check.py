"""系统 Google Chrome 可用性检查。"""

from __future__ import annotations

from collections.abc import Callable


def _probe_playwright_chrome() -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        browser.close()
    return True


def chrome_available(probe: Callable[[], bool] | None = None) -> bool:
    """优先通过 Playwright 的 chrome channel 检测系统 Chrome。"""
    try:
        return (probe or _probe_playwright_chrome)()
    except Exception:
        return False
