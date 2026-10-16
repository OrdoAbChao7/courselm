"""Data models for CourseLM Source Figures system.

Strict provenance tracking: every figure retains its source file, page index,
bounding box, extraction method, SHA-256 hashes, and review status.
No AI redrawing or hallucinatory generation permitted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class ExtractionType(str, Enum):
    EMBEDDED = "embedded"    # Extracted directly from embedded image stream
    CROPPED = "cropped"      # Rendered and cropped from page coordinates
    STANDALONE = "standalone" # Ingested from standalone image file


class ReviewStatus(str, Enum):
    PENDING = "pending"      # Awaiting human review
    CONFIRMED = "confirmed"  # Approved for inclusion
    REJECTED = "rejected"    # Discarded / not relevant


class CoordinateSystem(str, Enum):
    POINTS = "points"        # PDF points (72 pt/inch, origin bottom-left or top-left)
    NORMALIZED = "normalized"# 0.0 - 1.0 relative to page width and height


class BoundingBox(BaseModel):
    """Bounding box on the source page."""
    x0: float
    y0: float
    x1: float
    y1: float
    coord_system: CoordinateSystem = CoordinateSystem.NORMALIZED

    @property
    def width(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def clamp(self, max_w: float, max_h: float) -> "BoundingBox":
        return BoundingBox(
            x0=max(0.0, min(max_w, self.x0)),
            y0=max(0.0, min(max_h, self.y0)),
            x1=max(0.0, min(max_w, self.x1)),
            y1=max(0.0, min(max_h, self.y1)),
            coord_system=self.coord_system,
        )

    def normalize(self, page_width: float, page_height: float) -> "BoundingBox":
        return self.to_normalized(page_width, page_height)

    def to_normalized(self, page_width: float, page_height: float) -> "BoundingBox":
        if self.coord_system == CoordinateSystem.NORMALIZED:
            return self
        return BoundingBox(
            x0=max(0.0, min(1.0, self.x0 / page_width)),
            y0=max(0.0, min(1.0, self.y0 / page_height)),
            x1=max(0.0, min(1.0, self.x1 / page_width)),
            y1=max(0.0, min(1.0, self.y1 / page_height)),
            coord_system=CoordinateSystem.NORMALIZED,
        )

    def to_points(self, page_width: float, page_height: float) -> "BoundingBox":
        if self.coord_system == CoordinateSystem.POINTS:
            return self
        return BoundingBox(
            x0=self.x0 * page_width,
            y0=self.y0 * page_height,
            x1=self.x1 * page_width,
            y1=self.y1 * page_height,
            coord_system=CoordinateSystem.POINTS,
        )


class SourceOccurrence(BaseModel):
    """Record of an occurrence in source materials (supports deduplication)."""
    source_file: str = Field(default="", alias="source_file_rel")
    source_sha256: str = Field(default="", alias="source_file_sha256")
    page_index: int = 1
    bbox: Optional[BoundingBox] = None
    surrounding_text: str = ""

    model_config = {"populate_by_name": True}


class FigureAsset(BaseModel):
    """Represents a verified original figure asset."""
    asset_id: str
    task_id: str
    source_file: str = ""             # Relative path within source materials
    source_sha256: str = ""
    page_index: int = 1               # 1-based page or slide number
    extraction_type: ExtractionType
    bbox: Optional[BoundingBox] = None
    page_rotation: int = 0
    image_rel_path: str = Field(default="", alias="file_path") # Relative path inside task storage
    image_sha256: str = Field(default="", alias="sha256")
    width: int                        # Pixels
    height: int                       # Pixels
    dpi: int = 300
    adjacent_text: str = ""           # Surrounding text/context extracted near figure
    caption: str = ""                 # Detected or assigned figure caption
    status: ReviewStatus = ReviewStatus.PENDING
    occurrences: List[SourceOccurrence] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @property
    def file_path(self) -> str:
        return self.image_rel_path

    @property
    def sha256(self) -> str:
        return self.image_sha256

    def add_occurrence(self, occ: SourceOccurrence) -> None:
        for existing in self.occurrences:
            if (existing.source_file == occ.source_file and
                existing.source_sha256 == occ.source_sha256 and
                existing.page_index == occ.page_index and existing.bbox == occ.bbox):
                return
        self.occurrences.append(occ)


class FigureBinding(BaseModel):
    """An explicit question-to-source association, invalidated by any evidence change.

    These records are created by the server's bind operation, never by a lexical
    matcher. An asset's legacy `confirmed` flag alone does not authorize insertion.
    """
    binding_id: str
    task_id: str
    document_path: str
    question_sha256: str
    asset_id: str
    asset_revision: str
    image_sha256: str
    source_file: str
    source_sha256: str
    caption: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class FigureManifest(BaseModel):
    """Manifest of all figures belonging to a specific task."""
    task_id: str
    course: str = ""
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    figures: dict[str, FigureAsset] = Field(default_factory=dict)
    bindings: dict[str, FigureBinding] = Field(default_factory=dict)

    def get(self, asset_id: str) -> Optional[FigureAsset]:
        return self.figures.get(asset_id)

    def add(self, asset: FigureAsset) -> FigureAsset:
        if asset.task_id != self.task_id:
            raise ValueError("题图任务 scope 不匹配")
        # Check if identical sha256 already exists for deduplication
        for existing in self.figures.values():
            if existing.sha256 and existing.sha256 == asset.sha256:
                for occ in asset.occurrences:
                    existing.add_occurrence(occ)
                self.updated_at = datetime.now().isoformat(timespec="seconds")
                return existing
        self.figures[asset.asset_id] = asset
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        return asset

    def add_figure(self, asset: FigureAsset) -> FigureAsset:
        return self.add(asset)

    def list_figures(self, status: Optional[ReviewStatus] = None, source_file: Optional[str] = None) -> List[FigureAsset]:
        res = list(self.figures.values())
        if status is not None:
            res = [f for f in res if f.status == status]
        if source_file is not None:
            res = [f for f in res if f.source_file == source_file]
        return sorted(res, key=lambda f: (f.source_file, f.page_index, f.asset_id))

    def save(self, path: Optional[Path] = None) -> None:
        target = path or getattr(self, "_path", None)
        if target is None:
            raise ValueError("No path provided or stored for manifest save")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".figures-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(self.model_dump_json(indent=2))
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path, task_id: str, course: str = "", course_id: str = "") -> "FigureManifest":
        course_name = course or course_id
        obj = None
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                obj = cls.model_validate(data)
            except (ValueError, OSError) as exc:
                raise ValueError(f"题图 manifest 损坏，拒绝静默重置：{path}") from exc
        if obj is None:
            obj = cls(task_id=task_id, course=course_name)
        if obj.task_id != task_id or (course_name and obj.course != course_name):
            raise ValueError("题图 manifest 任务/课程 scope 不匹配")
        if any(a.task_id != obj.task_id for a in obj.figures.values()):
            raise ValueError("题图资产任务 scope 不匹配")
        if any(b.task_id != obj.task_id for b in obj.bindings.values()):
            raise ValueError("题图绑定任务 scope 不匹配")
        obj._path = path
        return obj


class MissingFigureWarning(BaseModel):
    """Warning produced when text indicates a figure should exist but none is referenced."""
    file_path: str
    line_number: int
    matched_text: str
    snippet: str
    candidate_figures: List[str] = Field(default_factory=list) # Candidate asset_ids


class FigureAuditReport(BaseModel):
    """Summary report of figure usage and audits."""
    total_figures_in_handout: int = 0
    valid_source_figures: int = 0
    missing_image_files: int = 0
    pending_review_figures: int = 0
    missing_figure_warnings: List[MissingFigureWarning] = Field(default_factory=list)
    invalid_figure_references: List[str] = Field(default_factory=list)
    audit_passed: bool = True
