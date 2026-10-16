"""Real localhost HTTP requests; no NotebookLM or browser required."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from studio.tests.test_workspace import workspace


@pytest.fixture
def http(workspace, monkeypatch):
    from studio import server
    monkeypatch.setattr(server, 'ROOT', workspace.root)
    monkeypatch.setattr(server, 'JOBS', workspace.job.parent)
    monkeypatch.setattr(server, 'ACTIVE', {})
    instance = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(instance.server_port)
    def request(path, data=None, origin=None):
        headers = {'Content-Type':'application/json'}
        if origin:
            headers['Origin'] = origin
        req = Request(base + path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
        try:
            with urlopen(req) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)
    yield request, workspace
    instance.shutdown()
    instance.server_close()
    thread.join()


def test_history_document_edit_conflict_and_cross_task(http):
    from urllib.parse import quote
    request, w = http
    prefix = '/api/jobs/' + w.job.name
    code, jobs = request('/api/jobs')
    assert code == 200 and jobs[0]['id'] == w.job.name
    code, docs = request(prefix + '/documents')
    assert code == 200 and len(docs) == 2
    path = 'chapters/01-基础.md'
    _, doc = request(prefix + '/document?path=' + quote(path))
    payload = {'path':path, 'revision':doc['revision'], 'content':'# 网络编辑\n\n已保存'}
    assert request(prefix + '/save', payload)[0] == 200
    assert request(prefix + '/save', payload)[0] == 400
    assert '已保存' in w.read(path)['content']
    assert request(prefix + '/document?path=' + quote('../../demo-bbbbbbbbbbbb/md/secret.md'))[0] == 400
    assert request('/api/jobs/bbbbbbbbbbbb/documents')[0] == 404
    assert request(prefix + '/save', payload, origin='https://evil.example')[0] == 403
    assert request('/api/scan?path=' + quote(str(w.root)), origin='https://evil.example')[0] == 403


def test_create_same_course_isolated_and_does_not_touch_original(http, monkeypatch):
    from studio import server
    request, w = http
    source = w.root / 'input'
    source.mkdir()
    original = source / 'notes.pdf'
    original.write_bytes(b'%PDF fixture')
    monkeypatch.setattr(server, 'start_worker', lambda jobid, action: server.Workspace(server.ROOT, jobid).state())
    payload = {'course':'同名课程', 'source_path':str(source), 'mode':'practice', 'style':'warm'}
    code, first = request('/api/jobs', payload)
    code2, second = request('/api/jobs', payload)
    assert code == code2 == 201
    assert first['course_id'] != second['course_id']
    assert original.read_bytes() == b'%PDF fixture'
    assert request('/api/jobs', {**payload, 'mode':'invalid'})[0] == 400


def test_progress_from_artifacts_and_interrupted_task(http):
    from studio.worker import atomic_json
    request, w = http
    state = w.state()
    state.update(status='running', stage='绪论生成')
    atomic_json(w.job / 'status.json', state)
    code, state = request('/api/jobs/' + w.job.name)
    assert code == 200 and state['status'] == 'failed'
    assert state['failed_stage'] == '绪论生成'


def test_folder_picker_uses_native_dialog_and_disposes_it(http, monkeypatch):
    import sys
    import types
    request, w = http
    actions = []
    ui = types.SimpleNamespace(withdraw=lambda: actions.append('withdraw'),
        attributes=lambda *args: None, destroy=lambda: actions.append('destroy'))
    dialog = types.SimpleNamespace(askdirectory=lambda **kwargs: str(w.root))
    monkeypatch.setitem(sys.modules, 'tkinter', types.SimpleNamespace(Tk=lambda: ui, filedialog=dialog))
    code, data = request('/api/browse', {})
    assert code == 200 and data['path'] == str(w.root)
    assert actions == ['withdraw', 'destroy']
