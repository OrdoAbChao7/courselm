"""Run Studio through the real engine using the existing FakeService contract."""
import asyncio
import runpy
from pathlib import Path

import pytest

from studio.workspace import Workspace, write_json
from studio.worker import Progress, run


def test_worker_failure_resume_preserves_edit_and_reports_stages(tmp_path, monkeypatch):
    import main
    import modules.notebooklm
    import modules.config
    import modules.path_manager
    # Share the CLI's established FakeService instead of inventing a different
    # valid-response schema for Studio. run_path only defines test helpers.
    helpers = runpy.run_path(str(Path(__file__).parents[2] / 'tests/test_prompt_runner.py'))
    service = helpers['FakeService']()
    class Context:
        async def __aenter__(self): return service
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(modules.notebooklm, 'NotebookLMService', lambda **kwargs: Context())
    monkeypatch.setattr(modules.config, 'load_config', lambda: helpers['make_cfg'](tmp_path))
    monkeypatch.setattr(modules.path_manager, 'build_runtime_env', lambda: {})
    def compile_ok(path):
        path.with_suffix('.pdf').write_bytes(b'%PDF fixture')
        return True, 'ok'
    monkeypatch.setattr(main, 'compile_latex', compile_ok)
    jobid = '123456789abc'
    course_id = 'same-' + jobid
    job = tmp_path / 'studio_data/jobs' / jobid
    source = tmp_path / 'original'
    source.mkdir()
    (source / 'notes.pdf').write_bytes(b'fixture')
    write_json(job / 'status.json', {'id':jobid,'course':'测试','course_id':course_id,'status':'queued','percent':0,'artifacts':{}})
    write_json(job / 'request.json', {'course':'测试','course_id':course_id,'source_path':str(source),
        'mode':'practice','style':'modern','title':'','subtitle':''})
    service.fail_chapter = 2
    with pytest.raises(RuntimeError, match='模型生成'):
        asyncio.run(run(job, Progress(job)))
    w = Workspace(tmp_path, jobid)
    w.update(status='failed')
    chapter = next(d for d in w.documents() if d['path'].startswith('chapters/'))
    doc = w.read(chapter['path'])
    w.save(doc['path'], doc['content'] + '\n人工保留标记', doc['revision'])
    service.fail_chapter = None
    service.ask_calls.clear()
    asyncio.run(run(job, Progress(job), resume=True))
    assert '人工保留标记' in w.read(doc['path'])['content']
    assert '人工保留标记' in w.artifact('markdown').read_text(encoding='utf-8')
    assert w.state()['generation_complete'] is True
    assert w.state()['pdf_current'] is True
    assert len(service.ask_calls) == 1  # Retry only the failed chapter.
    assert all('本次生成模式：题型突破' in q for q in service.ask_calls)
    assert (source / 'notes.pdf').read_bytes() == b'fixture'
    assert '课程大纲生成' in (job / 'events.jsonl').read_text(encoding='utf-8')
