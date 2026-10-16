"""Smart matching, provenance correlation, and missing figure audit engine for CourseLM.

Implements strict verification:
- Independent matching of questions to source figures.
- Explicit prioritization: File/Page/Figure Number > Adjacent text proximity > Keyword overlap.
- Missing figure inspection: flags sentences requiring figures ("如图所示", "由电路图可知", etc.)
  that lack valid image references.
- Never hallucinates or substitutes mismatched figures.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field

from modules.figure_models import (
    FigureAsset,
    FigureAuditReport,
    FigureManifest,
    MissingFigureWarning,
    ReviewStatus,
)


TRIGGER_PHRASES = [
    r"如[下此]?图所示",
    r"由[下此]?(?:电路图|受力图|受力分析图|光路图|函数图[像象]|波形图|示意图)可知",
    r"根据[下此]?(?:电路图|受力图|受力分析图|光路图|函数图[像象]|波形图|示意图)",
    r"从[下此]?(?:电路图|受力图|受力分析图|光路图|函数图[像象]|波形图)可以看出",
    r"观察(?:函数图[像象]|受力图|波形图|电路图)",
    r"参见(?:附图|图\s*[0-9]+[-.][0-9]+)",
    r"如?图\s*[0-9]+[-.][0-9]+\s*所示",
    r"见[下此]图",
    r"如下图",
    r"如附图所示",
    r"原图待补",
]

_TRIGGER_REGEX = re.compile("|".join(f"(?:{p})" for p in TRIGGER_PHRASES), re.IGNORECASE)
_MARKDOWN_IMG_REGEX = re.compile(r"!\[(.*?)\]\((.*?)\)")


class CandidateMatch(BaseModel):
    """Candidate original figure match for an exercise or section."""
    target_id: str                      # e.g., example-1 or section title
    target_title: str
    target_snippet: str
    figure_asset_id: str
    figure_image_path: str
    figure_source: str
    figure_page: int
    score: float                        # 0.0 to 1.0
    match_reasons: List[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.PENDING


def _tokenize_text(text: str) -> set[str]:
    """Extract Chinese terms, English words, formulas and numbers."""
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5]", " ", text)
    tokens = set()
    for tok in cleaned.split():
        tok = tok.strip()
        if len(tok) >= 2:
            tokens.add(tok.lower())
    # Add 2-gram characters for Chinese
    chinese_chars = [c for c in text if "\u4e00" <= c <= "\u9fa5"]
    for i in range(len(chinese_chars) - 1):
        tokens.add(chinese_chars[i] + chinese_chars[i + 1])
    return tokens


def _calculate_lexical_similarity(text1: str, text2: str) -> float:
    t1 = _tokenize_text(text1)
    t2 = _tokenize_text(text2)
    if not t1 or not t2:
        return 0.0
    intersection = t1.intersection(t2)
    shorter_len = min(len(t1), len(t2))
    containment = len(intersection) / shorter_len if shorter_len else 0.0
    union = t1.union(t2)
    jaccard = len(intersection) / len(union) if union else 0.0
    return 0.75 * containment + 0.25 * jaccard


class FigureMatcher:
    """Matches text blocks to candidate source figures and checks for missing figures."""

    def __init__(self, manifest: FigureManifest):
        self.manifest = manifest

    def match_question(
        self,
        question_text: str,
        question_title: str = "",
        target_id: str = "",
        top_k: int = 3,
    ) -> List[CandidateMatch]:
        """Find candidate source figures for a given question or problem stem."""
        candidates: List[CandidateMatch] = []

        # Extract explicit references from question
        page_matches = re.findall(r"(?:P|第)\s*(\d+)\s*(?:页|p)?", question_text, re.IGNORECASE)
        fig_num_matches = re.findall(r"图\s*([0-9]+[.-][0-9]+|[0-9]+)", question_text)
        ex_num_matches = re.findall(r"例\s*([0-9]+[.-][0-9]+|[0-9]+)", question_text)

        target_snippet = question_text[:200]

        for asset in self.manifest.figures.values():
            if asset.status == ReviewStatus.REJECTED or asset.task_id != self.manifest.task_id:
                continue

            score = 0.0
            reasons: List[str] = []

            # Rule 1: Exact figure number match in caption / adjacent text
            for fnum in fig_num_matches:
                if fnum in asset.caption or fnum in asset.adjacent_text:
                    score += 0.55
                    reasons.append(f"图号匹配：图 {fnum}")
                    break

            # Rule 2: Explicit page number match
            for pnum in page_matches:
                if int(pnum) == asset.page_index:
                    score += 0.35
                    reasons.append(f"页码精确吻合：第 {asset.page_index} 页 ({asset.source_file})")
                    break

            # Rule 3: Example number match
            for enum in ex_num_matches:
                if enum in asset.caption or enum in asset.adjacent_text:
                    score += 0.40
                    reasons.append(f"例题号吻合：例 {enum}")
                    break

            # Rule 4: Lexical text similarity between question stem and adjacent source text
            if asset.adjacent_text:
                sim = _calculate_lexical_similarity(question_text, asset.adjacent_text)
                if sim >= 0.12:
                    score += min(0.40, sim * 0.8)
                    reasons.append(f"原资料邻近文字高度相关 (相似度: {sim:.2f})")

            # Rule 5: Caption text similarity
            if asset.caption:
                cap_sim = _calculate_lexical_similarity(question_text, asset.caption)
                if cap_sim >= 0.2:
                    score += 0.20
                    reasons.append(f"图注与题目相关: {asset.caption}")

            if score > 0.15:
                candidates.append(
                    CandidateMatch(
                        target_id=target_id,
                        target_title=question_title or target_id,
                        target_snippet=target_snippet,
                        figure_asset_id=asset.asset_id,
                        figure_image_path=asset.image_rel_path,
                        figure_source=asset.source_file,
                        figure_page=asset.page_index,
                        score=min(1.0, score),
                        match_reasons=reasons,
                        status=asset.status,
                    )
                )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]

    def find_candidate_figures(self, text: str, limit: int = 3, target_title: str = "", target_id: str = "") -> List[CandidateMatch]:
        """Alias for match_question."""
        return self.match_question(text, question_title=target_title, target_id=target_id, top_k=limit)


    def audit_markdown_content(
        self,
        markdown: str,
        file_path: str = "manuscript.md",
    ) -> Tuple[List[MissingFigureWarning], List[str]]:
        """Audit Markdown content for missing figure triggers without images.

        Returns (warnings, list_of_referenced_image_paths).
        """
        from modules.figure_integrity import image_references, _parser, questions
        lines = markdown.splitlines()
        warnings: List[MissingFigureWarning] = []
        referenced_images: List[str] = []

        # First collect all referenced images with their line numbers
        img_line_indices: set[int] = set()
        for ref in image_references(markdown):
            referenced_images.append(ref.path)
            img_line_indices.add(ref.line - 1)
        protected_lines = set()
        question_blocks = questions(markdown)
        for token in _parser().parse(markdown):
            if token.type in {'fence', 'code_block', 'math_block', 'front_matter'} and token.map:
                protected_lines.update(range(*token.map))

        # Scan for missing figure triggers
        for idx, line in enumerate(lines):
            stripped = line.strip()
            # Ignore headers, list symbols, quotes
            if idx in protected_lines or not stripped or stripped.startswith("#"):
                continue

            match = _TRIGGER_REGEX.search(stripped)
            if match:
                # A different question's nearby image cannot satisfy this request.
                has_nearby_image = any(
                    q.start_line <= idx + 1 <= q.end_line and
                    any(q.start_line <= line + 1 <= q.end_line for line in img_line_indices)
                    for q in question_blocks)

                if not has_nearby_image:
                    # Look up candidate figures
                    candidates = self.match_question(stripped, target_id=f"{file_path}:{idx + 1}")
                    candidate_ids = [c.figure_asset_id for c in candidates]

                    warnings.append(
                        MissingFigureWarning(
                            file_path=file_path,
                            line_number=idx + 1,
                            matched_text=match.group(0),
                            snippet=stripped[:120],
                            candidate_figures=candidate_ids,
                        )
                    )

        return warnings, referenced_images

    def audit_handout(
        self,
        manuscript_text: str,
        handout_dir: Path,
        source_root: Path | None = None,
    ) -> FigureAuditReport:
        """Run a full audit on the generated handout."""
        warnings, referenced_paths = self.audit_markdown_content(manuscript_text)

        total_figures = len(referenced_paths)
        valid_figures = 0
        missing_files = 0
        pending_review = 0

        from modules.figure_integrity import local_file, sha256, asset_revision, questions, image_references, _check_asset
        invalid = []
        question_blocks = questions(manuscript_text)

        for ref in image_references(manuscript_text):
            rel_path = ref.path
            try:
                path = local_file(handout_dir, rel_path)
                found = path.is_file()
            except ValueError:
                found = False
            if not found:
                missing_files += 1
            stem = Path(rel_path).stem
            asset = self.manifest.get(stem)
            if asset:
                if asset.status == ReviewStatus.PENDING:
                    pending_review += 1
            valid = (found and asset is not None and asset.task_id == self.manifest.task_id
                     and asset.status != ReviewStatus.REJECTED and asset.image_rel_path == rel_path
                     and sha256(path.read_bytes()) == asset.image_sha256
                     and source_root is not None
                     and _check_asset(self.manifest, asset, handout_dir, source_root) is None
                     and any(b.task_id == self.manifest.task_id and b.asset_id == stem
                             and b.image_sha256 == asset.image_sha256
                             and b.asset_revision == asset_revision(asset)
                             and any(q.start <= ref.start < q.end and
                                     q.fingerprint == b.question_sha256 for q in question_blocks)
                             for b in self.manifest.bindings.values()))
            if valid:
                valid_figures += 1
            else:
                invalid.append(rel_path)

        audit_passed = not missing_files and not warnings and not invalid

        return FigureAuditReport(
            total_figures_in_handout=total_figures,
            valid_source_figures=valid_figures,
            missing_image_files=missing_files,
            pending_review_figures=pending_review,
            missing_figure_warnings=warnings,
            invalid_figure_references=invalid,
            audit_passed=audit_passed,
        )


def detect_missing_figures(text: str, file_path: str = "") -> list[MissingFigureWarning]:
    """Scan text content for trigger phrases lacking nearby images."""
    matcher = FigureMatcher(FigureManifest(task_id="", course_id=""))
    warnings, _ = matcher.audit_markdown_content(text, file_path=file_path)
    return warnings


def audit_handout_figures(
    manuscript_text: str,
    manifest: FigureManifest,
    handout_dir: Path | None = None,
) -> FigureAuditReport:
    """Full audit of figures and triggers in a handout manuscript."""
    matcher = FigureMatcher(manifest)
    return matcher.audit_handout(manuscript_text, handout_dir or Path("."))

