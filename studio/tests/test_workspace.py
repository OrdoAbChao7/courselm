from pathlib import Path
import json

import pytest

from studio.worker import atomic_json


@pytest.fixture
def workspace(tmp_path):
    from studio.workspace import Workspace
    jobid = 'a123456789ab'
    job = tmp_path / 'studio_data' / 'jobs' / jobid
    job.mkdir(parents=True)
    atomic_json(job / 'status.json', {'id': jobid, 'course_id': 'demo-' + jobid,
                'course': '测试', 'status': 'draft_ready', 'artifacts': {}})
    atomic_json(job / 'request.json', {'course': '测试'})
    md = tmp_path / 'output' / ('demo-' + jobid) / 'md'
    (md / 'chapters').mkdir(parents=True)
    (md / '00-绪论.md').write_text('# 绪论\n\n介绍', encoding='utf-8')
    (md / 'chapters' / '01-基础.md').write_text('# 基础\n\n旧内容', encoding='utf-8')
    return Workspace(tmp_path, jobid)


def test_save_conflict_backup_restore_and_isolation(workspace):
    w = workspace
    doc = w.read('chapters/01-基础.md')
    saved = w.save(doc['path'], '# 基础\n\n修改后的公式 $x=2$', doc['revision'])
    assert '修改后的公式' in w.read(doc['path'])['content']
    with pytest.raises(ValueError, match='冲突'):
        w.save(doc['path'], '覆盖', doc['revision'])
    versions = w.versions(doc['path'])
    assert len(versions) == 1
    restored = w.restore(doc['path'], versions[0]['id'], saved['revision'])
    assert restored['content'] == doc['content']
    for path in ['../request.json', '../../other/md/secret.md', 'C:/private.md', 'chapters\\..\\secret.md']:
        with pytest.raises((ValueError, FileNotFoundError)):
            w.read(path)


def test_build_reads_saved_markdown_and_compile_failure_keeps_draft(workspace, monkeypatch):
    import main
    w = workspace
    doc = w.read('chapters/01-基础.md')
    w.save(doc['path'], '# 基础\n\n唯一的修改标记 $x=42$', doc['revision'])
    monkeypatch.setattr(main, 'compile_latex', lambda path: (False, 'main.tex:19: Undefined control sequence'))
    state = w.build()
    assert state['status'] == 'draft_ready'
    assert '唯一的修改标记' in (w.output / 'handout/manuscript.md').read_text(encoding='utf-8')
    assert '唯一的修改标记' in (w.output / 'handout/main.tex').read_text(encoding='utf-8')
    assert '唯一的修改标记' in w.read(doc['path'])['content']
    assert 'main.tex:19' in state['compile_log']
    with pytest.raises((ValueError, FileNotFoundError)):
        w.artifact('pdf')


def test_review_requires_current_pdf_and_all_files(workspace, monkeypatch):
    import main
    w = workspace
    def compile_ok(path):
        path.with_suffix('.pdf').write_bytes(b'%PDF-1.4 fixture')
        return True, 'ok'
    monkeypatch.setattr(main, 'compile_latex', compile_ok)
    w.build()
    with pytest.raises(ValueError):
        w.deliver()
    for doc in w.documents():
        w.review(doc['path'], 'approved', doc['revision'])
    assert w.deliver()['status'] == 'deliverable'
    doc = w.read('chapters/01-基础.md')
    w.save(doc['path'], doc['content'] + '\n新修改', doc['revision'])
    assert w.state()['status'] == 'draft_ready'
    assert w.read(doc['path'])['review'] == 'pending'
    with pytest.raises(ValueError):
        w.artifact('pdf')


def test_busy_disallows_save_and_review(workspace):
    doc = workspace.read('chapters/01-基础.md')
    state = workspace.state()
    state['status'] = 'running'
    atomic_json(workspace.job / 'status.json', state)
    with pytest.raises(ValueError):
        workspace.save(doc['path'], 'racing', doc['revision'])
    with pytest.raises(ValueError):
        workspace.review(doc['path'], 'approved', doc['revision'])


@pytest.fixture
def bound_workspace(workspace):
    from PIL import Image, ImageDraw
    w = workspace
    w.course.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (400, 240), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 370, 210), outline='black', width=3)
    draw.text((45, 70), 'R=20 ohm', fill='black')
    image.save(w.course / 'original.png')
    figures = w.scan_figures()
    doc = w.read('chapters/01-基础.md')
    doc = w.save(doc['path'], '# 基础\n\n### 标准例题\n\n已知电阻为20Ω，求支路电流。\n\n**解析**\n\n使用欧姆定律。', doc['revision'])
    result = w.bind_figure(doc['path'], doc['revision'], figures[0]['asset_id'], 5, '原始电路图')
    return w, result


@pytest.mark.parametrize('changed', ['source', 'image', 'binding'])
def test_bound_figure_changes_invalidate_export(bound_workspace, monkeypatch, changed):
    import main
    w, result = bound_workspace
    def compile_ok(path):
        path.with_suffix('.pdf').write_bytes(b'%PDF fixture')
        return True, 'ok'
    monkeypatch.setattr(main, 'compile_latex', compile_ok)
    w.build()
    assert w.artifact('pdf').is_file()
    if changed == 'source':
        (w.course / 'original.png').write_bytes(b'changed')
    elif changed == 'image':
        asset = w.figures_manifest().get(result['binding']['asset_id'])
        (w.output / asset.image_rel_path).write_bytes(b'changed')
    else:
        manifest = w.figures_manifest()
        manifest.bindings.clear()
        manifest.save()
    with pytest.raises(ValueError, match='重新编译'):
        w.artifact('pdf')


