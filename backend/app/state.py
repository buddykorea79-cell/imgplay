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
        """규칙을 yaml로 저장한다.

        UI에서 확정할 때마다 이 파일을 덮어쓰므로, 손으로 적어둔 주석은 사라집니다.
        대신 설명을 자동으로 다시 붙여 파일이 항상 스스로를 설명하게 만듭니다
        (주석 왕복 보존은 ruamel.yaml 의존성이 필요해 쓰지 않았습니다).
        """
        p = self.rules_path(kind)
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        p.write_text(_annotate_yaml(kind, body), encoding="utf-8")

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
        """지정 순서 → 저장된 수동 순서 → EXIF 촬영시각 순.

        수동 순서에 없는 사진(나중에 추가된 사진)은 촬영시각 순으로 뒤에 붙여
        유실을 막습니다.
        """
        from .timeline import TimelineEntry, sort_by_capture_time

        def by_capture(photos: list[Photo]) -> list[str]:
            return sort_by_capture_time(
                [TimelineEntry(p.id, p.filename, p.captured_at) for p in photos]
            )

        ids = [i for i in (order or self.order) if i in self.photos]
        seen = set(ids)
        ids += by_capture([p for p in self.photos.values() if p.id not in seen])
        return [self.photos[i] for i in ids]

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


_HEADERS = {
    "grade": "1단계 화질 보정 규칙. 값을 바꾸면 재측정 없이 즉시 반영됩니다.",
    "motion": "2단계 영상 효과 규칙. 출력 규격을 바꾸면 안전 줌 상한이 다시 계산됩니다.",
}

# 최상위 키에 붙일 한 줄 설명. 규칙 파일을 처음 여는 사람이 헤매지 않게 합니다.
_SECTION_NOTES = {
    "target": "보정이 도달하려는 목표값",
    "gamma": "밝기. 가드가 걸리면 max보다 더 낮게 눌립니다",
    "contrast": "대비. 클리핑이 임계를 넘으면 clip_penalty만큼 깎습니다",
    "saturation": "채도. 얼굴이 검출되면 상한이 skin_max로 내려갑니다",
    "unsharp": "선명도 = base - sharpness / divisor (sharpness는 1024px 정규화)",
    "whitebalance": "그레이월드. max_deviation이 단색 화면에서의 폭주를 막습니다",
    "guards": "촬영 조건별 상한 덮어쓰기. 클램프 히트로 기록됩니다",
    "output": "출력 규격. preview_height는 클립 미리보기 속도 손잡이입니다",
    "duration": "클립 길이. 어지럽다면 zoom.amount보다 base_sec을 먼저 늘리세요",
    "zoom": "safety × (원본 해상도 여유) 가 사진별 줌 상한이 됩니다",
    "pan": "관심영역(얼굴 → 엣지 무게중심) 방향으로 이동",
    "aspect": "세로 사진 등 종횡비가 다른 사진의 처리 방식",
    "transition": "인접 사진의 히스토그램 거리와 EXIF 촬영 간격으로 결정",
}


def _annotate_yaml(kind: str, body: str) -> str:
    """덤프된 yaml에 헤더와 섹션 주석을 다시 붙인다."""
    header = (
        f"# {_HEADERS.get(kind, '')}\n"
        f"# 이 파일은 앱이 저장할 때마다 다시 씁니다 — 직접 단 주석은 유지되지 않습니다.\n"
    )
    out: list[str] = []
    for line in body.splitlines():
        key = line.split(":", 1)[0]
        if line and not line[0].isspace() and key in _SECTION_NOTES:
            out.append(f"\n# {_SECTION_NOTES[key]}")
        out.append(line)
    return header + "\n".join(out) + "\n"


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
