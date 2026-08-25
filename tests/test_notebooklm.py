"""NotebookLM 适配层单元测试（FakeClient 注入，不触网）。

覆盖：notebook 复用/新建、上传成功/部分失败/全失败/认证中止、
ask 翻译、异常映射、run_login 命令构造。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from notebooklm.exceptions import (
    AuthError,
    NotebookLMError,
    RateLimitError,
    SourceAddError,
)

from modules.file_manager import CourseFile, CourseManifest
from modules.notebooklm import (
    NotebookLMAuthError,
    NotebookLMOperationError,
    NotebookLMService,
    UploadReport,
    run_login,
)


# ---------------------------------------------------------------- FakeClient

@dataclass
class FakeNotebook:
    id: str
    title: str
    sources_count: int = 0


@dataclass
class FakeAskResult:
    answer: str


@dataclass
class FakeNotebooks:
    existing: list[FakeNotebook] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    fail_create: Exception | None = None

    async def list(self) -> list[FakeNotebook]:
        return list(self.existing)

    async def create(self, title: str) -> FakeNotebook:
        if self.fail_create is not None:
            raise self.fail_create
        nb = FakeNotebook(id=f"new-{len(self.created) + 1}", title=title)
        self.created.append(title)
        return nb


@dataclass
class FakeSources:
    fail_names: set[str] = field(default_factory=set)
    abort_error: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    async def add_file(self, notebook_id: str, file_path, **kwargs) -> str:
        self.calls.append({"notebook_id": notebook_id, "path": Path(file_path), **kwargs})
        if self.abort_error is not None:
            raise self.abort_error
        name = Path(file_path).name
        if name in self.fail_names:
            raise SourceAddError(f"上传失败:{name}")
        return f"src-{name}"


@dataclass
class FakeChat:
    fail_error: Exception | None = None

    async def ask(self, notebook_id: str, question: str) -> FakeAskResult:
        if self.fail_error is not None:
            raise self.fail_error
        return FakeAskResult(answer=f"回答[{question[:12]}]")


@dataclass
class FakeClient:
    notebooks: FakeNotebooks = field(default_factory=FakeNotebooks)
    sources: FakeSources = field(default_factory=FakeSources)
    chat: FakeChat = field(default_factory=FakeChat)
    closed: bool = False

    async def close(self) -> None:
        self.closed = True


def make_manifest(names: list[str]) -> CourseManifest:
    files = [
        CourseFile(path=Path(f"C:/tmp/{n}"), size_bytes=100, category="pdf")
        for n in names
    ]
    return CourseManifest(
        course_name="测试课",
        root=Path("C:/tmp"),
        files=files,
        total_size_bytes=100 * len(files),
    )


def run(coro):
    return asyncio.run(coro)


class TestGetOrCreateNotebook:
    def test_reuse_existing(self) -> None:
        fake = FakeClient(notebooks=FakeNotebooks(existing=[FakeNotebook("id-1", "电磁场")]))
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.get_or_create_notebook("电磁场")

        assert run(go()) == "id-1"
        assert fake.notebooks.created == []  # 未新建

    def test_create_when_missing(self) -> None:
        fake = FakeClient(notebooks=FakeNotebooks(existing=[FakeNotebook("id-1", "别的课")]))
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.get_or_create_notebook("电磁场")

        nb_id = run(go())
        assert nb_id == "new-1"
        assert fake.notebooks.created == ["电磁场"]

    def test_notebook_limit_error_mapped(self) -> None:
        from notebooklm.exceptions import NotebookLimitError

        fake = FakeClient(notebooks=FakeNotebooks(fail_create=NotebookLimitError("limit")))
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.get_or_create_notebook("电磁场")

        with pytest.raises(NotebookLMOperationError, match="上限"):
            run(go())


class TestUploadSources:
    def test_all_success(self) -> None:
        fake = FakeClient()
        svc = NotebookLMService(client=fake, upload_wait_timeout=42)
        m = make_manifest(["a.pdf", "b.pdf"])

        async def go():
            async with svc:
                return await svc.upload_sources("nb-1", m)

        report = run(go())
        assert report.uploaded == ["a.pdf", "b.pdf"]
        assert report.failed == []
        assert not report.all_failed
        # 透传 wait 与超时参数
        assert all(c["wait"] is True and c["wait_timeout"] == 42 for c in fake.sources.calls)

    def test_partial_failure_continues(self) -> None:
        fake = FakeClient(sources=FakeSources(fail_names={"b.pdf"}))
        svc = NotebookLMService(client=fake)
        m = make_manifest(["a.pdf", "b.pdf", "c.pdf"])

        async def go():
            async with svc:
                return await svc.upload_sources("nb-1", m)

        report = run(go())
        assert report.uploaded == ["a.pdf", "c.pdf"]
        assert [f.name for f in report.failed] == ["b.pdf"]

    def test_all_failed_raises(self) -> None:
        fake = FakeClient(sources=FakeSources(fail_names={"a.pdf", "b.pdf"}))
        svc = NotebookLMService(client=fake)
        m = make_manifest(["a.pdf", "b.pdf"])

        async def go():
            async with svc:
                return await svc.upload_sources("nb-1", m)

        with pytest.raises(NotebookLMOperationError, match="全部"):
            run(go())

    def test_auth_error_aborts_immediately(self) -> None:
        fake = FakeClient(sources=FakeSources(abort_error=AuthError("expired")))
        svc = NotebookLMService(client=fake)
        m = make_manifest(["a.pdf", "b.pdf"])

        async def go():
            async with svc:
                return await svc.upload_sources("nb-1", m)

        with pytest.raises(NotebookLMAuthError, match="login"):
            run(go())
        # 中止：第二个文件未被尝试
        assert len(fake.sources.calls) == 1

    def test_rate_limit_aborts(self) -> None:
        fake = FakeClient(sources=FakeSources(abort_error=RateLimitError("429")))
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.upload_sources("nb-1", make_manifest(["a.pdf"]))

        with pytest.raises(NotebookLMOperationError):
            run(go())

    def test_generic_error_per_file(self) -> None:
        """非认证/限流的 NotebookLMError：逐文件记录为失败，不立即中止。"""
        fake = FakeClient(sources=FakeSources(abort_error=NotebookLMError("boom")))
        svc = NotebookLMService(client=fake)
        m = make_manifest(["a.pdf", "b.pdf"])

        async def go():
            async with svc:
                return await svc.upload_sources("nb-1", m)

        # 两个文件都被尝试（未中止），最终全部失败 → 抛"全部失败"
        with pytest.raises(NotebookLMOperationError, match="全部"):
            run(go())
        assert len(fake.sources.calls) == 2


class TestAsk:
    def test_ask_returns_answer(self) -> None:
        fake = FakeClient()
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.ask("nb-1", "总结知识体系")

        assert run(go()) == "回答[总结知识体系]"

    def test_ask_auth_error_mapped(self) -> None:
        fake = FakeClient(chat=FakeChat(fail_error=AuthError("expired")))
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.ask("nb-1", "问题")

        with pytest.raises(NotebookLMAuthError):
            run(go())

    def test_ask_generic_error_mapped(self) -> None:
        fake = FakeClient(chat=FakeChat(fail_error=NotebookLMError("rpc boom")))
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                return await svc.ask("nb-1", "问题")

        with pytest.raises(NotebookLMOperationError, match="rpc boom"):
            run(go())


class TestLifecycle:
    def test_client_closed_on_exit_when_owned_is_false_with_injection(self) -> None:
        """注入的 client 不归适配层所有，退出时不应关闭。"""
        fake = FakeClient()
        svc = NotebookLMService(client=fake)

        async def go():
            async with svc:
                await svc.find_notebook_id("x")

        run(go())
        assert fake.closed is False

    def test_service_requires_context(self) -> None:
        """未注入 client 且未进入上下文时，访问 client 应报错。"""
        svc = NotebookLMService()  # 生产模式：client 由 from_storage 提供
        with pytest.raises(RuntimeError, match="上下文"):
            _ = svc.client


class TestUploadReport:
    def test_report_defaults_and_str(self) -> None:
        r = UploadReport()
        assert not r.all_failed
        assert str(r) == "成功 0 / 失败 0"


class TestRunLogin:
    def test_invokes_notebooklm_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        class FakeProc:
            returncode = 0

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            captured["kw"] = kw
            return FakeProc()

        monkeypatch.setattr("modules.notebooklm.subprocess.run", fake_run)
        assert run_login() == 0
        cmd = captured["cmd"]
        assert cmd[1:] == ["-m", "notebooklm", "login"]

    def test_nonzero_exit_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeProc:
            returncode = 3

        monkeypatch.setattr("modules.notebooklm.subprocess.run", lambda cmd, **kw: FakeProc())
        assert run_login() == 3
