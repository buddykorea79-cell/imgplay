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
    # cv2.mean은 채널 평균을 한 번에 구합니다. 채널별 astype+mean보다 훨씬 빠릅니다.
    b, g, r = (float(v) for v in cv2.mean(img)[:3])
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

    H는 이미 0~179의 정수로 양자화되어 있으므로, 픽셀마다 sin/cos를 계산하는
    대신 180빈 히스토그램을 만들어 빈 단위로 합산합니다. 결과는 같고 훨씬 빠릅니다.
    """
    sat = np.ascontiguousarray(hsv[..., 1])
    mask = cv2.inRange(sat, np.array([sat_floor]), np.array([255]))
    hist = cv2.calcHist([hsv], [0], mask, [180], [0, 180]).ravel()
    total = float(hist.sum())
    if total <= 0:
        return 0.0
    rad = np.deg2rad(np.arange(180, dtype=np.float32) * 2.0)  # H 0~179 → 0~358도
    angle = float(
        np.rad2deg(
            np.arctan2((np.sin(rad) * hist).sum() / total, (np.cos(rad) * hist).sum() / total)
        )
    )
    return angle % 360.0


def _percentile_from_hist(cdf: np.ndarray, total: float, q: float) -> float:
    """uint8 히스토그램 CDF에서 백분위를 구한다 (0~255 스케일).

    L 채널은 이미 uint8이라 256빈 히스토그램에 정보 손실이 없습니다. 12M 픽셀을
    정렬하는 `np.percentile`보다 훨씬 빠르면서 같은 값을 돌려줍니다.
    """
    target = q / 100.0 * (total - 1)
    idx = int(np.searchsorted(cdf, target, side="right"))
    return float(min(idx, 255))


def measure(img_bgr: np.ndarray) -> Stats:
    """BGR 이미지에서 규칙 계산에 필요한 통계를 뽑는다."""
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        raise ValueError("BGR 3채널 이미지가 필요합니다")

    h, w = img_bgr.shape[:2]

    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    # L(uint8) 히스토그램 하나에서 백분위·클리핑·32빈 히스토그램을 모두 뽑는다.
    # 12M 픽셀 배열을 여러 번 훑는 대신 256개 빈만 다루면 된다.
    counts = cv2.calcHist([lab], [0], None, [256], [0, 256]).ravel()
    total = float(counts.sum()) or 1.0
    cdf = np.cumsum(counts)

    to100 = 100.0 / 255.0
    p05 = _percentile_from_hist(cdf, total, 5.0) * to100
    p95 = _percentile_from_hist(cdf, total, 95.0) * to100
    median_L = _percentile_from_hist(cdf, total, 50.0) * to100

    # L < 2 와 L > 98 (0~100 스케일)을 uint8 인덱스 경계로 옮긴다.
    #   i < t 를 만족하는 인덱스 개수 = ceil(t)   (t가 정수여도 성립)
    #   i > t 를 만족하는 첫 인덱스     = floor(t) + 1
    black_end = int(np.ceil(2.0 / to100))          # counts[:black_end]
    white_start = int(np.floor(98.0 / to100)) + 1  # counts[white_start:]
    clip_black = float(counts[:black_end].sum()) / total * 100.0
    clip_white = float(counts[white_start:].sum()) / total * 100.0

    # 256빈을 32빈으로 재구간화 (256 = 32 × 8이라 정확히 나뉜다)
    hist_norm = (counts.reshape(HIST_BINS, -1).sum(axis=1) / total).astype(np.float32)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    small = resize_long_edge(gray, SHARPNESS_LONG_EDGE)
    sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())

    return Stats(
        median_L=median_L,
        p05_L=p05,
        p95_L=p95,
        spread_L=p95 - p05,
        clip_black_pct=clip_black,
        clip_white_pct=clip_white,
        mean_sat=float(cv2.mean(hsv)[1] / 255.0),
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
