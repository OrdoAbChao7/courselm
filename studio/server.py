"""CourseLM Studio. Personal localhost-only dashboard, no new pip dependencies."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from studio.engine import MODES, STYLES, inventory, make_style_config, safe_slug
from studio.worker import atomic_json
from studio.workspace import Workspace, confined, BUSY

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = Path(__file__).parent / "static"
JOBS = ROOT / "studio_data" / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
# Safeguard: generated personal content should never be added to a public repository.
(JOBS.parent / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
ACTIVE: dict[str, subprocess.Popen] = {}
LOCK = threading.RLock()
MAX_BODY = 2 * 1024 * 1024 + 32768


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start_worker(jobid: str, action: str):
    w = Workspace(ROOT, jobid)
    w.check_tree()
    if any(p.poll() is None for p in ACTIVE.values()):
        raise ValueError('当前已有运行中的任务，请等待或取消后再操作')
    w.idle()
    if action == 'resume' and w.state().get('generation_complete'):
        raise ValueError('生成已完成，请使用重新编译')
    w.update(status='building' if action == 'build' else 'queued', stage='等待重新编译' if action == 'build' else '等待继续生成', percent=0)
    env = {**os.environ, 'PYTHONPATH': str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', ''), 'PYTHONIOENCODING': 'utf-8'}
    try:
        with confined(ROOT, w.job / 'worker.log').open('ab') as logfile:
            ACTIVE[jobid] = subprocess.Popen([sys.executable, '-m', 'studio.worker', '--job', str(w.job), '--action', action],
                cwd=ROOT, env=env, stdout=logfile, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as exc:
        w.update(status='failed', stage='工作进程启动失败', detail=str(exc))
        raise
    return w.state()


def load_status(jobid: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{12}", jobid):
        raise ValueError("任务编号无效")
    fp = confined(ROOT, JOBS / jobid / "status.json")
    if not fp.is_file():
        raise FileNotFoundError("任务不存在")
    status = json.loads(fp.read_text(encoding="utf-8"))
    eventpath = confined(ROOT, JOBS / jobid / "events.jsonl")
    if eventpath.exists():
        status['events'] = []
        for line in eventpath.read_text(encoding='utf-8').splitlines()[-45:]:
            try:
                status['events'].append(json.loads(line))
            except ValueError:
                pass  # A worker may be appending the final event right now.
    log = confined(ROOT, JOBS / jobid / 'worker.log')
    if log.exists():
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 16000))
            status['worker_log'] = re.sub(r'\x1b\[[0-9;]*m', '', stream.read().decode('utf-8', errors='replace'))
    with LOCK:
        process = ACTIVE.get(jobid)
        if status['status'] in BUSY and (not process or process.poll() is not None):
            status.update(status='failed', failed_stage=status.get('stage'), stage='工作进程已停止', detail='进程中断或服务重启；草稿和缓存已保留，可继续生成或重新编译。')
            atomic_json(fp, {k:v for k,v in status.items() if k not in {'events', 'worker_log'}})
    return status


def create_job(data: dict) -> dict:
    course = safe_slug(str(data.get("course", "")))
    source = str(data.get("source_path", ""))
    checked = inventory(source)
    mode = str(data.get("mode", "sprint"))
    style = str(data.get("style", "academic"))
    title = str(data.get("title", ""))
    subtitle = str(data.get("subtitle", ""))
    accent = data.get("accent")
    make_style_config(mode, style, title, subtitle, accent)
    with LOCK:
        if any(p.poll() is None for p in ACTIVE.values()):
            raise ValueError("当前已有生成任务，首版只支持一次生成一份讲义")
        jobid = uuid.uuid4().hex[:12]
        jobpath = confined(ROOT, JOBS / jobid)
        jobpath.mkdir()
        course_id = f"{course}-{jobid}"
        request = {"course": course, "course_id": course_id, "source_path": checked["root"], "mode": mode,
                   "style": style, "title": title, "subtitle": subtitle, "accent": accent}
        atomic_json(jobpath / "request.json", request)
        state = {"id": jobid, "course": course, "course_id": course_id, "mode": mode, "style": style,
                 "file_count": checked["count"], "status": "queued", "stage": "等待启动", "percent": 0,
                 "detail": "", "created_at": datetime.now().isoformat(timespec="seconds"), "artifacts": {}, 'generation_complete': False}
        atomic_json(jobpath / "status.json", state)
        state['status'] = 'draft_ready'
        atomic_json(jobpath / 'status.json', state)
        state = start_worker(jobid, 'generate')
    return state


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def _local(self) -> bool:
        host = self.headers.get("Host", "").lower()
        return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _json(self, data: dict | list, status: int = 200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, error: Exception):
        if isinstance(error, FileNotFoundError):
            return self._json({"error": str(error)}, 404)
        return self._json({"error": str(error)}, 400)

    def _check_origin(self) -> bool:
        origin = self.headers.get("Origin", "")
        return not origin or origin in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self._local() or not self._check_origin():
            return self._json({"error": "仅允许本机访问"}, 403)
        uri = urlsplit(self.path)
        q = parse_qs(uri.query)
        path = uri.path
        try:
            if path == "/api/health":
                return self._json({"ok": True, "course_root": str(ROOT), "modes": {k:v["name"] for k,v in MODES.items()}, "styles": {k:v["name"] for k,v in STYLES.items()}})
            if path == "/api/scan":
                check = inventory(q.get("path", [""])[0])
                return self._json({k:v for k,v in check.items() if k != "base"})
            if path == "/api/jobs":
                entries = []
                for folder in sorted(JOBS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    if re.fullmatch(r'[a-f0-9]{12}', folder.name) and folder.is_dir() and (folder / "status.json").exists():
                        st = load_status(folder.name)
                        st.pop("events", None)
                        entries.append(st)
                    if len(entries) >= 20: break
                return self._json(entries)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/(documents|document|versions)', path)
            if match:
                jobid, action = match.groups()
                with LOCK:
                    load_status(jobid)
                    w = Workspace(ROOT, jobid)
                    relative = q.get('path', [''])[0]
                    return self._json(w.documents() if action == 'documents' else w.read(relative) if action == 'document' else w.versions(relative))
            match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})", path)
            if match:
                jobid = match.group(1)
                state = load_status(jobid)
                with LOCK:
                    p = ACTIVE.get(jobid)
                    if p and p.poll() is not None and state["status"] in ("queued", "running"):
                        state["status"] = "failed"
                        state["stage"] = "工作进程异常退出"
                        atomic_json(JOBS / jobid / "status.json", {k:v for k,v in state.items() if k != "events"})
                return self._json(state)
            match = re.fullmatch(r"/api/(download|preview)/([a-f0-9]{12})/(pdf|markdown|tex)", path)
            if match:
                disposition, jobid, kind = match.groups()
                with LOCK:
                    load_status(jobid)
                    body = Workspace(ROOT, jobid).artifact(kind).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", {"pdf": "application/pdf", "markdown": "text/markdown; charset=utf-8", "tex": "application/x-tex"}[kind])
                self.send_header("Content-Disposition", f'{"inline" if disposition == "preview" else "attachment"}; filename="courselm-{jobid}.{ {"pdf":"pdf","markdown":"md","tex":"tex"}[kind]}"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/asset/(fig_[a-f0-9]{12})', path)
            if match:
                jobid, asset_id = match.groups()
                with LOCK:
                    load_status(jobid)
                    w = Workspace(ROOT, jobid)
                    img_path = w.figure_asset_path(asset_id)
                    body = img_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/source-pdf', path)
            if match:
                jobid = match.group(1)
                rel = q.get('path', [''])[0]
                with LOCK:
                    load_status(jobid)
                    w = Workspace(ROOT, jobid)
                    pdf_path = w.source_file_path(rel)
                    body = pdf_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'inline; filename="{Path(rel).name}"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures', path)
            if match:
                jobid = match.group(1)
                with LOCK:
                    load_status(jobid)
                    w = Workspace(ROOT, jobid)
                    st = q.get('status', [None])[0]
                    src = q.get('source', [None])[0]
                    return self._json(w.figures_list(status=st, source_file=src))
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/sources', path)
            if match:
                jobid = match.group(1)
                with LOCK:
                    load_status(jobid)
                    w = Workspace(ROOT, jobid)
                    src_root = w.source_root()
                    supported = {'.pdf', '.pptx', '.ppt', '.docx', '.doc', '.png', '.jpg', '.jpeg'}
                    sources = [p.relative_to(src_root).as_posix() for p in src_root.rglob('*') if p.is_file() and p.suffix.lower() in supported]
                    return self._json(sorted(sources))
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/audit', path)
            if match:
                jobid = match.group(1)
                with LOCK:
                    load_status(jobid)
                    w = Workspace(ROOT, jobid)
                    return self._json(w.audit_figures())
            if path.startswith("/api/"):
                raise FileNotFoundError("接口不存在")
            static = confined(PUBLIC, PUBLIC / path.lstrip('/'))
            if not static.exists():
                raise FileNotFoundError('页面不存在')
            return super().do_GET()
        except Exception as e:
            return self._error(e)

    def do_POST(self):
        with LOCK:
            self._post()

    def _post(self):
        if not self._local() or not self._check_origin():
            return self._json({"error": "拒绝跨站或非本地请求"}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > MAX_BODY:
                raise ValueError("请求体长度超限")
            data = json.loads(self.rfile.read(size)) if size else {}
            if not isinstance(data, dict):
                raise ValueError('请求内容必须是对象')
            path = urlsplit(self.path).path
            if path == "/api/jobs":
                return self._json(create_job(data), 201)
            if path == "/api/browse":
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    ui = tk.Tk(); ui.withdraw(); ui.attributes("-topmost", True)
                    try:
                        selected = filedialog.askdirectory(title="选择课程资料文件夹", mustexist=True)
                    finally:
                        ui.destroy()
                    return self._json({"path": selected})
                except Exception as e:
                    return self._json({"error": "无法打开系统文件夹选择器，请手动粘贴资料路径：" + str(e)}, 503)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/scan', path)
            if match:
                jobid = match.group(1)
                load_status(jobid)
                w = Workspace(ROOT, jobid)
                return self._json(w.scan_figures(), 200)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/crop', path)
            if match:
                jobid = match.group(1)
                load_status(jobid)
                w = Workspace(ROOT, jobid)
                source_rel = data.get('source_path', '')
                page = int(data.get('page', 1))
                bbox = data.get('bbox', [0.0, 0.0, 1.0, 1.0])
                caption = str(data.get('caption', ''))
                status = str(data.get('status', 'confirmed'))
                return self._json(w.crop_figure(source_rel, page, bbox, caption, status), 201)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/bind', path)
            if match:
                jobid = match.group(1)
                load_status(jobid)
                w = Workspace(ROOT, jobid)
                return self._json(w.bind_figure(
                    data.get('path', ''), data.get('revision', ''), data.get('asset_id', ''),
                    int(data.get('cursor_line', 0)), data.get('caption')), 200)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/figures/update', path)
            if match:
                jobid = match.group(1)
                load_status(jobid)
                w = Workspace(ROOT, jobid)
                asset_id = data.get('asset_id', '')
                status = data.get('status')
                caption = data.get('caption')
                return self._json(w.update_figure(asset_id, status=status, caption=caption), 200)
            match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/(save|restore|review|deliver|build|resume)', path)
            if match:
                jobid, action = match.groups()
                load_status(jobid)
                w = Workspace(ROOT, jobid)
                relative = data.get('path', '')
                revision = data.get('revision', '')
                if action in {'build', 'resume'}:
                    return self._json(start_worker(jobid, action), 202)
                if action == 'deliver':
                    result = w.deliver()
                elif action == 'save':
                    result = w.save(relative, data.get('content'), revision)
                elif action == 'restore':
                    result = w.restore(relative, data.get('version', ''), revision)
                else:
                    result = w.review(relative, data.get('review'), revision)
                return self._json(result)
            match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/cancel", path)
            if match:
                jobid = match.group(1)
                with LOCK:
                    p = ACTIVE.get(jobid)
                    state = load_status(jobid)
                    if not p or p.poll() is not None or state["status"] not in BUSY:
                        raise ValueError("任务已停止，无法取消")
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
                    else:
                        p.terminate()
                    try: p.wait(timeout=3)
                    except subprocess.TimeoutExpired: p.kill(); p.wait()
                    state.pop("events", None)
                    state.pop('worker_log', None)
                    state.update(status="cancelled", stage="已取消", detail="用户主动停止")
                    atomic_json(JOBS / jobid / "status.json", state)
                return self._json(state)
            raise FileNotFoundError("接口不存在")
        except Exception as e:
            return self._error(e)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CourseLM Studio local dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = LocalServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"CourseLM Studio: {url}\n源项目目录: {ROOT}\nCtrl+C 停止看板", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        for process in ACTIVE.values():
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    process.terminate()
        server.server_close()


if __name__ == "__main__":
    main()
