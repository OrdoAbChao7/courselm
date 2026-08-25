"""排列组合实验：定位 NamedTemporaryFile 卡死的具体条件。

每个组合在独立子进程运行（5 秒超时强制杀掉），避免一次卡死阻塞全部。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHILD = r'''
import tempfile, sys
d, pre, suf = sys.argv[1], sys.argv[2], sys.argv[3]
d = d or None
with tempfile.NamedTemporaryFile("w", dir=d, prefix=pre, suffix=suf, delete=False) as f:
    f.write("{}")
print("OK", f.name)
'''

PROFILE = r"C:\Users\32583\.notebooklm\profiles\default"
CASES = [
    ("profile + .storage_state.json.", PROFILE, ".storage_state.json.", ".tmp"),
    ("profile + .foo.", PROFILE, ".foo.", ".tmp"),
    ("profile + 无前缀", PROFILE, "", ".tmp"),
    ("TEMP   + .storage_state.json.", None, ".storage_state.json.", ".tmp"),
    ("E盘    + .storage_state.json.", "E:/Projects/note-agent", ".storage_state.json.", ".tmp"),
]


def main() -> None:
    child = Path("_t_child.py")
    child.write_text(CHILD, encoding="utf-8")
    for label, d, pre, suf in CASES:
        argv = [sys.executable, str(child)] + ([d] if d else []) + [pre, suf]
        if d is None:
            argv = [sys.executable, str(child), "", pre, suf]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=5)
            out = (r.stdout + r.stderr).strip().replace("\n", " | ")[:80]
            print(f"{label:32} -> {'通过' if r.returncode == 0 else 'FAIL'}: {out}")
        except subprocess.TimeoutExpired:
            print(f"{label:32} -> 卡死（5s 超时）")
    child.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
