"""Task-scoped editable Markdown, version history and reproducible PDF builds.

HTTP mutations are serialized by server.LOCK; workers run only while a task is
busy. No browser-supplied path is ever used outside the task's md directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

BUSY = {'queued', 'running', 'building'}


def atomic_write(path: Path, content: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.studio-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content.encode('utf-8') if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def is_link(path: Path) -> bool:
    """Also recognize Windows junctions on Python 3.11 (no is_junction API)."""
    try:
        tag = getattr(path.lstat(), 'st_reparse_tag', 0)
        return path.is_symlink() or tag in {0xA0000003, 0xA000000C}
    except FileNotFoundError:
        return False


def confined(root: Path, path: Path) -> Path:
    root, path = root.absolute(), path.absolute()
    if not path.is_relative_to(root):
        raise ValueError('文件路径越界')
    for item in (path, *path.parents):
        if is_link(item):
            raise ValueError('不允许符号链接或目录联接')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('文件路径越界')
    return path


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_tex_source(content: str, name: str):
    """Studio accepts math, not raw TeX programs or file access primitives."""
    dangerous = re.compile(r'\\(?:input|include\w*|openin|openout|read\w*|write\w*|csname|endcsname|[egx]?def|let|futurelet|catcode|scantokens|usepackage|documentclass|(?:re)?newcommand|(?:re)?newenvironment|directlua|special|immediate|every\w*|loop|repeat|pdf\w*|XeTeX\w*|shell\w*|expandafter|noexpand|endlinechar|escapechar|@\w*)\b|\^\^')
    match = dangerous.search(content)
    if match:
        line = content[:match.start()].count('\n') + 1
        raise ValueError(f'{name}:{line}: 禁止使用文件访问或程序控制 TeX 指令 {match.group()}')
    environments = {'matrix', 'pmatrix', 'bmatrix', 'Bmatrix', 'vmatrix', 'Vmatrix', 'smallmatrix',
                    'array', 'aligned', 'align', 'align*', 'alignedat', 'gathered', 'gather', 'gather*',
                    'cases', 'equation', 'equation*', 'split', 'subequations', 'multline', 'multline*'}
    for match in re.finditer(r'\\(?:begin|end)\s*\{([^}]+)\}', content):
        if match.group(1) not in environments:
            raise ValueError(f'{name}: 不支持该 TeX 环境：{match.group(1)}；请使用 Markdown 或标准数学环境')


class Workspace:
    def __init__(self, root: Path, jobid: str):
        if not re.fullmatch(r'[a-f0-9]{12}', jobid):
            raise ValueError('任务编号无效')
        self.root = root.absolute()
        self.job = confined(self.root, self.root / 'studio_data/jobs' / jobid)
        state = self.state()
        course = state['course_id']
        if not re.fullmatch(r'[\w-]+-[a-f0-9]{6,12}', course) or not (course.endswith('-' + jobid) or course.endswith('-' + jobid[:6])):
            raise ValueError('任务目录标识无效')
        self.course_id = course
        self.output = confined(self.root, self.root / 'output' / course)
        self.course = confined(self.root, self.root / 'courses' / course)

    def state(self):
        return json.loads(confined(self.root, self.job / 'status.json').read_text(encoding='utf-8'))

    def update(self, **changes):
        state = self.state()
        state.update(changes, updated_at=datetime.now().isoformat(timespec='seconds'))
        write_json(confined(self.root, self.job / 'status.json'), state)
        return state

    def idle(self):
        if self.state()['status'] in BUSY:
            raise ValueError('任务正在生成或编译，请等待结束后操作')

    def check_tree(self):
        for base in (self.output, self.course, self.job):
            confined(self.root, base)
            if base.exists():
                for path in base.rglob('*'):
                    confined(base, path)

    def doc_path(self, relative: str):
        if not isinstance(relative, str) or '\\' in relative or ':' in relative:
            raise ValueError('文件路径无效')
        rel = PurePosixPath(relative)
        if rel.is_absolute() or '..' in rel.parts or rel.suffix != '.md':
            raise ValueError('只能访问本任务的 Markdown 文件')
        return confined(self.output / 'md', self.output / 'md' / relative)

    def metadata(self):
        path = confined(self.root, self.job / 'editor.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def documents(self):
        base = confined(self.root, self.output / 'md')
        docs = []
        for path in sorted(base.rglob('*.md')) if base.exists() else []:
            doc = self.read(path.relative_to(base).as_posix())
            docs.append({k: v for k, v in doc.items() if k != 'content'})
        return docs

    def read(self, relative):
        path = self.doc_path(relative)
        content = path.read_bytes()
        revision = digest(content)
        meta = self.metadata().get(relative, {})
        return {'path': relative, 'title': path.stem, 'content': content.decode('utf-8'),
                'revision': revision, 'review': meta.get('review', 'pending') if meta.get('revision') == revision else 'pending'}

    def fingerprint(self):
        values = [(d['path'], d['revision']) for d in self.documents()]
        style = confined(self.root, self.course / 'handout.yaml')
        figure_evidence = []
        manifest_path = self.output / 'figures' / 'manifest.json'
        if manifest_path.exists():
            from modules.figure_integrity import local_file
            manifest = self.figures_manifest()
            figure_evidence.append(digest(manifest_path.read_bytes()))
            for binding in sorted(manifest.bindings.values(), key=lambda b: b.binding_id):
                asset = manifest.get(binding.asset_id)
                for base, relative in ((self.output, asset.image_rel_path if asset else ''),
                                       (self.source_root(), binding.source_file)):
                    path = local_file(base, relative)
                    if path.is_file():
                        checksum = hashlib.sha256()
                        with path.open('rb') as stream:
                            while chunk := stream.read(65536):
                                checksum.update(chunk)
                        figure_evidence.append((relative, checksum.hexdigest()))
                    else:
                        figure_evidence.append((relative, 'MISSING'))
        return digest(json.dumps([values, figure_evidence]).encode() +
                      (style.read_bytes() if style.exists() else b''))

    def save(self, relative, content, revision):
        self.idle()
        if not isinstance(content, str) or len(content.encode('utf-8')) > 2 * 1024 * 1024:
            raise ValueError('单篇 Markdown 最大 2 MB')
        old = self.read(relative)
        if revision != old['revision']:
            raise ValueError('版本冲突：文件已被修改，请先复制当前草稿，再重新加载')
        if old['content'] == content:
            return old
        history = confined(self.root, self.job / 'versions' / digest(relative.encode()))
        backup = confined(self.root, history / (uuid.uuid4().hex + '.md'))
        atomic_write(backup, old['content'])
        atomic_write(self.doc_path(relative), content)
        meta = self.metadata()
        meta[relative] = {'revision': digest(content.encode()), 'review': 'pending'}
        write_json(confined(self.root, self.job / 'editor.json'), meta)
        state = self.state()
        generated = state.get('generation_complete', state['status'] in {'review_ready', 'draft_ready', 'deliverable'})
        self.update(status='draft_ready', stage='内容已修改，等待重新编译', pdf_current=False,
                    artifacts={}, delivered_at=None, generation_complete=generated)
        return self.read(relative)

    def versions(self, relative):
        self.read(relative)
        base = confined(self.root, self.job / 'versions' / digest(relative.encode()))
        return [{'id': p.stem, 'time': datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds')}
                for p in sorted(base.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
                if confined(base, p).is_file()]

    def restore(self, relative, version, revision):
        if not re.fullmatch(r'[a-f0-9]{32}', version):
            raise ValueError('版本编号无效')
        path = confined(self.root, self.job / 'versions' / digest(relative.encode()) / (version + '.md'))
        return self.save(relative, path.read_bytes().decode('utf-8'), revision)

    def review(self, relative, value, revision):
        self.idle()
        if value not in {'pending', 'approved', 'changes'}:
            raise ValueError('审核状态无效')
        doc = self.read(relative)
        if doc['revision'] != revision:
            raise ValueError('版本冲突，请重新加载后审核')
        meta = self.metadata()
        meta[relative] = {'revision': revision, 'review': value}
        write_json(confined(self.root, self.job / 'editor.json'), meta)
        if self.state()['status'] == 'deliverable':
            self.update(status='review_ready', delivered_at=None)
        return self.read(relative)

    def deliver(self):
        self.idle()
        docs = self.documents()
        if not docs or any(d['review'] != 'approved' for d in docs):
            raise ValueError('请先审核通过全部章节与文件')
        self.artifact('pdf')
        report_path = self.output / 'handout' / 'figure-report.json'
        if not report_path.is_file():
            raise ValueError('缺少本次题图构建报告，请重新编译')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('required_missing'):
            raise ValueError('仍有依赖原图的题目条件不完整；可导出带标记草稿，补齐或改写后再交付')
        return self.update(status='deliverable', stage='人工审核通过 · 可交付', delivered_at=datetime.now().isoformat())

    def artifact(self, kind):
        self.idle()
        state = self.state()
        if state.get('built_revision') != self.fingerprint():
            raise ValueError('内容已修改或尚未构建，请重新编译后导出')
        paths = {'markdown': 'handout/manuscript.md', 'tex': 'handout/main.tex', 'pdf': 'release/讲义成品.pdf'}
        if kind not in paths:
            raise ValueError('未知导出类型')
        if kind == 'pdf' and not state.get('pdf_current'):
            raise ValueError('当前版本的 PDF 尚未编译成功')
        path = confined(self.output, self.output / paths[kind])
        if not path.is_file():
            raise FileNotFoundError('尚未生成该文件')
        return path

    def build(self):
        """Called in a worker after server marks the job busy; never regenerate md."""
        from modules.handout_builder import build_handout
        from modules.latex_renderer import write_latex_document
        from main import compile_latex
        self.check_tree()
        revision = self.fingerprint()
        self.update(status='building', stage='重新组装 Markdown', pdf_current=False, artifacts={}, delivered_at=None)
        try:
            for doc in self.documents():
                validate_tex_source(self.read(doc['path'])['content'], doc['path'])
            result = build_handout(self.course_id, self.root / 'output', courses_dir=self.root / 'courses',
                                   prefer_source_titles=True, rebuild_question_index=False,
                                   figure_task_id=self.job.name, figure_course=self.state()['course'],
                                   figure_source_dir=self.source_root())
            if result.missing_inputs:
                raise ValueError('缺少讲义输入：' + ', '.join(result.missing_inputs))
            state = self.state()
            figure_report = json.loads((self.output / 'handout' / 'figure-report.json').read_text(encoding='utf-8'))
            self.update(figure_inserted=figure_report['inserted'], figure_omitted=figure_report['omitted'],
                        figure_required_missing=figure_report['required_missing'])
            write_latex_document(result.manuscript_path.read_text(encoding='utf-8'), result.tex_path,
                                 state['course'] + result.template.title_suffix,
                                 subtitle=result.template.subtitle, style=result.template.latex)
            self.update(stage='LaTeX 编译', built_revision=revision,
                        artifacts={'markdown': True, 'tex': True})
            ok, log = compile_latex(result.tex_path)
            atomic_write(confined(self.output, result.tex_path.with_suffix('.log')), log)
            if revision != self.fingerprint():
                raise ValueError('编译期间源文件发生变化，请重新编译')
            if ok:
                target = confined(self.output, self.output / 'release/讲义成品.pdf')
                atomic_write(target, result.tex_path.with_suffix('.pdf').read_bytes())
            return self.update(status='review_ready' if ok else 'draft_ready',
                               stage='等待人工审核' if ok else 'PDF 编译失败', compile_log=log,
                               pdf_current=ok, built_revision=revision, percent=100,
                               detail='核查公式、例题答案、事实来源及版权。' if ok else log[-2000:],
                               artifacts={'markdown': True, 'tex': True, **({'pdf': True} if ok else {})})
        except Exception as exc:
            self.update(status='draft_ready', stage='讲义构建失败', detail=str(exc), compile_log=str(exc), pdf_current=False)
            raise

    def source_root(self) -> Path:
        if self.course.is_dir() and any(p for p in self.course.iterdir() if p.name != 'handout.yaml'):
            return self.course
        req_path = confined(self.root, self.job / 'request.json')
        if not req_path.is_file():
            raise FileNotFoundError('任务请求配置不存在')
        data = json.loads(req_path.read_text(encoding='utf-8'))
        src = Path(data.get('source_path', '')).resolve()
        if not src.is_dir():
            raise FileNotFoundError(f'资料源目录不存在: {src}')
        return src

    def source_file_path(self, relative: str) -> Path:
        if not isinstance(relative, str) or '\\' in relative or ':' in relative:
            raise ValueError('源文件路径格式无效')
        rel = PurePosixPath(relative)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('文件路径越界')
        src_root = self.source_root()
        target = confined(src_root, src_root / rel)
        if not target.is_file():
            raise FileNotFoundError(f'源文件不存在: {relative}')
        return target

    def figures_manifest(self):
        from modules.figure_models import FigureManifest
        manifest_path = self.output / 'figures' / 'manifest.json'
        return FigureManifest.load(manifest_path, self.job.name, self.state().get('course', ''))

    def figures_list(self, status: str | None = None, source_file: str | None = None):
        from modules.figure_models import ReviewStatus
        st = ReviewStatus(status) if status else None
        manifest = self.figures_manifest()
        return [f.model_dump() for f in manifest.list_figures(status=st, source_file=source_file)]

    def scan_figures(self, check_idle: bool = True):
        if check_idle:
            self.idle()
        from modules.figure_extractor import FigureExtractor
        manifest = self.figures_manifest()
        extractor = FigureExtractor(target_dpi=300)
        source_dir = self.source_root()
        extractor.scan_and_extract_directory(source_dir, self.output, self.job.name, manifest)
        return [f.model_dump() for f in manifest.list_figures()]

    def crop_figure(self, source_rel: str, page_index: int, bbox_coords: list[float], caption: str = '', status: str = 'confirmed'):
        self.idle()
        from modules.figure_extractor import FigureExtractor
        from modules.figure_models import BoundingBox, ReviewStatus, ExtractionType
        if len(bbox_coords) != 4:
            raise ValueError('选区坐标必须包含 4 个数值 [x0, y0, x1, y1]')
        source_path = self.source_file_path(source_rel)
        manifest = self.figures_manifest()
        extractor = FigureExtractor(target_dpi=300)
        bbox = BoundingBox(x0=bbox_coords[0], y0=bbox_coords[1], x1=bbox_coords[2], y1=bbox_coords[3])
        rev_status = ReviewStatus(status) if status in ReviewStatus.__members__.values() else ReviewStatus.CONFIRMED
        asset = extractor.crop_pdf_region(
            pdf_path=source_path,
            page_index=page_index,
            bbox=bbox,
            task_figures_dir=self.output / 'figures',
            task_id=self.job.name,
            rel_source_path=source_rel,
            manifest=manifest,
            dpi=300,
            caption=caption,
            status=rev_status,
            extraction_type=ExtractionType.CROPPED,
        )
        if not asset:
            raise ValueError('裁剪生成图片失败，可能选区过小或全为空白')
        manifest.save(self.output / 'figures' / 'manifest.json')
        return asset.model_dump()

    def update_figure(self, asset_id: str, status: str | None = None, caption: str | None = None):
        self.idle()
        from modules.figure_models import ReviewStatus
        manifest = self.figures_manifest()
        asset = manifest.get(asset_id)
        if not asset:
            raise FileNotFoundError(f'未找到题图资产: {asset_id}')
        if status:
            asset.status = ReviewStatus(status)
        if caption is not None:
            asset.caption = caption.strip()
        manifest.save(self.output / 'figures' / 'manifest.json')
        self.update(pdf_current=False, delivered_at=None, artifacts={})
        return asset.model_dump()

    def bind_figure(self, relative: str, revision: str, asset_id: str, cursor_line: int,
                    caption: str | None = None):
        """Selecting a source for one question creates a reusable explicit binding."""
        self.idle()
        document = self.read(relative)
        if document['revision'] != revision:
            raise ValueError('版本冲突，请重新加载后选图')
        from modules.figure_integrity import bind_figure, prepare_markdown
        manifest = self.figures_manifest()
        binding = bind_figure(manifest, asset_id, document['content'], relative, cursor_line,
                              source_root=self.source_root(), figure_root=self.output, caption=caption)
        result = prepare_markdown(document['content'], relative, manifest,
                                  figure_root=self.output, source_root=self.source_root())
        saved = self.save(relative, result.markdown, revision)
        manifest.save(self.output / 'figures' / 'manifest.json')
        self.update(pdf_current=False, delivered_at=None, artifacts={})
        return {'binding': binding.model_dump(), 'document': saved}

    def figure_asset_path(self, asset_id: str) -> Path:
        if not re.fullmatch(r'fig_[a-f0-9]{12}', asset_id):
            raise ValueError('资产编号无效')
        path = confined(self.output / 'figures', self.output / 'figures' / f'{asset_id}.png')
        if not path.is_file():
            raise FileNotFoundError(f'题图资产文件不存在: {asset_id}')
        return path

    def audit_figures(self):
        from modules.figure_matcher import FigureMatcher
        manifest = self.figures_manifest()
        matcher = FigureMatcher(manifest)
        ms_path = self.output / 'handout' / 'manuscript.md'
        if ms_path.is_file():
            content = ms_path.read_text(encoding='utf-8')
        else:
            docs = [self.read(d['path'])['content'] for d in self.documents()]
            content = '\n\n'.join(docs)
        report = matcher.audit_handout(content, self.output / 'handout', source_root=self.source_root())
        return report.model_dump()
