"""generate 命令 CLI 集成测试（FakeService 注入，零网络）。

验证 main.py 把 scan → prompts → pipeline → markdown → sync 串起来的
完整行为：退出码、vault 落盘、--prompts 过滤、认证失败提示。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import main
from modules.config import AppConfig
from modules.notebooklm import NotebookLMAuthError, UploadReport

SUMMARY_ANSWER = """
## 常考题型汇总

| 序号 | 题型名称 | 高频解法 |
| ---- | -------- | -------- |
| 1    | 镜像法   | 对称性分析 |
| 2    | 分离变量法 | 边界条件匹配 |
"""


class FakeService:
    """替代 NotebookLMService 的假服务（async with 协议）。"""

    def __init__(self, *, upload_wait_timeout: float = 300.0, client=None,
                 auth_fail: bool = False) -> None:
        self.ask_count = 0
        self.auth_fail = auth_fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_or_create_notebook(self, name: str) -> str:
        return "nb-fake"

    async def upload_sources(self, notebook_id: str, manifest) -> UploadReport:
        return UploadReport(uploaded=[f.path.name for f in manifest.files])

    async def ask(self, notebook_id: str, question: str) -> str:
        if self.auth_fail:
            raise NotebookLMAuthError("登录态失效")
        self.ask_count += 1
        if "常考题型" in question:  # 真实 prompts.yaml 题型总结模板的特征词
            return SUMMARY_ANSWER
        return f"## 回答\n\n针对问题的详细内容，含公式 \\(E=mc^2\\)。"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """搭建隔离环境：课程资料 + 测试配置（vault 指向临时目录）。"""
    courses = tmp_path / "courses" / "电磁场"
    courses.mkdir(parents=True)
    (courses / "教材.pdf").write_bytes(b"%PDF-1.4 fake")
    (courses / "试卷.pdf").write_bytes(b"%PDF-1.4 fake")
    vault = tmp_path / "vault"
    vault.mkdir()

    cfg = AppConfig(
        paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output",
               "logs_dir": tmp_path / "logs"},
        obsidian={"vault_path": str(vault), "course_folder": "课程"},
        notebooklm={"upload_wait_timeout": 60, "source_limit_warn": 50},
        network={"proxy": "none"},
        prompt_runner={"retry": 1, "max_question_types": 12},
        markdown={"tags": ["大学课程", "复习"]},
        file_types=[".pdf"],
    )
    monkeypatch.setattr(main, "load_config", lambda: cfg)
    return tmp_path, vault, cfg


@pytest.fixture()
def fake_service(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    svc = FakeService()

    def factory(**kwargs):
        return svc

    monkeypatch.setattr("modules.notebooklm.NotebookLMService", factory)
    return svc


class TestGenerateFullFlow:
    def test_success_exit0_and_vault_files(self, env, fake_service, capsys) -> None:
        tmp_path, vault, cfg = env

        rc = main.main(["generate", "电磁场"])

        assert rc == 0
        course_dir = vault / "课程" / "电磁场"
        assert (course_dir / "知识结构.md").is_file()
        assert (course_dir / "公式总结.md").is_file()
        assert (course_dir / "题型" / "题型总结.md").is_file()
        assert (course_dir / "题型" / "镜像法.md").is_file()
        assert (course_dir / "题型" / "分离变量法.md").is_file()

        out = capsys.readouterr().out
        assert "处理完成" in out
        assert "2 类" in out
        assert "同步" in out

        # 文档内容含 front matter 与转换后的公式
        text = (course_dir / "知识结构.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "$E=mc^2$" in text

    def test_partial_failure_exit2(self, env, monkeypatch, capsys) -> None:
        tmp_path, vault, cfg = env

        class FlakyService(FakeService):
            async def ask(self, notebook_id: str, question: str) -> str:
                if "镜像法" in question:
                    raise RuntimeError("boom")
                return await super().ask(notebook_id, question)

        svc = FlakyService()
        monkeypatch.setattr("modules.notebooklm.NotebookLMService", lambda **kw: svc)

        rc = main.main(["generate", "电磁场"])

        assert rc == 2
        course_dir = vault / "课程" / "电磁场"
        assert (course_dir / "知识结构.md").is_file()        # 成功的照常生成
        assert not (course_dir / "题型" / "镜像法.md").exists()  # 失败的不生成
        out = capsys.readouterr().out
        assert "失败明细" in out

    def test_rerun_all_cache_hit(self, env, fake_service, capsys) -> None:
        main.main(["generate", "电磁场"])
        assert fake_service.ask_count > 0

        fake_service.ask_count = 0
        rc = main.main(["generate", "电磁场"])

        assert rc == 0
        assert fake_service.ask_count == 0  # 全部缓存命中，零提问
        out = capsys.readouterr().out
        assert "缓存命中" in out

    def test_fresh_rerun(self, env, fake_service) -> None:
        main.main(["generate", "电磁场"])
        n_first = fake_service.ask_count
        assert n_first > 0

        fake_service.ask_count = 0
        rc = main.main(["generate", "电磁场", "--fresh"])
        assert rc == 0
        assert fake_service.ask_count == n_first  # 重新提问


class TestGeneratePromptsFilter:
    def test_only_formula_summary(self, env, fake_service, capsys) -> None:
        tmp_path, vault, cfg = env

        rc = main.main(["generate", "电磁场", "--prompts", "formula_summary"])

        assert rc == 0
        course_dir = vault / "课程" / "电磁场"
        assert (course_dir / "公式总结.md").is_file()
        assert not (course_dir / "知识结构.md").exists()    # 其他固定 prompt 未跑
        assert not (course_dir / "题型").exists()            # 调试模式跳过阶段二
        assert fake_service.ask_count == 1

    def test_unknown_prompt_id_exit1(self, env, fake_service) -> None:
        rc = main.main(["generate", "电磁场", "--prompts", "no_such_id"])
        assert rc == 1


class TestGenerateErrors:
    def test_auth_error_exit2(self, env, monkeypatch) -> None:
        tmp_path, vault, cfg = env
        svc = FakeService(auth_fail=True)
        monkeypatch.setattr("modules.notebooklm.NotebookLMService", lambda **kw: svc)

        rc = main.main(["generate", "电磁场"])
        assert rc == 2
        # vault 未被写入
        assert not (vault / "课程" / "电磁场").exists()

    def test_course_not_found_exit1(self, env, fake_service) -> None:
        rc = main.main(["generate", "不存在的课"])
        assert rc == 1

    def test_vault_not_configured_exit1(self, env, fake_service, monkeypatch) -> None:
        tmp_path, vault, cfg = env
        cfg.obsidian.vault_path = ""
        rc = main.main(["generate", "电磁场"])
        assert rc == 1
