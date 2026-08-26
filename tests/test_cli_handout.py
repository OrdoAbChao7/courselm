from pathlib import Path

import main
from modules.config import AppConfig


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        paths={"courses_dir": tmp_path / "courses", "output_dir": tmp_path / "output", "logs_dir": tmp_path / "logs"},
        obsidian={"vault_path": str(tmp_path / "vault"), "course_folder": "课程"},
        notebooklm={"upload_wait_timeout": 60, "source_limit_warn": 50},
        network={"proxy": "none"},
        prompt_runner={"retry": 1, "max_question_types": 12},
        markdown={"tags": ["大学课程", "复习"]},
        file_types=[".pdf"],
    )


def _source(tmp_path: Path) -> None:
    md = tmp_path / "output" / "电磁场" / "md"
    (md / "题型").mkdir(parents=True)
    (md / "知识结构.md").write_text("# 知识结构", encoding="utf-8")
    (md / "公式总结.md").write_text("# 公式总结\n\n$$E=mc^2$$", encoding="utf-8")
    (md / "题型" / "题型总结.md").write_text("# 题型总结", encoding="utf-8")


def test_build_handout_command_writes_latex(tmp_path: Path, monkeypatch, capsys) -> None:
    _source(tmp_path)
    monkeypatch.setattr(main, "load_config", lambda: _cfg(tmp_path))

    assert main.main(["build-handout", "电磁场"]) == 0
    assert (tmp_path / "output" / "电磁场" / "handout" / "main.tex").is_file()
    assert "讲义初稿" in capsys.readouterr().out


def test_export_handout_reports_compiler_failure(tmp_path: Path, monkeypatch) -> None:
    _source(tmp_path)
    monkeypatch.setattr(main, "load_config", lambda: _cfg(tmp_path))
    monkeypatch.setattr(main, "compile_latex", lambda path: (False, "latex failed"))

    assert main.main(["export-handout", "电磁场"]) == 2
    assert (tmp_path / "output" / "电磁场" / "handout" / "main.tex").is_file()


def test_export_handout_copies_pdf_after_success(tmp_path: Path, monkeypatch) -> None:
    _source(tmp_path)
    monkeypatch.setattr(main, "load_config", lambda: _cfg(tmp_path))

    def fake_compile(path: Path):
        path.with_suffix(".pdf").write_bytes(b"%PDF-fake")
        return True, "ok"

    monkeypatch.setattr(main, "compile_latex", fake_compile)
    assert main.main(["export-handout", "电磁场"]) == 0
    assert (tmp_path / "output" / "电磁场" / "release" / "电磁场-期末复习讲义.pdf").is_file()


def test_compile_latex_tolerates_missing_process_output(tmp_path: Path, monkeypatch) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("内容", encoding="utf-8")
    monkeypatch.setattr(main.shutil, "which", lambda name: "xelatex.exe")

    def fake_run(*args, **kwargs):
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        tex.with_suffix(".pdf").write_bytes(b"%PDF-fake")
        return main.subprocess.CompletedProcess(args[0], 0, stdout=None, stderr=None)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    assert main.compile_latex(tex)[0] is True
