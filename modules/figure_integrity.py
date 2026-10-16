"""Fail-closed question-bound figures; similarity is never insertion authority.

The only approval operation is an explicit source-to-question selection. Rebuilds
reuse it deterministically, and omit stale/unknown images without changing input
Markdown. No generated pixels or remote/shared figure lookup is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import image as image_rule
from markdown_it.rules_inline import html_inline as html_rule
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from modules.figure_models import FigureBinding, FigureManifest, ReviewStatus

OMITTED = '（配图待补）'
_QUESTION = re.compile(r'例题|习题|练习|题目|问题|自己试|(?:^|【)例\s*\d')
_SOLUTION = re.compile(r'^(?:[\s*#【\[])*(?:解析|解答|答案|提示|证明)(?:[\s*】\]:：]|$)')
_HTML_MEDIA = re.compile(r'<\s*(?:img|picture|svg|object|iframe)\b', re.I)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_file(root: Path, relative: str) -> Path:
    """No basename fallback, absolute paths, Windows junctions or other roots."""
    rel = PurePosixPath(relative)
    if (not relative or '\\' in relative or ':' in relative or rel.is_absolute()
            or '..' in rel.parts):
        raise ValueError('题图来源路径越界')
    base = root.absolute()
    path = base.joinpath(*rel.parts)
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('题图来源路径越界')
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), 'st_reparse_tag', 0)
                                 in {0xA0000003, 0xA000000C}):
            raise ValueError('题图路径不允许链接或目录联接')
    return path


def _capture(rule):
    def wrapped(state, silent):
        start = state.pos
        ok = rule(state, silent)
        if ok and not silent and state.tokens[-1].type in {'image', 'html_inline'}:
            state.tokens[-1].meta['source_span'] = (start, state.pos)
        return ok
    return wrapped


def _parser():
    parser = MarkdownIt('commonmark').enable('table')
    parser.use(dollarmath_plugin).use(front_matter_plugin)
    parser.inline.ruler.at('image', _capture(image_rule))
    parser.inline.ruler.at('html_inline', _capture(html_rule))
    return parser


@dataclass(frozen=True)
class ImageReference:
    start: int
    end: int
    path: str
    line: int


def image_references(markdown: str) -> list[ImageReference]:
    """Locate parsed image syntax, preserving literal syntax inside math/code.

    The inline parser records its own spans, including reference-style images.
    Source maps locate complete inline content, not a regex search for ![]().
    An unmappable construct is an error rather than permission to keep an image.
    """
    lines = markdown.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    cursors: dict[tuple[int, int], int] = {}
    unmapped = set()
    references = []
    table_depth = 0
    for token in _parser().parse(markdown):
        if token.type == 'table_open':
            table_depth += 1
        elif token.type == 'table_close':
            table_depth -= 1
        if token.type == 'html_block' and _HTML_MEDIA.search(token.content):
            raise ValueError('不支持 HTML 图片块，请使用绑定题图；未放行该内容')
        if token.type != 'inline' or token.map is None:
            continue
        children = [child for child in token.children or []
                    if child.type == 'image' or
                    (child.type == 'html_inline' and _HTML_MEDIA.search(child.content))]
        key = tuple(token.map)
        lower, upper = offsets[key[0]], offsets[key[1]]
        if children and key in unmapped:
            raise ValueError('同一行前序内容无法定位，拒绝猜测图片位置')
        begin = markdown.find(token.content, max(lower, cursors.get(key, lower)), upper)
        if begin >= 0:
            cursors[key] = begin + len(token.content)
            positions = list(range(begin, begin + len(token.content) + 1))
        elif table_depth:
            # The table block parser removes backslashes before pipes even inside
            # code spans. Map that normalization back to original character offsets
            # and advance past EVERY cell, including cells with no real images.
            raw = markdown[max(lower, cursors.get(key, lower)):upper]
            raw_start = max(lower, cursors.get(key, lower))
            mapping = [raw_start + i for i, c in enumerate(raw)
                       if not (c == '\\' and i + 1 < len(raw) and raw[i + 1] == '|')]
            normalized = ''.join(markdown[i] for i in mapping)
            normalized_start = normalized.find(token.content)
            if normalized_start < 0:
                unmapped.add(key)
                if children:
                    raise ValueError('无法安全定位表格内图片')
                continue
            positions = mapping[normalized_start:normalized_start + len(token.content)]
            positions.append(positions[-1] + 1)
            cursors[key] = positions[-1]
        elif children:
            # Lists/blockquotes may add a container prefix on each source line.
            positions = []
            valid = True
            inline_lines = token.content.splitlines(keepends=True)
            for index, content_line in enumerate(inline_lines):
                source_index = key[0] + index
                if source_index >= key[1]:
                    valid = False
                    break
                body = content_line.rstrip('\n')
                column = lines[source_index].find(body)
                if column < 0:
                    valid = False
                    break
                positions.extend(range(offsets[source_index] + column,
                                       offsets[source_index] + column + len(content_line)))
            if not valid or len(positions) != len(token.content):
                raise ValueError('无法安全定位图片语法，拒绝猜测插入或保留位置')
            positions.append(positions[-1] + 1)
        else:
            unmapped.add(key)
            continue
        for child in children:
            start, end = child.meta['source_span']
            references.append(ImageReference(positions[start], positions[end],
                                             child.attrGet('src') or '<html>',
                                             markdown.count('\n', 0, positions[start]) + 1))
    return sorted(references, key=lambda ref: ref.start)


def _replace_images(markdown: str, replacement: str) -> tuple[str, list[ImageReference]]:
    refs = image_references(markdown)
    for ref in reversed(refs):
        markdown = markdown[:ref.start] + replacement + markdown[ref.end:]
    return markdown, refs


@dataclass(frozen=True)
class Question:
    start: int
    end: int
    start_line: int
    end_line: int
    fingerprint: str


def questions(markdown: str) -> list[Question]:
    """Only complete, top-level question blocks have automatic insertion slots."""
    tokens = _parser().parse(markdown)
    lines = markdown.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    result = []
    references = image_references(markdown)
    for index, token in enumerate(tokens):
        if token.type != 'heading_open' or token.level != 0:
            continue
        title = tokens[index + 1].content
        if not _QUESTION.search(title) or re.search(r'解析|解答|答案|提示', title):
            continue
        level = int(token.tag[1:])
        begin, finish = token.map[0], len(lines)
        for later in tokens[index + 3:]:
            if later.map is None or later.level != 0:
                continue
            if later.type == 'heading_open' and int(later.tag[1:]) <= level:
                finish = later.map[0]
                break
            if later.type in {'heading_open', 'paragraph_open'}:
                following = lines[later.map[0]].strip()
                if _SOLUTION.match(following):
                    finish = later.map[0]
                    break
        stem = markdown[offsets[begin]:offsets[finish]]
        for ref in reversed(references):
            if offsets[begin] <= ref.start and ref.end <= offsets[finish]:
                left, right = ref.start - offsets[begin], ref.end - offsets[begin]
                stem = stem[:left] + stem[right:]
        stem = stem.replace(OMITTED, '')
        # Only whitespace layout is normalized; signs, numbers and formulas remain.
        normalized = '\n'.join(line.rstrip() for line in stem.strip().splitlines())
        normalized = re.sub(r'\n{3,}', '\n\n', normalized)
        if len(normalized) > len(title) + 5:
            result.append(Question(offsets[begin], offsets[finish], begin + 1, finish,
                                   sha256(normalized.encode('utf-8'))))
    return result


def asset_revision(asset) -> str:
    keys = ('asset_id', 'task_id', 'source_file', 'source_sha256', 'page_index',
            'extraction_type', 'bbox', 'page_rotation', 'image_rel_path',
            'image_sha256', 'width', 'height', 'caption')
    payload = asset.model_dump(mode='json', include=set(keys))
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8'))


def _check_asset(manifest, asset, figure_root, source_root) -> str | None:
    if asset is None:
        return 'UNREGISTERED_ASSET'
    if asset.task_id != manifest.task_id:
        return 'SCOPE_MISMATCH'
    if asset.status == ReviewStatus.REJECTED:
        return 'REJECTED_ASSET'
    if asset.image_rel_path != f'figures/{asset.asset_id}.png':
        return 'NONCANONICAL_IMAGE_PATH'
    try:
        image = local_file(figure_root, asset.image_rel_path)
        source = local_file(source_root, asset.source_file)
        if not asset.image_sha256 or sha256(image.read_bytes()) != asset.image_sha256:
            return 'IMAGE_HASH_MISMATCH'
        if not asset.source_sha256 or sha256(source.read_bytes()) != asset.source_sha256:
            return 'SOURCE_HASH_MISMATCH'
    except (ValueError, OSError):
        return 'SOURCE_OR_IMAGE_UNAVAILABLE'
    return None


def bind_figure(manifest: FigureManifest, asset_id: str, markdown: str,
                document_path: str, cursor_line: int, *, source_root: Path,
                figure_root: Path, caption: str | None = None) -> FigureBinding:
    """Explicit author selection, reusable across builds; never called by a matcher."""
    local_file(figure_root / 'md', document_path)
    asset = manifest.get(asset_id)
    reason = _check_asset(manifest, asset, figure_root, source_root)
    if reason:
        raise ValueError(f'不能绑定该原图：{reason}')
    # A raw PDF image object can omit overlaid labels and connectors.
    if asset.source_file.lower().endswith('.pdf') and asset.extraction_type.value != 'cropped':
        raise ValueError('PDF 嵌入对象不代表完整题图，请先框选完整原页区域')
    from modules.figure_extractor import is_blank_image
    from PIL import Image
    with Image.open(local_file(figure_root, asset.image_rel_path)) as image:
        if is_blank_image(image):
            raise ValueError('该区域为空白、纯色或渐变装饰，不能作为题图')
    candidates = [q for q in questions(markdown) if q.start_line <= cursor_line <= q.end_line]
    if len(candidates) != 1:
        raise ValueError('请在顶层例题或练习的完整题干内选图；表格、列表、代码不是题图槽位')
    question = candidates[0]
    # A cursor within a protected structure never silently moves to another block.
    protected = {'table_open', 'fence', 'code_block', 'math_block', 'bullet_list_open',
                 'ordered_list_open', 'blockquote_open'}
    for token in _parser().parse(markdown):
        if token.type in protected and token.map and token.map[0] <= cursor_line - 1 < token.map[1]:
            raise ValueError('不能在表格、公式、代码、引用或列表内部插入题图')
    if sum(q.fingerprint == question.fingerprint for q in questions(markdown)) != 1:
        raise ValueError('相同题干出现多次，不能猜测绑定位置')
    description = (caption or asset.caption).strip()
    if not description or re.fullmatch(r'第\s*\d+\s*页题图', description):
        raise ValueError('请填写能描述学术内容的图注')
    identity = f'{manifest.task_id}\0{document_path}\0{question.fingerprint}\0{asset_id}'
    binding = FigureBinding(
        binding_id='bind_' + sha256(identity.encode())[:24], task_id=manifest.task_id,
        document_path=document_path, question_sha256=question.fingerprint,
        asset_id=asset_id, asset_revision=asset_revision(asset),
        image_sha256=asset.image_sha256, source_file=asset.source_file,
        source_sha256=asset.source_sha256, caption=description)
    manifest.bindings[binding.binding_id] = binding
    return binding


@dataclass
class PreparedFigures:
    markdown: str
    inserted: int = 0
    omissions: list[dict] = field(default_factory=list)
    assets: dict[str, str] = field(default_factory=dict)


def _repair_omitted_table_gap(markdown: str) -> str:
    """Repair the old injector's precise failure shape, preserving every data row.

    Join orphan rows only across blank lines and omitted-image-only lines, and
    only if the parser confirms one complete table. Never join two valid tables.
    """
    lines = markdown.splitlines(keepends=True)
    for token in reversed(_parser().parse(markdown)):
        if token.type != 'table_open' or token.level != 0 or token.map is None:
            continue
        start, end = token.map
        cursor, omitted = end, 0
        while cursor < len(lines) and lines[cursor].strip() in {'', OMITTED}:
            omitted += lines[cursor].strip() == OMITTED
            cursor += 1
        if not omitted or cursor == len(lines) or not lines[cursor].lstrip().startswith('|'):
            continue
        rows_start = cursor
        while cursor < len(lines) and lines[cursor].lstrip().startswith('|'):
            cursor += 1
        orphan = lines[rows_start:cursor]
        if any(re.fullmatch(r'[| :\-\t]+', row.strip()) for row in orphan):
            continue  # The following block has its own header separator.
        columns = len(re.findall(r'(?<!\\)\|', lines[start]))
        if any(len(re.findall(r'(?<!\\)\|', row)) != columns for row in orphan):
            continue  # Do not merge ambiguous/mismatched cell structures.
        candidate = ''.join(lines[start:end] + orphan)
        parsed = _parser().parse(candidate)
        if (not parsed or parsed[0].type != 'table_open' or
                parsed[0].map != [0, len(lines[start:end]) + len(orphan)]):
            continue
        lines[end:cursor] = orphan + ['\n', OMITTED + '\n', '\n']
    return ''.join(lines)


def prepare_markdown(markdown: str, document_path: str, manifest: FigureManifest, *,
                     figure_root: Path, source_root: Path) -> PreparedFigures:
    """Remove all unbound images, then materialize only current explicit bindings."""
    markdown = markdown.replace('\r\n', '\n').replace('\r', '\n')
    clean, references = _replace_images(markdown, '')
    found = questions(clean)
    result = PreparedFigures(clean)
    selected: list[tuple[Question, FigureBinding]] = []
    for binding in manifest.bindings.values():
        if binding.document_path != document_path:
            continue
        asset = manifest.get(binding.asset_id)
        reason = ('SCOPE_MISMATCH' if binding.task_id != manifest.task_id else
                  _check_asset(manifest, asset, figure_root, source_root))
        if not reason and (asset_revision(asset) != binding.asset_revision or
                           binding.image_sha256 != asset.image_sha256 or
                           binding.source_file != asset.source_file or
                           binding.source_sha256 != asset.source_sha256):
            reason = 'STALE_ASSET_BINDING'
        matches = [q for q in found if q.fingerprint == binding.question_sha256]
        if not reason and len(matches) != 1:
            reason = 'CHANGED_OR_AMBIGUOUS_QUESTION'
        if reason:
            result.omissions.append({'document': document_path, 'asset_id': binding.asset_id,
                                     'binding_id': binding.binding_id, 'reason': reason})
        else:
            selected.append((matches[0], binding))
            result.assets[asset.image_rel_path] = asset.image_sha256
    # Existing image references are authorized only inside their actual question.
    # They are rebuilt from the binding, so moved/inline tags cannot choose placement.
    approved_paths = set(result.assets)
    for ref in references:
        if ref.path not in approved_paths:
            result.omissions.append({'document': document_path, 'path': ref.path,
                                     'line': ref.line, 'reason': 'NO_VALID_QUESTION_BINDING'})
    # A verified reference is removed even when misplaced; its slot is reconstructed.
    patches = [(ref.start, ref.end, '' if ref.path in approved_paths else OMITTED)
               for ref in references]
    for start, end, replacement in reversed(patches):
        markdown = markdown[:start] + replacement + markdown[end:]
    markdown = _repair_omitted_table_gap(markdown)
    current_questions = {q.fingerprint: q for q in questions(markdown)}
    patches = []
    # Group multiple explicitly bound subfigures in the same slot, in stable order.
    slots: dict[int, list[FigureBinding]] = {}
    for question, binding in selected:
        if question.fingerprint not in current_questions:
            result.assets.pop(manifest.get(binding.asset_id).image_rel_path, None)
            result.omissions.append({'document': document_path, 'binding_id': binding.binding_id,
                                     'reason': 'QUESTION_STRUCTURE_CHANGED'})
            continue
        slots.setdefault(current_questions[question.fingerprint].end, []).append(binding)
    for position, bindings in slots.items():
        tags = []
        for binding in sorted(bindings, key=lambda b: b.binding_id):
            caption = re.sub(r'[\r\n|]', ' ', binding.caption)
            caption = caption.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
            tags.append(f'![{caption}]({manifest.get(binding.asset_id).image_rel_path})')
        # Existing trailing whitespace is reused to make reprocessing idempotent.
        start = position
        while start > 0 and markdown[start - 1] in '\n\r ':
            start -= 1
        tags_text = '\n\n' + '\n\n'.join(tags) + '\n\n'
        patches.append((start, position, tags_text))
        result.inserted += len(bindings)
    for start, end, replacement in sorted(patches, key=lambda p: (p[0], p[1]), reverse=True):
        markdown = markdown[:start] + replacement + markdown[end:]
    remaining = image_references(markdown)
    expected_paths = sorted(manifest.get(binding.asset_id).image_rel_path
                            for bindings in slots.values() for binding in bindings)
    if sorted(ref.path for ref in remaining) != expected_paths:
        raise ValueError('最终图片引用与有效绑定不一致，已阻止输出')
    result.markdown = markdown
    return result


def copy_bound_figures(figure_root: Path, destination: Path, assets: dict[str, str]) -> None:
    """Only exact referenced bytes are copied; existing destinations are revalidated."""
    for relative, expected in assets.items():
        data = local_file(figure_root, relative).read_bytes()
        if sha256(data) != expected:
            raise ValueError('题图在构建期间变化，请重新构建')
        target = local_file(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
