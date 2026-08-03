"""이미지 → 통계 (섹션 5).

측정은 원본 해상도에서 합니다. 단 하나의 예외가 선명도로, 라플라시안 분산은
해상도에 비례하므로 긴 변 1024px로 정규화한 뒤 측정합니다. 이걸 빠뜨리면
`unsharp` 규칙 상수가 사진 크기에 따라 제멋대로 움직입니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .imageio import resize_long_edge

__all__ = ["Stats", "measure", "SHARPNESS_LONG_EDGE", "HIST_BINS"]

SHARPNESS_LONG_EDGE = 1024
HIST_BINS = 32


@dataclass(slots=True)
class Stats:
    median_L: float
    p05_L: float
    p95_L: float
    spread_L: float
    clip_black_pct: float
    clip_white_pct: float
    mean_sat: float
    sharpness: float
    wb_gains: dict[str, float]
    hist_L: list[float] = field(default_factory=list)
    mean_hue: float = 0.0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _white_balance_gains(img: np.ndarray) -> dict[str, float]:
    """그레이월드 가정: 채널 평균이 서로 같아지도록 하는 게인."""
    b, g, r = (img[..., i].astype(np.float32).mean() for i in range(3))
    neutral = (b + g + r) / 3.0
    # 완전 단색(예: 순수 검정) 이미지에서 0 나눗셈을 피한다.
    eps = 1e-6
    return {
        "b": float(neutral / max(b, eps)),
        "g": float(neutral / max(g, eps)),
        "r": float(neutral / max(r, eps)),
    }


def _mean_hue(hsv: np.ndarray, sat_floor: int = 25) -> float:
    """HSV H의 원형 평균(도, 0~360).

    색상은 각도라서 산술 평균이 성립하지 않습니다(359°와 1°의 평균은 180°가
    아니라 0°). 벡터 합으로 구합니다. 무채색 픽셀은 색상이 노이즈이므로
    채도 하한으로 걸러냅니다.
    """
    h = hsv[..., 0].astype(np.float32) * 2.0  # OpenCV H는 0~179 → 0~358
    s = hsv[..., 1]
    mask = s >= sat_floor
    if not mask.any():
        return 0.0
    rad = np.deg2rad(h[mask])
    angle = float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())))
    return angle % 360.0


def measure(img_bgr: np.ndarray) -> Stats:
    """BGR 이미지에서 규칙 계산에 필요한 통계를 뽑는다."""
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        raise ValueError("BGR 3채널 이미지가 필요합니다")

    h, w = img_bgr.shape[:2]

    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    L = lab[..., 0].astype(np.float32) * 100.0 / 255.0  # 0~100 정규화
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    p05, p95 = (float(v) for v in np.percentile(L, [5, 95]))

    hist = cv2.calcHist([L], [0], None, [HIST_BINS], [0.0, 100.0]).ravel()
    total = float(hist.sum()) or 1.0
    hist_norm = (hist / total).astype(np.float32)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    small = resize_long_edge(gray, SHARPNESS_LONG_EDGE)
    sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())

    return Stats(
        median_L=float(np.median(L)),
        p05_L=p05,
        p95_L=p95,
        spread_L=p95 - p05,
        clip_black_pct=float((L < 2).mean() * 100.0),
        clip_white_pct=float((L > 98).mean() * 100.0),
        mean_sat=float(hsv[..., 1].mean() / 255.0),
        sharpness=sharpness,
        wb_gains=_white_balance_gains(img_bgr),
        hist_L=[float(v) for v in hist_norm],
        mean_hue=_mean_hue(hsv),
        width=int(w),
        height=int(h),
    )


def hist_distance(hist_a: list[float], hist_b: list[float]) -> float:
    """두 휘도 히스토그램의 Bhattacharyya 거리 (0=동일, 1=완전히 다름)."""
    a = np.asarray(hist_a, dtype=np.float32).reshape(-1, 1)
    b = np.asarray(hist_b, dtype=np.float32).reshape(-1, 1)
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return 1.0
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))
