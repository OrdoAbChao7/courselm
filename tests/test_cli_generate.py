from pathlib import Path

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
    return tmp_path, vault


@pytest.fixture()
def service(monkeypatch):
    svc = FakeService()
    monkeypatch.setattr("modules.notebooklm.NotebookLMService", lambda **kw: svc)
    return svc


def test_generate_creates_v2_vault_tree(env, service, capsys):
    _, vault = env
    assert main.main(["generate", "电磁场"]) == 0
    root = vault / "课程" / "电磁场"
    assert (root / "00-绪论.md").is_file()
    assert (root / "chapters" / "01-静电场.md").is_file()
    assert (root / "appendix" / "03-考前复习提要.md").is_file()
    assert "课程结构" in capsys.readouterr().out


def test_generate_cache_and_fresh(env, service):
    main.main(["generate", "电磁场"])
    first = service.ask_count
    assert main.main(["generate", "电磁场"]) == 0
    assert service.ask_count == first
    assert main.main(["generate", "电磁场", "--fresh"]) == 0
    assert service.ask_count == first * 2


def test_generate_stage_and_chapter(env, service):
    assert main.main(["generate", "电磁场", "--stage", "outline"]) == 0
    assert main.main(["generate", "电磁场", "--chapter", "1"]) == 0


def test_generate_auth_error_does_not_sync(env, monkeypatch):
    _, vault = env
    monkeypatch.setattr("modules.notebooklm.NotebookLMService", lambda **kw: FakeService(auth_fail=True))
    assert main.main(["generate", "电磁场"]) == 2
    assert not (vault / "课程" / "电磁场" / "00-绪论.md").exists()


def test_generate_unknown_course_returns_usage_error(env, service):
    assert main.main(["generate", "不存在的课"]) == 1
