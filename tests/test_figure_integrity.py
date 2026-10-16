"""Production regression tests: unknown images must never reach a handout."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from modules.figure_models import FigureAsset, FigureManifest, ExtractionType, ReviewStatus
from modules.figure_matcher import FigureMatcher
from modules.handout_builder import build_handout, _sync_handout_figures


def test_manifest_rejects_foreign_scope(tmp_path):
    path = tmp_path / 'manifest.json'
    FigureManifest(task_id='A', course='Signals').save(path)
    with pytest.raises(ValueError, match='任务|scope'):
        FigureManifest.load(path, 'B', 'Signals')


def test_corrupt_manifest_is_not_silently_reset(tmp_path):
    path = tmp_path / 'manifest.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        FigureManifest.load(path, 'A')


def test_existing_unregistered_file_does_not_pass_audit(tmp_path):
    Image.new('RGB', (20, 20)).save(tmp_path / 'unknown.png')
    report = FigureMatcher(FigureManifest(task_id='A')).audit_handout(
        '![题图](unknown.png)', tmp_path)
    assert report.valid_source_figures == 0
    assert not report.audit_passed


def test_matcher_does_not_recommend_foreign_task():
    manifest = FigureManifest(task_id='A')
    # Also guard loaded/legacy malformed manifests, without relying on add().
    manifest.figures['bad'] = FigureAsset(
        asset_id='bad', task_id='B', extraction_type=ExtractionType.EMBEDDED,
        width=200, height=200, caption='电路', adjacent_text='电路')
    assert FigureMatcher(manifest).match_question('电路中电阻为20Ω，求电流') == []


def test_sync_does_not_copy_unreferenced_library(tmp_path):
    root = tmp_path / 'output' / 'Signals'
    (root / 'figures').mkdir(parents=True)
    (root / 'figures' / 'watermark.png').write_bytes(b'not-for-publication')
    _sync_handout_figures(root, root / 'handout', '# 无图课程')
    assert not (root / 'handout' / 'figures' / 'watermark.png').exists()


def test_build_omits_unknown_images_without_altering_source(tmp_path):
    output = tmp_path / 'output'
    root = output / 'Signals'
    (root / 'md' / 'chapters').mkdir(parents=True)
    (root / 'figures').mkdir()
    source = root / 'md' / 'chapters' / '01-test.md'
    text = ('# 第一章\n\n| 考点 | 分值 |\n| --- | --- |\n| 电路 | 8 |\n'
            '| 波形 | 9 |\n\n文字与公式 $x=1$。![水印](figures/logo.png)\n\n'
            '```markdown\n![代码示例](figures/example.png)\n```\n')
    source.write_text(text, encoding='utf-8')
    (root / 'figures' / 'logo.png').write_bytes(b'unregistered')
    result = build_handout('Signals', output, courses_dir=tmp_path / 'courses')
    manuscript = result.manuscript_path.read_text(encoding='utf-8')
    assert '![水印]' not in manuscript
    assert '文字与公式 $x=1$。' in manuscript
    assert '| 电路 | 8 |\n| 波形 | 9 |' in manuscript
    assert '![代码示例](figures/example.png)' in manuscript
    assert source.read_text(encoding='utf-8') == text
    assert (root / 'handout' / 'figure-report.json').is_file()


@pytest.fixture
def bound_course(tmp_path):
    from modules.figure_integrity import bind_figure
    root = tmp_path / 'output' / 'Signals'
    sources = tmp_path / 'courses' / 'Signals'
    sources.mkdir(parents=True)
    (root / 'figures').mkdir(parents=True)
    image = Image.new('RGB', (400, 240), 'white')
    draw = ImageDraw.Draw(image)
    draw.line([(30, 180), (30, 30), (350, 30), (350, 180), (30, 180)], fill='black', width=3)
    draw.text((90, 38), 'R1=20 ohm', fill='black')
    image.save(sources / 'original.png')
    data = (sources / 'original.png').read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    aid = 'fig_' + sha[:12]
    (root / 'figures' / (aid + '.png')).write_bytes(data)
    manifest = FigureManifest(task_id='course_Signals', course='Signals')
    manifest.add(FigureAsset(
        asset_id=aid, task_id=manifest.task_id, source_file='original.png',
        source_sha256=sha, image_sha256=sha, image_rel_path=f'figures/{aid}.png',
        extraction_type=ExtractionType.STANDALONE, width=400, height=240,
        caption='原始电路图', status=ReviewStatus.CONFIRMED))
    text = ('# 第一章\n\n### 例题 1\n\n已知电路中 R1=20Ω，求支路电流。\n\n'
            '**解析**\n\n使用欧姆定律。\n')
    binding = bind_figure(manifest, aid, text, 'chapters/01-test.md', 5,
                          source_root=sources, figure_root=root)
    manifest.save(root / 'figures' / 'manifest.json')
    return root, sources, manifest, text, binding


def test_exact_binding_is_reused_before_solution_and_is_idempotent(bound_course):
    from modules.figure_integrity import prepare_markdown
    root, sources, manifest, text, binding = bound_course
    result = prepare_markdown(text, 'chapters/01-test.md', manifest,
                              figure_root=root, source_root=sources)
    assert result.inserted == 1
    assert result.markdown.index('![原始电路图]') < result.markdown.index('**解析**')
    repeated = prepare_markdown(result.markdown, 'chapters/01-test.md', manifest,
                                figure_root=root, source_root=sources)
    assert repeated.markdown == result.markdown
    assert not repeated.omissions


@pytest.mark.parametrize('change', ['parameter', 'source', 'image', 'caption', 'rejected'])
def test_changed_binding_evidence_is_automatically_omitted(bound_course, change):
    from modules.figure_integrity import prepare_markdown
    root, sources, manifest, text, binding = bound_course
    if change == 'parameter':
        text = text.replace('20Ω', '200Ω')
    elif change == 'source':
        (sources / 'original.png').write_bytes(b'changed')
    elif change == 'image':
        (root / manifest.get(binding.asset_id).image_rel_path).write_bytes(b'changed')
    elif change == 'caption':
        manifest.get(binding.asset_id).caption = 'different description'
    else:
        manifest.get(binding.asset_id).status = ReviewStatus.REJECTED
    result = prepare_markdown(text, 'chapters/01-test.md', manifest,
                              figure_root=root, source_root=sources)
    assert result.inserted == 0
    assert '![' not in result.markdown
    assert result.omissions


def test_binding_cannot_be_created_in_table_or_code(bound_course):
    from modules.figure_integrity import bind_figure
    root, sources, manifest, text, binding = bound_course
    bad = '# 第一章\n\n| 电路 | 分值 |\n| --- | --- |\n| 例题 | 8 |\n'
    with pytest.raises(ValueError):
        bind_figure(manifest, binding.asset_id, bad, 'chapters/02.md', 5,
                    source_root=sources, figure_root=root)


def test_reference_images_and_inline_code_are_handled_separately(tmp_path):
    from modules.figure_integrity import prepare_markdown
    text = '`![保留](x.png)`\n\n![省略][original]\n\n[original]: x.png\n'
    result = prepare_markdown(text, '01.md', FigureManifest(task_id='A'),
                              figure_root=tmp_path, source_root=tmp_path)
    assert '`![保留](x.png)`' in result.markdown
    assert '![省略]' not in result.markdown
    assert len(result.omissions) == 1


def test_build_automatically_inserts_persisted_binding(bound_course):
    root, sources, manifest, text, binding = bound_course
    chapters = root / 'md' / 'chapters'
    chapters.mkdir(parents=True)
    (chapters / '01-test.md').write_text(text, encoding='utf-8')
    result = build_handout('Signals', root.parent, courses_dir=sources.parent)
    assert '![原始电路图]' in result.manuscript_path.read_text(encoding='utf-8')
    assert (root / 'handout' / manifest.get(binding.asset_id).image_rel_path).is_file()


def test_gradient_is_not_a_figure():
    from modules.figure_extractor import is_blank_image
    gradient = Image.new('RGB', (256, 256))
    gradient.putdata([(80 + y // 3, 120 + y // 3, 180 + y // 4)
                      for y in range(256) for x in range(256)])
    assert is_blank_image(gradient)


def test_batch_script_does_not_inject_by_keyword(tmp_path):
    from scripts.batch_remake_handouts import enhance_markdown_with_figures
    root = tmp_path / 'Signals'
    chapters = root / 'md' / 'chapters'
    chapters.mkdir(parents=True)
    path = chapters / '01.md'
    text = '| 考点 | 分值 |\n| --- | --- |\n| 电路 | 8 |\n| 波形 | 9 |\n'
    path.write_text(text, encoding='utf-8')
    manifest = FigureManifest(task_id='A')
    manifest.add(FigureAsset(asset_id='fig_000000000001', task_id='A',
        extraction_type=ExtractionType.EMBEDDED, width=300, height=200,
        caption='电路', adjacent_text='电路', status=ReviewStatus.CONFIRMED))
    assert enhance_markdown_with_figures(root, manifest) == 0
    assert path.read_text(encoding='utf-8') == text


def test_legacy_image_split_table_is_rejoined_without_losing_rows(tmp_path):
    from modules.figure_integrity import prepare_markdown
    text = ('| 考点 | 分值 |\n| --- | --- |\n| 电路 | 8 |\n\n'
            '![装饰](figures/logo.png)\n\n| 波形 | 9 |\n| 光路 | 6 |\n')
    result = prepare_markdown(text, '01.md', FigureManifest(task_id='A'),
                              figure_root=tmp_path, source_root=tmp_path)
    assert '| 电路 | 8 |\n| 波形 | 9 |\n| 光路 | 6 |' in result.markdown
    assert result.markdown.index('配图待补') > result.markdown.index('| 光路 | 6 |')


def test_audit_rejects_picture_moved_to_another_question(bound_course):
    root, sources, manifest, text, binding = bound_course
    from modules.figure_integrity import copy_bound_figures
    relative = manifest.get(binding.asset_id).image_rel_path
    copy_bound_figures(root, root / 'handout', {relative: binding.image_sha256})
    wrong = text + f'\n### 例题 2\n\n这是另一道题目，参数不同。\n\n![图]({relative})\n'
    report = FigureMatcher(manifest).audit_handout(wrong, root / 'handout', source_root=sources)
    assert not report.audit_passed
    assert report.valid_source_figures == 0


def test_audit_accepts_current_binding_and_rejects_changed_source(bound_course):
    from modules.figure_integrity import prepare_markdown, copy_bound_figures
    root, sources, manifest, text, binding = bound_course
    result = prepare_markdown(text, 'chapters/01-test.md', manifest,
                              figure_root=root, source_root=sources)
    copy_bound_figures(root, root / 'handout', result.assets)
    matcher = FigureMatcher(manifest)
    report = matcher.audit_handout(result.markdown, root / 'handout', source_root=sources)
    assert report.audit_passed
    assert report.valid_source_figures == 1
    (sources / 'original.png').write_bytes(b'changed source')
    assert not matcher.audit_handout(result.markdown, root / 'handout', source_root=sources).audit_passed


@pytest.mark.parametrize('syntax', [
    '~~~markdown\n![保留](x.png)\n~~~\n',
    '$$\n\\text{![保留](x.png)}\n$$\n',
    '这是行内代码 `![保留](x.png)`，还有数学 $x=1$。\n',
])
def test_protected_blocks_are_unchanged(tmp_path, syntax):
    from modules.figure_integrity import prepare_markdown
    result = prepare_markdown(syntax, '01.md', FigureManifest(task_id='A'),
                              figure_root=tmp_path, source_root=tmp_path)
    assert result.markdown == syntax


def test_picture_in_table_is_removed_but_code_in_other_cell_is_preserved(tmp_path):
    from modules.figure_integrity import prepare_markdown
    text = '| 示例 | 图 |\n| --- | --- |\n| `![x](x.png)` | ![x](x.png) |\n'
    result = prepare_markdown(text, '01.md', FigureManifest(task_id='A'),
                              figure_root=tmp_path, source_root=tmp_path)
    assert '| `![x](x.png)` | （配图待补） |' in result.markdown


def test_required_figure_is_reported_without_selecting_a_nearby_picture(tmp_path):
    root = tmp_path / 'output' / 'Signals'
    chapters = root / 'md' / 'chapters'
    chapters.mkdir(parents=True)
    (chapters / '01.md').write_text(
        '# 基础\n\n### 练习 1\n\n如图所示，求电路中的支路电流。\n\n**解析**\n\n略。', encoding='utf-8')
    result = build_handout('Signals', root.parent, courses_dir=tmp_path / 'courses')
    import json
    report = json.loads((root / 'handout' / 'figure-report.json').read_text(encoding='utf-8'))
    assert report['required_missing'] == 1
    assert '配图待补' in result.manuscript_path.read_text(encoding='utf-8')
    assert report['inserted'] == 0


def test_table_escaped_pipe_cannot_move_image_span_into_inline_code(tmp_path):
    from modules.figure_integrity import prepare_markdown
    text = '| `a \\| ![x](a.png)` | ![x](a.png) |\n| --- | --- |\n'
    result = prepare_markdown(text, '01.md', FigureManifest(task_id='A'),
                              figure_root=tmp_path, source_root=tmp_path)
    assert '`a \\| ![x](a.png)`' in result.markdown
    assert result.markdown.count('![x](a.png)') == 1


def test_multiline_old_image_cannot_shift_binding_to_next_question(bound_course):
    from modules.figure_integrity import bind_figure, questions
    root, sources, manifest, original, binding = bound_course
    text = ('![x](\n a.png\n)\n\n### 例题 1\n\n'
            'First question long enough to bind.\n\n### 例题 2\n\n'
            'Second question long enough to bind.\n')
    new_binding = bind_figure(manifest, binding.asset_id, text, 'chapters/02.md', 7,
                              source_root=sources, figure_root=root)
    assert new_binding.question_sha256 == questions(text)[0].fingerprint


def test_reference_definition_outside_question_does_not_change_fingerprint(bound_course):
    from modules.figure_integrity import bind_figure, prepare_markdown
    root, sources, manifest, original, binding = bound_course
    text = ('### 例题 1\n\nFirst question long enough to bind.\n\n![old][a]\n\n'
            '**解析**\n\nSolution.\n\n[a]: old.png\n')
    bind_figure(manifest, binding.asset_id, text, 'chapters/02.md', 3,
                source_root=sources, figure_root=root)
    result = prepare_markdown(text, 'chapters/02.md', manifest,
                              figure_root=root, source_root=sources)
    assert result.inserted == 1


@pytest.mark.parametrize('text', [
    '~~~markdown\n![literal](figures/unknown.png)\n~~~\n',
    '    ![literal](figures/unknown.png)\n',
    '````markdown\n```\n![literal](figures/unknown.png)\n````\n',
    '`start\n![literal](figures/unknown.png)\nend`\n',
    '<!--\n![literal](figures/unknown.png)\n-->\n',
    '$$\n\n![literal](figures/unknown.png)\n$$\n',
])
def test_renderer_never_promotes_literal_code_to_an_image(text):
    from modules.latex_renderer import render_markdown_to_latex
    assert '\\includegraphics' not in render_markdown_to_latex(text)


def test_cross_document_reference_cannot_activate_unbound_image(tmp_path):
    from modules.figure_integrity import image_references
    root = tmp_path / 'output' / 'Signals'
    chapters = root / 'md' / 'chapters'
    chapters.mkdir(parents=True)
    (chapters / '01.md').write_text('# First\n\n![unknown][crossdoc]\n', encoding='utf-8')
    (chapters / '02.md').write_text('# Second\n\n[crossdoc]: figures/unknown.png\n', encoding='utf-8')
    (root / 'handout' / 'figures').mkdir(parents=True)
    (root / 'handout' / 'figures' / 'unknown.png').write_bytes(b'old asset')
    result = build_handout('Signals', root.parent, courses_dir=tmp_path / 'courses')
    assert image_references(result.manuscript_path.read_text(encoding='utf-8')) == []


def test_bound_handout_real_xelatex_compilation(bound_course):
    """Exercise source binding → builder → copied original → actual XeLaTeX."""
    import shutil
    if not shutil.which('xelatex'):
        pytest.skip('XeLaTeX unavailable')
    from main import compile_latex
    from modules.latex_renderer import write_latex_document
    root, sources, manifest, text, binding = bound_course
    chapters = root / 'md' / 'chapters'
    chapters.mkdir(parents=True)
    (chapters / '01.md').write_text(text, encoding='utf-8')
    # Bindings are scoped to the exact relative source-document path.
    (chapters / '01.md').rename(chapters / '01-test.md')
    result = build_handout('Signals', root.parent, courses_dir=sources.parent)
    write_latex_document(result.manuscript_path.read_text(encoding='utf-8'), result.tex_path,
                         '原图绑定回归测试')
    ok, log = compile_latex(result.tex_path)
    assert ok, log
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(result.tex_path.with_suffix('.pdf')) as pdf:
        count = sum(obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE
                    for page in pdf for obj in page.get_objects())
        assert count >= 1
