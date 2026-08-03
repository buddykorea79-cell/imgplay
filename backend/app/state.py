"""세션 상태: 업로드된 사진 레지스트리와 1단계 확정 여부.

DB는 쓰지 않습니다. `work/registry.json` 하나에 담고 프로세스 메모리에 캐시합니다.
멀티테넌시가 없으므로 이걸로 충분합니다.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from .cache import JsonCache, WorkDirs
from .compose import Composition
from .exif import Exif
from .measure import Stats
from .schemas import FaceBox, GradeRules, MotionRules

__all__ = ["Photo", "AppState", "get_state", "REPO_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class Photo:
    id: str  # 파일 내용 SHA-256
    filename: str
    path: Path
    stats: Stats
    exif: Exif
    faces: list[FaceBox] = field(default_factory=list)
    composition: Composition | None = None  # 2단계에서 채워짐
    graded_path: Path | None = None

    @property
    def captured_at(self) -> datetime | None:
        return self.exif.datetime_original

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "width": self.stats.width,
            "height": self.stats.height,
            "stats": self.stats.to_dict(),
            "exif": self.exif.to_dict(),
            "faces": [f.model_dump() for f in self.faces],
            "thumb_url": f"/api/grade/original/{self.id}?mode=fit&long_edge=320",
        }


class AppState:
    """프로세스 전역 상태. 락으로 보호합니다(업로드/렌더가 동시에 들어옵니다)."""

    def __init__(self, work: WorkDirs | None = None) -> None:
        self.work = work or WorkDirs()
        self.photos: dict[str, Photo] = {}
        self.order: list[str] = []  # 사용자가 확정한 타임라인 순서
        self.committed = False
        self.composition_sig: tuple | None = None  # 구도 캐시가 어떤 출력 규격 기준인지
        self.lock = threading.RLock()
        self.measure_cache = JsonCache(self.work.cache, "measure")
        self.jobs: dict = {}  # job_id -> RenderJob (순환 임포트를 피하려 타입 생략)
        self._registry = self.work.root / "registry.json"
        self._load()

    # ------------------------------------------------------------ 규칙 파일

    def rules_path(self, kind: str) -> Path:
        """규칙 파일 위치. 테스트는 `PVT_RULES_DIR`로 격리합니다 —
        그러지 않으면 테스트가 저장소의 grade.yaml을 덮어씁니다."""
        base = Path(os.environ.get("PVT_RULES_DIR", REPO_ROOT))
        return base / f"{kind}.yaml"

    def load_grade_rules(self) -> GradeRules:
        return GradeRules(**self._read_yaml("grade"))

    def load_motion_rules(self) -> MotionRules:
        return MotionRules(**self._read_yaml("motion"))

    def _read_yaml(self, kind: str) -> dict:
        p = self.rules_path(kind)
        if not p.is_file():
            return {}
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    def write_rules(self, kind: str, data: dict) -> None:
        p = self.rules_path(kind)
        p.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    # ------------------------------------------------------------ 영속화

    def _load(self) -> None:
        if not self._registry.is_file():
            return
        try:
            doc = json.loads(self._registry.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in doc.get("photos", []):
            path = Path(item["path"])
            if not path.is_file():
                continue  # work/가 지워졌으면 조용히 건너뛴다
            graded = self.work.graded / f"{item['id']}.png"
            self.photos[item["id"]] = Photo(
                id=item["id"],
                filename=item["filename"],
                path=path,
                stats=Stats(**item["stats"]),
                exif=_exif_from_dict(item["exif"]),
                faces=[FaceBox(**f) for f in item.get("faces", [])],
                graded_path=graded if graded.is_file() else None,
            )
        self.order = [i for i in doc.get("order", []) if i in self.photos]
        self.committed = bool(doc.get("committed")) and all(
            p.graded_path is not None for p in self.photos.values()
        ) and bool(self.photos)

    def save(self) -> None:
        doc = {
            "committed": self.committed,
            "order": self.order,
            "photos": [
                {
                    "id": p.id,
                    "filename": p.filename,
                    "path": str(p.path),
                    "stats": p.stats.to_dict(),
                    "exif": p.exif.to_dict(),
                    "faces": [f.model_dump() for f in p.faces],
                }
                for p in self.photos.values()
            ],
        }
        tmp = self._registry.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._registry)

    # ------------------------------------------------------------ 조회

    def ordered_photos(self, order: list[str] | None = None) -> list[Photo]:
        """지정 순서 → 저장된 순서 → 촬영시각 순."""
        from .timeline import TimelineEntry, sort_by_capture_time

        ids = order or self.order
        if not ids:
            entries = [
                TimelineEntry(p.id, p.filename, p.captured_at) for p in self.photos.values()
            ]
            ids = sort_by_capture_time(entries)
        return [self.photos[i] for i in ids if i in self.photos]

    def invalidate_stage2(self) -> None:
        """1단계로 되돌아가기. 통계 캐시는 유지합니다."""
        with self.lock:
            self.work.clear_stage2()
            self.committed = False
            for p in self.photos.values():
                p.graded_path = None
                p.composition = None
            self.save()

    def reset(self) -> None:
        with self.lock:
            self.photos.clear()
            self.order.clear()
            self.committed = False
            self.work.clear_stage2()
            self._registry.unlink(missing_ok=True)


def _exif_from_dict(d: dict) -> Exif:
    dt = d.get("datetime_original")
    return Exif(
        iso=d.get("iso"),
        exposure_time=d.get("exposure_time"),
        f_number=d.get("f_number"),
        flash=d.get("flash"),
        datetime_original=datetime.fromisoformat(dt) if dt else None,
        focal_length=d.get("focal_length"),
        orientation=d.get("orientation"),
    )


_state: AppState | None = None
_state_lock = threading.Lock()


def get_state() -> AppState:
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
    return _state