def test_binding_save_uses_revision_and_creates_image_before_solution(bound_workspace):
    w, result = bound_workspace
    doc = result['document']
    assert doc['content'].index('![原始电路图]') < doc['content'].index('**解析**')
    assert doc['review'] == 'pending'
    with pytest.raises(ValueError, match='版本冲突'):
        w.bind_figure(doc['path'], 'stale', result['binding']['asset_id'], 5)


def test_missing_required_figure_stays_a_marked_draft(workspace, monkeypatch):
    import main
    w = workspace
    doc = w.read('chapters/01-基础.md')
    w.save(doc['path'], '# 基础\n\n### 练习 1\n\n如图所示，求电流。\n', doc['revision'])
    def compile_ok(path):
        path.with_suffix('.pdf').write_bytes(b'%PDF fixture')
        return True, 'ok'
    monkeypatch.setattr(main, 'compile_latex', compile_ok)
    w.build()
    assert w.artifact('pdf').is_file()  # A marked draft remains downloadable.
    for doc in w.documents():
        w.review(doc['path'], 'approved', doc['revision'])
    with pytest.raises(ValueError, match='条件不完整'):
        w.deliver()


def test_symlink_escape_rejected(workspace, tmp_path):
    outside = tmp_path / 'private.md'
    outside.write_text('secret')
    link = workspace.output / 'md/escape.md'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('Windows symlink privilege unavailable')
    with pytest.raises(ValueError):
        workspace.read('escape.md')
    with pytest.raises(ValueError):
        workspace.build()


@pytest.mark.parametrize('mode', ['sprint', 'comprehensive', 'practice'])
def test_real_prompt_schema_modes(mode):
    from modules.prompts import load_prompts
    from studio.engine import apply_mode, MODES
    original = load_prompts()
    book = apply_mode(original, mode)
    assert MODES[mode]['instruction'] in book.dynamic.chapter.template
    assert MODES[mode]['instruction'] in book.global_prompts.introduction.template
    assert MODES[mode]['instruction'] not in original.dynamic.chapter.template


def test_edited_h1_and_appendix_are_in_final_manuscript(workspace, monkeypatch):
    import main
    w = workspace
    chapter = w.read('chapters/01-基础.md')
    w.save(chapter['path'], '# 人工修改后的章节标题\n\n## 题型一：计算\n\n### 标准例题：加法\n\n正文', chapter['revision'])
    appendix = w.output / 'md/appendix/02-典型题型索引.md'
    appendix.parent.mkdir()
    appendix.write_text('# 人工索引标题\n\n人工添加的题型说明', encoding='utf-8')
    monkeypatch.setattr(main, 'compile_latex', lambda path: (False, 'fixture'))
    w.build()
    content = (w.output / 'handout/manuscript.md').read_text(encoding='utf-8')
    assert '# 人工修改后的章节标题' in content
    assert '人工添加的题型说明' in content


@pytest.mark.parametrize('style', ['academic', 'modern', 'warm', 'minimal'])
def test_every_style_reaches_latex_template(tmp_path, style):
    from studio.engine import make_style_config
    from modules.latex_renderer import write_latex_document
    config = make_style_config('sprint', style, '', '')
    path = tmp_path / 'test.tex'
    write_latex_document('# 标题\n\n内容', path, '测试', style=config['latex'])
    tex = path.read_text(encoding='utf-8')
    assert '{'+config['latex']['primary_color']+'}' in tex


@pytest.mark.parametrize('payload', [r'$\input{../secret.txt}$', r'$\csname input\endcsname{secret}$', r'$^^5cinput{secret}$'])
def test_unsafe_tex_is_rejected_without_losing_source(workspace, payload, monkeypatch):
    import main
    doc = workspace.read('chapters/01-基础.md')
    workspace.save(doc['path'], '# 基础\n\n' + payload, doc['revision'])
    def unexpected_compile(path):
        raise AssertionError('unsafe document reached compiler')
    monkeypatch.setattr(main, 'compile_latex', unexpected_compile)
    with pytest.raises(ValueError, match='TeX'):
        workspace.build()
    assert payload in workspace.read(doc['path'])['content']


def test_editing_partial_failed_task_does_not_mark_generation_complete(workspace):
    workspace.update(status='failed')
    doc = workspace.read('chapters/01-基础.md')
    workspace.save(doc['path'], doc['content'] + '\n人工修订', doc['revision'])
    assert workspace.state()['generation_complete'] is False


def test_windows_junction_escape_rejected(workspace, tmp_path):
    import os
    import subprocess
    from studio.engine import inventory
    if os.name != 'nt':
        pytest.skip('Windows junction test')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.md').write_text('secret')
    (outside / 'source.pdf').write_bytes(b'fixture')
    link = workspace.output / 'md/junction'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
    assert result.returncode == 0, result.stderr
    try:
        with pytest.raises(ValueError): workspace.read('junction/secret.md')
        with pytest.raises(ValueError): inventory(link)
        with pytest.raises(ValueError): workspace.build()
    finally:
        os.rmdir(link)  # Removes only this junction, never its target.
