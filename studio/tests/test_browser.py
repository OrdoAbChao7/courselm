"""Opt-in browser + real XeLaTeX acceptance against a running local Studio.

COURSELM_BROWSER_URL=http://127.0.0.1:8877
COURSELM_TEST_JOB=<id from scripts/studio_acceptance.py>
python -m pytest studio/tests/test_browser.py -q
"""
import os
from pathlib import Path

import pytest

URL = os.environ.get('COURSELM_BROWSER_URL')
JOB = os.environ.get('COURSELM_TEST_JOB')
pytestmark = pytest.mark.skipif(not URL or not JOB, reason='Opt-in live browser / XeLaTeX acceptance')


def test_edit_preview_save_recompile_review_export():
    from playwright.sync_api import sync_playwright, expect
    import re
    from studio.workspace import Workspace
    from pypdf import PdfReader
    root = Path(__file__).parents[2]
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror', lambda error: (errors.append(str(error)), print('PAGE ERROR:', str(error))))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(URL)
        page.locator(f'.history-item[data-job="{JOB}"]').click()
        page.get_by_role('button', name='打开章节编辑器').click()
        page.locator('.document-item[data-path^="chapters/"]').click()
        editor = page.get_by_role('textbox', name='Markdown 编辑区')
        expect(editor).to_have_value(re.compile(r'^# 第1章'))
        original = editor.input_value().split('\n\n## 验收修改')[0]
        text = original + '\n\n## 验收修改\n\nSTUDIO_ACCEPTANCE_42\n\n<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>\n'
        editor.fill(text)
        page.wait_for_function('() => document.querySelector("#markdown-preview").textContent.includes("STUDIO_ACCEPTANCE_42")')
        assert page.locator('#markdown-preview .katex').count() > 0
        assert page.locator('#markdown-preview table').count() > 0
        assert page.locator('#markdown-preview img, #markdown-preview script').count() == 0
        assert page.evaluate('window.__xss') is None
        page.get_by_role('button', name='保存 · Ctrl+S').click()
        page.wait_for_function('() => document.querySelector("#save-state").textContent.includes("保存成功")')
        w = Workspace(root, JOB)
        assert 'STUDIO_ACCEPTANCE_42' in w.read('chapters/01-导数.md')['content']
        page.get_by_role('button', name='保存并重新编译 PDF').click()
        page.wait_for_function('() => document.querySelector("#editor-state").textContent === "等待人工审核"', timeout=120000)
        assert w.state()['pdf_current'] is True
        pdf = w.artifact('pdf')
        extracted = '\n'.join(p.extract_text() for p in PdfReader(pdf).pages)
        assert 'STUDIO_ACCEPTANCE_42' in extracted
        for kind in ['pdf','markdown','tex']:
            response = page.request.get(URL + '/api/download/' + JOB + '/' + kind)
            assert response.ok
            assert len(response.body()) > 20
        page.get_by_role('button', name='内容预览', exact=True).click()
        for doc in w.documents():
            page.locator('.document-item').filter(has_text=doc['title']).click()
            page.locator('#review').select_option('approved')
            page.wait_for_function('() => document.querySelector("#review").value === "approved"')
            # Wait for the actual server acknowledgement, rather than only the select value.
            page.wait_for_function('() => !document.querySelector("#documents .document-item.active small").textContent.includes("待审核")')
        page.once('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='确认整份讲义可交付').click()
        page.wait_for_function('() => document.querySelector("#editor-state").textContent.includes("可交付")')
        assert w.state()['status'] == 'deliverable'
        page.locator('.document-item[data-path^="chapters/"]').click()
        shot = root / 'output/playwright/studio-editor.png'
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot), full_page=False)
        # Exercise a real TeX error, then recover without losing the draft.
        expect(editor).to_have_value(re.compile(r'^# 第1章'))
        good_text = original + '\n\n## 验收修改\n\nSTUDIO_ACCEPTANCE_42\n'
        editor.fill(good_text + '\n\n$\\undefinedStudioCommand$\n')
        page.get_by_role('button', name='保存 · Ctrl+S').click()
        page.wait_for_function('() => document.querySelector("#save-state").textContent.includes("保存成功")')
        page.get_by_role('button', name='保存并重新编译 PDF').click()
        page.wait_for_function('() => document.querySelector("#editor-state").textContent === "PDF 编译失败"', timeout=120000)
        assert 'undefinedStudioCommand' in w.read('chapters/01-导数.md')['content']
        assert 'Undefined control sequence' in w.state()['compile_log']
        assert not page.request.get(URL + '/api/download/' + JOB + '/pdf').ok
        editor.fill(good_text)
        page.get_by_role('button', name='保存 · Ctrl+S').click()
        page.wait_for_function('() => document.querySelector("#save-state").textContent.includes("保存成功")')
        page.get_by_role('button', name='保存并重新编译 PDF').click()
        page.wait_for_function('() => document.querySelector("#editor-state").textContent === "等待人工审核"', timeout=120000)
        assert w.state()['pdf_current'] is True
        assert not errors, errors
        browser.close()
