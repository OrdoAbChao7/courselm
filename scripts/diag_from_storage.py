"""最小复现实验：定位 from_storage 在本环境的卡点。

用法：.venv\\Scripts\\python scripts\\diag_from_storage.py [无代理|代理]
"""

from __future__ import annotations

import asyncio
import faulthandler
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 15 秒后自动 dump 所有线程栈（定位卡点），不退出进程
faulthandler.dump_traceback_later(timeout=15, exit=False, file=sys.stderr)

mode = sys.argv[1] if len(sys.argv) > 1 else "proxy"
if mode == "proxy":
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7897")
    print(f"[diag] 模式=经代理 {os.environ.get('HTTPS_PROXY')}")
else:
    for v in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        os.environ.pop(v, None)
    print("[diag] 模式=直连（已清空代理环境变量）")


async def main() -> None:
    from notebooklm import NotebookLMClient

    t0 = time.monotonic()
    print(f"[diag] {t0 - t0:5.1f}s  调用 from_storage()...")
    ctx = NotebookLMClient.from_storage()
    print(f"[diag] {time.monotonic() - t0:5.1f}s  ctx 已创建（未建连），进入 __aenter__...")
    async with ctx as client:
        print(f"[diag] {time.monotonic() - t0:5.1f}s  客户端已建立 ✓")
        notebooks = await client.notebooks.list()
        print(f"[diag] {time.monotonic() - t0:5.1f}s  notebooks.list() ✓ 共 {len(notebooks)} 个 notebook")
        for nb in notebooks[:5]:
            print(f"        - {nb.title!r} (id={nb.id})")
    print(f"[diag] {time.monotonic() - t0:5.1f}s  完成，正常退出")


if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=90))
    except asyncio.TimeoutError:
        print("[diag] 90 秒超时 —— 卡死确认")
        sys.exit(2)
