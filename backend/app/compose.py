"""구도 분석 (섹션 8) — 2단계의 입력.

모션을 무작위로 주면 안 됩니다. 사진에서 계산합니다.

`cv2.saliency`는 쓰지 않습니다 — contrib 패키지가 필요해져서 의존성이 늘어나는데,
엣지 무게중심으로 충분합니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .grade import clamp
from .imageio import resize_long_edge
from .schemas import FaceBox

__all__ = ["Composition", "analyze_composition", "poi_from_edges", "safe_max_zoom"]

_ANALYSIS_LONG_EDGE = 720  # POI는 정밀도가 필요 없다. 축소하면 수십 배 빠르다.


@dataclass(slots=True)
class Composition:
    poi_x: float  # 0~1 정규화
    poi_y: float
    poi_source: str  # "face" | "edges" | "center"
    max_zoom: float
    aspect_dev: float
    headroom: float

    def to_dict(self) -> dict:
        return asdict(self)


def poi_from_edges(img_bgr: np.ndarray) -> tuple[float, float]:
    """엣지 밀도 무게중심 (0~1 정규화)."""
    small = resize_long_edge(img_bgr, _ANALYSIS_LONG_EDGE)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    mag = np.abs(cv2.Laplacian(cv2.GaussianBlur(gray, (5, 5), 0), cv2.CV_32F))
    total = float(mag.sum())
    if total <= 1e-6:
        return 0.5, 0.5  # 완전 평탄한 이미지: 중앙
    ys, xs = np.mgrid[0 : mag.shape[0], 0 : mag.shape[1]]
    cx = float((xs * mag).sum() / total) / mag.shape[1]
    cy = float((ys * mag).sum() / total) / mag.shape[0]
    return clamp(cx, 0.0, 1.0), clamp(cy, 0.0, 1.0)


def poi_from_faces(faces: list[FaceBox]) -> tuple[float, float]:
    """얼굴 바운딩박스들의 (면적 가중) 무게중심.

    면적으로 가중하는 이유: 단체 사진에서 뒤쪽 작은 얼굴보다 앞쪽 큰 얼굴이
    구도의 중심일 가능성이 높습니다.
    """
    weights = [max(f.w * f.h, 1e-6) for f in faces]
    total = sum(weights)
    cx = sum((f.x + f.w / 2) * wt for f, wt in zip(faces, weights, strict=True)) / total
    cy = sum((f.y + f.h / 2) * wt for f, wt in zip(faces, weights, strict=True)) / total
    return clamp(cx, 0.0, 1.0), clamp(cy, 0.0, 1.0)


def safe_max_zoom(
    width: int, height: int, out_w: int, out_h: int, safety: float, hard_max: float
) -> tuple[float, float]:
    """(max_zoom, headroom).

    2MP 사진에 1.3배 줌을 걸면 뭉개집니다. 원본이 출력 대비 갖고 있는 여유
    배율(headroom)이 사진마다 줌 강도를 자동으로 제한합니다.
    """
    headroom = min(width / float(out_w), height / float(out_h))
    return clamp(headroom * safety, 1.0, hard_max), headroom


def aspect_deviation(width: int, height: int, out_w: int, out_h: int) -> float:
    """출력 종횡비 대비 편차. 세로 사진을 가로 타임라인에 넣을 때 필요."""
    return abs((width / float(height)) / (out_w / float(out_h)) - 1.0)


def analyze_composition(
    img_bgr: np.ndarray | None,
    width: int,
    height: int,
    faces: list[FaceBox],
    out_w: int,
    out_h: int,
    safety: float,
    hard_max: float,
) -> Composition:
    """구도 분석 한 번에.

    POI 우선순위: 얼굴 → 엣지 무게중심 → 중앙.
    `img_bgr`가 None이면(이미지를 로드하지 않은 경로) 중앙으로 폴백합니다.
    """
    if faces:
        px, py = poi_from_faces(faces)
        source = "face"
    elif img_bgr is not None:
        px, py = poi_from_edges(img_bgr)
        source = "edges"
    else:
        px, py = 0.5, 0.5
        source = "center"

    max_zoom, headroom = safe_max_zoom(width, height, out_w, out_h, safety, hard_max)
    return Composition(
        poi_x=round(px, 5),
        poi_y=round(py, 5),
        poi_source=source,
        max_zoom=round(max_zoom, 5),
        aspect_dev=round(aspect_deviation(width, height, out_w, out_h), 5),
        headroom=round(headroom, 5),
    )


def draw_poi_marker(img_bgr: np.ndarray, comp: Composition) -> np.ndarray:
    """POI를 눈으로 검증하기 위한 마커 오버레이 (CLI `pvt poi`용)."""
    out = img_bgr.copy()
    h, w = out.shape[:2]
    cx, cy = int(comp.poi_x * w), int(comp.poi_y * h)
    color = (0, 255, 0) if comp.poi_source == "face" else (0, 200, 255)
    r = max(8, min(w, h) // 40)
    cv2.circle(out, (cx, cy), r, color, max(2, r // 6))
    cv2.line(out, (cx - r * 2, cy), (cx + r * 2, cy), color, max(1, r // 8))
    cv2.line(out, (cx, cy - r * 2), (cx, cy + r * 2), color, max(1, r // 8))
    label = f"{comp.poi_source} zoom<={comp.max_zoom:.2f} dev={comp.aspect_dev:.2f}"
    cv2.putText(out, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    return out
