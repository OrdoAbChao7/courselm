"""network 模块单元测试：系统代理检测与环境变量同步。"""

from __future__ import annotations

import os

import pytest

from modules.network import apply_proxy_env, detect_windows_proxy, setup_proxy


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch: pytest.MonkeyPatch):
    """每个测试前清掉代理相关环境变量，避免相互污染。"""
    for var in (
        "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
        "NO_PROXY", "no_proxy",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def _patch_registry(monkeypatch: pytest.MonkeyPatch, enable: int, server: str | None = None) -> None:
    """伪造 winreg：OpenKey 返回透传对象，QueryValueEx 按名字应答。

    必须两个都 patch：真 winreg.QueryValueEx 校验 key 是 PyHKEY 类型，
    FakeKey 过不了类型检查。
    """
    import winreg

    class _FakeKey:  # 支持 with 语句即可，值由 QueryValueEx 应答
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda root, path: _FakeKey())

    def fake_query_value_ex(key, name):
        if name == "ProxyEnable":
            return (enable, None)
        if name == "ProxyServer":
            return (server, None)
        raise OSError(f"unexpected value: {name}")

    monkeypatch.setattr(winreg, "QueryValueEx", fake_query_value_ex)


class TestDetectWindowsProxy:
    def test_reads_registry_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_registry(monkeypatch, enable=1, server="127.0.0.1:7897")
        assert detect_windows_proxy() == "http://127.0.0.1:7897"

    def test_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_registry(monkeypatch, enable=0)
        assert detect_windows_proxy() is None

    def test_per_protocol_format_prefers_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_registry(
            monkeypatch,
            enable=1,
            server="http=127.0.0.1:7890;https=127.0.0.1:7897;ftp=x",
        )
        assert detect_windows_proxy() == "http://127.0.0.1:7897"

    def test_registry_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import winreg

        def raise_oserror(root, path):
            raise OSError("denied")

        monkeypatch.setattr(winreg, "OpenKey", raise_oserror)
        assert detect_windows_proxy() is None


class TestApplyProxyEnv:
    def test_sets_all_vars(self) -> None:
        assert apply_proxy_env("http://127.0.0.1:7897") is True
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
        assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
        assert os.environ["NO_PROXY"] == "localhost,127.0.0.1,::1"

    def test_setdefault_does_not_override(self) -> None:
        os.environ["HTTPS_PROXY"] = "http://user-set:1"
        apply_proxy_env("http://127.0.0.1:7897")
        assert os.environ["HTTPS_PROXY"] == "http://user-set:1"

    def test_empty_returns_false(self) -> None:
        assert apply_proxy_env(None) is False
        assert apply_proxy_env("") is False


class TestSetupProxy:
    def test_explicit_value(self) -> None:
        assert setup_proxy("http://127.0.0.1:7897") is True
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"

    def test_explicit_value_without_scheme(self) -> None:
        assert setup_proxy("127.0.0.1:7897") is True
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"

    def test_none_disables(self) -> None:
        assert setup_proxy("none") is False
        assert "HTTPS_PROXY" not in os.environ

    def test_auto_without_system_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("modules.network.detect_windows_proxy", lambda: None)
        assert setup_proxy("auto") is False
        assert "HTTPS_PROXY" not in os.environ

    def test_auto_with_system_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("modules.network.detect_windows_proxy", lambda: "http://127.0.0.1:7897")
        assert setup_proxy("auto") is True
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
