from pathlib import Path
import re

import pytest

import main
from modules.config import AppConfig
from modules.notebooklm import NotebookLMAuthError, UploadReport


class FakeService:
    def __init__(self, auth_fail: bool = False):
        self.ask_count = 0
        self.auth_fail = auth_fail

    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return None
    async def get_or_create_notebook(self, name): return "nb"
    async def upload_sources(self, notebook_id, manifest): return UploadReport(uploaded=[f.path.name for f in manifest.files])
    async def ask(self, notebook_id, question):
        if self.auth_fail: raise NotebookLMAuthError("登录态失效")
        self.ask_count += 1
        if "只输出一个 JSON" in question:
            return '{"course_name":"电磁场","chapters":[{"index":1,"title":"静电场","topics":["库仑定律"]},{"index":2,"title":"电势","topics":["电势差"]}]}'
        if "你正在生成第" in question:
            number = re.search(r"你正在生成第(\d+)章", question).group(1)
            return f"# 第{number}章 示例\n\n## 本章路线\n先学基础题。\n\n## 题型一：基础题\n### 先知道什么\n概念。\n### 标准例题：基础题\n题目。[必要补充]\n### 跟着做\n1. 依据条件列式。\n### 从题归纳\n1. 先判断条件。\n### 自己试\n练习。提示：先判断条件。\n#### 解答\n列式并计算。\n## 章末过关\n练习和答案。"
        return "# 内容\n\n公式 \\(E=mc^2\\)。"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    course = tmp_path / "courses" / "电磁场"
    course.mkdir(parents=True)
    (course / "教材.pdf").write_bytes(b"pdf")
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = AppConfig(paths={"courses_dir":tmp_path/"courses", "output_dir":tmp_path/"output", "logs_dir":tmp_path/"logs"}, obsidian={"vault_path":str(vault),"course_folder":"课程"}, notebooklm={"upload_wait_timeout":60,"source_limit_warn":50}, network={"proxy":"none"}, prompt_runner={"retry":1,"max_question_types":12}, markdown={"tags":["复习"]}, file_types=[".pdf"])
    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    return tmp_path, vault


@pytest.fixture()
def service(monkeypatch):
    svc = FakeService()
    monkeypatch.setattr("modules.notebooklm.NotebookLMService", lambda **kw: svc)
    return svc


def test_generate_creates_current_vault_tree(env, service, capsys):
    _, vault = env
    assert main.main(["generate", "电磁场"]) == 0
    root = vault / "课程" / "电磁场"
    assert (root / "00-绪论.md").is_file()
    assert (root / "chapters" / "01-静电场.md").is_file()
    assert not (root / "appendix" / "03-考前复习提要.md").exists()
    assert service.ask_count == 4  # 大纲、绪论、两章；不再请求三个附录
    assert "课程结构" in capsys.readouterr().out


def test_generate_cache_and_fresh(env, service):
    main.main(["generate", "电磁场"])
    first = service.ask_count
    assert main.main(["generate", "电磁场"]) == 0
    assert service.ask_count == first
    assert main.main(["generate", "电磁场", "--fresh"]) == 0
    assert service.ask_count == first * 2


def test_generate_without_vault_builds_local_handout(env, service, capsys):
    root, _ = env
    main.load_config().obsidian.vault_path = ""
    assert main.main(["generate", "电磁场"]) == 0
    handout = root / "output" / "电磁场" / "handout"
    assert (handout / "manuscript.md").is_file()
    assert (handout / "main.tex").is_file()
    assert "xelatex" in capsys.readouterr().out


def test_generate_exports_pdf_in_one_command(env, service, monkeypatch):
    root, _ = env
    monkeypatch.setattr(main.shutil, "which", lambda name: "xelatex")

    def compile_pdf(path):
        path.with_suffix(".pdf").write_bytes(b"%PDF-test")
        return True, "ok"

    monkeypatch.setattr(main, "compile_latex", compile_pdf)
    assert main.main(["generate", "电磁场"]) == 0
    assert (root / "output" / "电磁场" / "release" / "电磁场-期末复习讲义.pdf").is_file()


def test_generate_pdf_failure_preserves_markdown(env, service, monkeypatch):
    root, _ = env
    monkeypatch.setattr(main.shutil, "which", lambda name: "xelatex")
    monkeypatch.setattr(main, "compile_latex", lambda path: (False, "compile failed"))
    assert main.main(["generate", "电磁场"]) == 2
    assert (root / "output" / "电磁场" / "handout" / "manuscript.md").is_file()


def test_generate_markdown_only_skips_compiler(env, service, monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: "xelatex")
    monkeypatch.setattr(main, "compile_latex", lambda path: pytest.fail("should not compile"))
    assert main.main(["generate", "电磁场", "--no-pdf"]) == 0


def test_generate_sync_failure_keeps_local_handout(env, service):
    root, _ = env
    main.load_config().obsidian.vault_path = str(root / "missing-vault")
    assert main.main(["generate", "电磁场"]) == 2
    assert (root / "output" / "电磁场" / "handout" / "manuscript.md").is_file()


def test_generate_auth_error_does_not_sync(env, monkeypatch):
    _, vault = env
    monkeypatch.setattr("modules.notebooklm.NotebookLMService", lambda **kw: FakeService(auth_fail=True))
    assert main.main(["generate", "电磁场"]) == 2
    assert not (vault / "课程" / "电磁场" / "00-绪论.md").exists()


def test_generate_unknown_course_returns_usage_error(env, service):
    assert main.main(["generate", "不存在的课"]) == 1


def test_generate_rejects_invalid_template_before_network(env, service):
    root, _ = env
    (root / "courses" / "电磁场" / "handout.yaml").write_text("sections: [", encoding="utf-8")
    assert main.main(["generate", "电磁场"]) == 1
    assert service.ask_count == 0


def test_generate_excludes_stale_chapters_from_handout_and_sync(env, service):
    root, vault = env
    chapters = root / "output" / "电磁场" / "md" / "chapters"
    chapters.mkdir(parents=True)
    for name in ("01-旧章名", "03-已删章节"):
        (chapters / f"{name}.md").write_text(
            "---\ngeneration_schema_version: 3\n---\n\n# 旧章节\n\n不应纳入本次讲义", encoding="utf-8"
        )
    assert main.main(["generate", "电磁场", "--fresh", "--no-pdf"]) == 0
    manuscript = (root / "output" / "电磁场" / "handout" / "manuscript.md").read_text(encoding="utf-8")
    assert "不应纳入本次讲义" not in manuscript
    assert not (vault / "课程" / "电磁场" / "chapters" / "01-旧章名.md").exists()
    assert (chapters / "01-旧章名.md").exists()  # 保留旧文件，避免删除用户内容
