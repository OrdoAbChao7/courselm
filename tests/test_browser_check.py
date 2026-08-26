from __future__ import annotations

from modules.browser_check import chrome_available


def test_chrome_available_returns_probe_result() -> None:
    assert chrome_available(lambda: True) is True
    assert chrome_available(lambda: False) is False


def test_chrome_available_converts_probe_error_to_false() -> None:
    def probe() -> bool:
        raise RuntimeError("chrome missing")

    assert chrome_available(probe) is False
