"""NotebookLM 适配层：封装 notebooklm-py 客户端，提供本项目语义化操作。

设计要点：
- 依赖注入：NotebookLMService(client=None)。生产环境经 from_storage() 建连；
  单元测试注入 FakeClient，无需网络即可验证全部编排逻辑。
- 异常翻译：上游认证类异常 → NotebookLMAuthError（提示重跑 courselm login）；
  其余 NotebookLMError → NotebookLMOperationError。认证失败立即中止整个流水线
  （后续操作必然继续失败），单文件上传失败仅记录并继续。
- 上游 API 依据 notebooklm-py 0.8.1 源码核对：
    client.notebooks.list() -> list[Notebook(id, title, ...)]
    client.notebooks.create(title) -> Notebook
    client.sources.add_file(notebook_id, file_path, wait=True, wait_timeout=...) -> Source
    client.chat.ask(notebook_id, question) -> AskResult(answer=...)
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from loguru import logger
from pydantic import BaseModel

from notebooklm import NotebookLMClient
from notebooklm.exceptions import (
    AuthError,
    AuthExtractionError,
    HeadlessLoginRequiredError,
    NotebookLMError,
    NotebookLimitError,
    RateLimitError,
)

if TYPE_CHECKING:
    from modules.file_manager import CourseManifest


class NotebookLMAdapterError(Exception):
    """适配层错误基类。"""


class NotebookLMAuthError(NotebookLMAdapterError):
    """登录态缺失或失效，需重新 courselm login。"""


class NotebookLMOperationError(NotebookLMAdapterError):
    """NotebookLM 操作失败（网络/RPC/配额等）。"""


class UploadFailure(BaseModel):
    name: str
    error: str


class UploadReport(BaseModel):
    """一次课程资料批量上传的结果。"""

    uploaded: list[str] = []
    failed: list[UploadFailure] = []

    @property
    def all_failed(self) -> bool:
        return bool(self.failed) and not self.uploaded

    def __str__(self) -> str:
        return f"成功 {len(self.uploaded)} / 失败 {len(self.failed)}"


# 认证类异常：出现即中止（后续操作必然继续失败）
_AUTH_ERRORS = (HeadlessLoginRequiredError, AuthError, AuthExtractionError)
# 账号级限流：继续重试只会更糟，同样中止
_ABORT_ERRORS = _AUTH_ERRORS + (RateLimitError,)


@contextmanager
def _translate_errors() -> Iterator[None]:
    """把上游异常翻译为适配层异常（含可读提示）。"""
    try:
        yield
    except NotebookLMAuthError:
        raise
    except _AUTH_ERRORS as e:
        raise NotebookLMAuthError(
            f"NotebookLM 登录态失效（{type(e).__name__}），请运行 courselm login 后重试"
        ) from e
    except NotebookLMError as e:
        raise NotebookLMOperationError(f"NotebookLM 操作失败：{e}") from e


class NotebookLMService:
    """课程流水线所需的 NotebookLM 操作集合（异步）。

    用法：
        async with NotebookLMService(upload_wait_timeout=300) as svc:
            nb_id = await svc.get_or_create_notebook("电磁场")
            report = await svc.upload_sources(nb_id, manifest)
            answer = await svc.ask(nb_id, "总结知识体系")
    """

    def __init__(
        self,
        upload_wait_timeout: float = 300.0,
        client: Any | None = None,
    ) -> None:
        self._upload_wait_timeout = upload_wait_timeout
        self._client = client  # 注入的 FakeClient（测试用）；None 则 from_storage
        self._owns_client = client is None

    # ---- 生命周期 -------------------------------------------------------

    async def __aenter__(self) -> NotebookLMService:
        if self._client is None:
            try:
                ctx = NotebookLMClient.from_storage()
                self._client = await ctx.__aenter__()
                logger.debug("NotebookLM 客户端已建立（from_storage）")
            except FileNotFoundError as e:
                raise NotebookLMAuthError(
                    f"未找到 NotebookLM 登录态文件，请先运行 courselm login（{e}）"
                ) from e
            except NotebookLMError as e:
                if isinstance(e, _AUTH_ERRORS):
                    raise NotebookLMAuthError(
                        f"NotebookLM 登录态失效（{type(e).__name__}），"
                        "请运行 courselm login 后重试"
                    ) from e
                raise NotebookLMOperationError(f"NotebookLM 客户端初始化失败：{e}") from e
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client = self._client
        if self._owns_client and client is not None:
            await client.close()
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("NotebookLMService 未进入异步上下文（async with）")
        return self._client

    # ---- 业务操作 -------------------------------------------------------

    async def find_notebook_id(self, title: str) -> str | None:
        """按标题精确查找已有 Notebook。

        注意：上游 list() 基于 ListRecentlyViewedProjects，与自己拥有的
        Notebook 列表页一致；未访问过的极旧 Notebook 理论上可能缺席，
        未命中时会新建，不影响正确性（仅可能产生重复）。
        """
        with _translate_errors():
            notebooks = await self.client.notebooks.list()
        for nb in notebooks:
            if nb.title == title:
                logger.info("复用已有 Notebook：「{}」（id={}, 资料数={}）",
                            title, nb.id, getattr(nb, "sources_count", "?"))
                return nb.id
        return None

    async def create_notebook(self, title: str) -> str:
        with _translate_errors():
            try:
                nb = await self.client.notebooks.create(title)
            except NotebookLimitError as e:
                raise NotebookLMOperationError(
                    "已达 Notebook 数量上限（免费版 100 个），"
                    "请到 NotebookLM 删除部分不再使用的笔记本后重试"
                ) from e
        logger.info("已创建 Notebook：「{}」（id={}）", title, nb.id)
        return nb.id

    async def get_or_create_notebook(self, course_name: str) -> str:
        """查找同名 Notebook 复用；未命中则新建。"""
        existing = await self.find_notebook_id(course_name)
        if existing is not None:
            return existing
        return await self.create_notebook(course_name)

    async def upload_sources(
        self,
        notebook_id: str,
        manifest: CourseManifest,
    ) -> UploadReport:
        """逐个上传课程资料并等待索引完成。

        - 单文件失败（超时/格式等）：记录后继续
        - 认证失效 / 限流：立即中止（抛 NotebookLMAuthError / NotebookLMOperationError）
        - 全部失败：抛 NotebookLMOperationError（流水线无资料可用，无意义继续）
        """
        report = UploadReport()
        total = len(manifest.files)
        for i, f in enumerate(manifest.files, start=1):
            logger.info("上传资料 ({}/{})：{}（{:.1f} MB）",
                        i, total, f.path.name, f.size_bytes / 1024 / 1024)
            try:
                await self.client.sources.add_file(
                    notebook_id,
                    f.path,
                    wait=True,
                    wait_timeout=self._upload_wait_timeout,
                )
            except _ABORT_ERRORS as e:
                with _translate_errors():
                    raise e  # 复用翻译逻辑给出统一提示
            except NotebookLMError as e:
                logger.warning("资料上传失败，跳过：{}（{}）", f.path.name, e)
                report.failed.append(UploadFailure(name=f.path.name, error=str(e)))
                continue
            except (TimeoutError, OSError) as e:
                logger.warning("资料上传失败，跳过：{}（{}）", f.path.name, e)
                report.failed.append(UploadFailure(name=f.path.name, error=str(e)))
                continue
            report.uploaded.append(f.path.name)
            logger.info("资料就绪：{}", f.path.name)

        logger.info("上传完成：{}", report)
        if report.all_failed:
            raise NotebookLMOperationError(
                f"全部 {total} 个资料上传失败，流水线中止。"
                f"失败原因：{report.failed[0].error}"
            )
        return report

    async def ask(self, notebook_id: str, question: str) -> str:
        """向 Notebook 提问并返回回答文本（每次独立会话）。"""
        with _translate_errors():
            result = await self.client.chat.ask(notebook_id, question)
        answer: str = result.answer or ""
        logger.debug("提问获得回答：{} 字符", len(answer))
        return answer


def run_login(browser: str = "chromium") -> int:
    """交互式登录：子进程调用上游 CLI（继承 stdio，浏览器流程对用户可见）。

    上游 CLI 负责 Chromium 预检、Google 登录页捕获、Cookie 原子持久化。
    browser: chromium（Playwright 内置）/ chrome / msedge（系统浏览器，
    内置 Chromium 异常时的备用路径）。
    返回进程退出码（0 成功）。
    """
    logger.info("启动 NotebookLM 登录流程（浏览器将自动打开）...")
    proc = subprocess.run(
        [sys.executable, "-m", "notebooklm", "login", "--browser", browser]
    )
    if proc.returncode == 0:
        logger.info("登录成功，登录态已持久化，之后无需重复登录")
    else:
        logger.error("登录失败（退出码 {}），请查看上方上游输出", proc.returncode)
    return proc.returncode
