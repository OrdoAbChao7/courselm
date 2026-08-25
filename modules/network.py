"""网络环境适配：Windows 系统代理 → 环境变量同步。

背景：notebooklm-py 的 httpx 客户端只读 HTTP_PROXY/HTTPS_PROXY 环境变量
（trust_env 行为），不读 Windows 系统代理注册表。Clash 等工具的"系统代理"
模式只改注册表。若不同步，登录成功后的所有 API 调用都会直连 Google 失败。

策略（config.yaml: network.proxy）：
    auto  —— 读取 Windows 系统代理设置并同步到环境变量（默认）
    none  —— 不做任何事（TUN 模式 / 直连环境适用）
    显式值 —— 如 http://127.0.0.1:7897，直接使用

同步时使用 setdefault：不覆盖用户已手动导出的环境变量。
"""

from __future__ import annotations

import os
import sys
from loguru import logger

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# 本地地址不走代理
_DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1"


def detect_windows_proxy() -> str | None:
    """读取 Windows 当前用户的系统代理设置；未启用或读取失败返回 None。

    注册表 ProxyServer 两种格式：
        "127.0.0.1:7897"                       —— 全协议同一代理
        "http=...;https=...;ftp=..."           —— 分协议（取 https，退化取 http）
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enable:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError as e:
        logger.debug("读取 Windows 系统代理失败：{}", e)
        return None

    server = (server or "").strip()
    if not server:
        return None

    if "=" in server:  # 分协议格式
        parts = dict(
            p.split("=", 1) for p in server.split(";") if "=" in p
        )
        chosen = parts.get("https") or parts.get("http")
        if not chosen:
            return None
        proxy = chosen
    else:
        proxy = server

    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return proxy


def apply_proxy_env(proxy: str | None) -> bool:
    """把代理地址写入 HTTPS_PROXY/HTTP_PROXY（setdefault，不覆盖已有值）。

    返回是否实际生效（proxy 非空即视为已配置）。
    """
    if not proxy:
        return False
    os.environ.setdefault("HTTPS_PROXY", proxy)
    os.environ.setdefault("https_proxy", proxy)
    os.environ.setdefault("HTTP_PROXY", proxy)
    os.environ.setdefault("http_proxy", proxy)
    os.environ.setdefault("NO_PROXY", _DEFAULT_NO_PROXY)
    os.environ.setdefault("no_proxy", _DEFAULT_NO_PROXY)
    logger.info("已启用代理：{}（httpx API 调用将经此代理访问 NotebookLM）", proxy)
    return True


def setup_proxy(config_value: str) -> bool:
    """按配置值应用代理。返回是否处于代理环境。

    Args:
        config_value: "auto" / "none" / 显式代理地址
    """
    value = (config_value or "auto").strip()
    if value.lower() == "none":
        logger.debug("network.proxy=none，跳过代理配置")
        return False
    if value.lower() == "auto":
        proxy = detect_windows_proxy()
        if proxy is None:
            logger.info("未检测到 Windows 系统代理，API 调用将直连（TUN 模式或无需代理环境）")
            return False
        return apply_proxy_env(proxy)
    # 显式地址
    proxy = value if "://" in value else f"http://{value}"
    return apply_proxy_env(proxy)
