"""측정 스펙 (섹션 5)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from conftest import make_image

from app.imageio import imread
from app.measure import HIST_BINS, hist_distance, measure


def test_기본_필드가_모두_채워진다(tmp_path: Path):
    img = imread(make_image(tmp_path / "a.jpg", 800, 600))
    s = measure(img)
    assert 0 <= s.median_L <= 100
    assert s.p05_L <= s.median_L <= s.p95_L
    assert s.spread_L == s.p95_L - s.p05_L
    assert 0 <= s.mean_sat <= 1
    assert len(s.hist_L) == HIST_BINS
    assert abs(sum(s.hist_L) - 1.0) < 1e-4
    assert (s.width, s.height) == (800, 600)


def test_밝은_사진의_median_L이_더_높다(tmp_path: Path):
    dark = measure(imread(make_image(tmp_path / "d.jpg", 400, 300, brightness=50)))
    bright = measure(imread(make_image(tmp_path / "b.jpg", 400, 300, brightness=200)))
    assert bright.median_L > dark.median_L + 20


def test_선명도는_해상도에_정규화된다(tmp_path: Path):
    """같은 장면을 크게/작게 찍어도 sharpness가 비슷해야 합니다.

    이 정규화를 빠뜨리면 unsharp 규칙 상수가 사진 크기 따라 제멋대로 움직입니다.
    """
    base = imread(make_image(tmp_path / "s.jpg", 1024, 768, detail=True))
    big = cv2.resize(base, (2048, 1536), interpolation=cv2.INTER_LANCZOS4)

    s_small = measure(base).sharpness
    s_big = measure(big).sharpness
    ratio = s_big / max(s_small, 1e-6)
    assert 0.4 < ratio < 2.5, f"해상도 정규화 실패: 비율 {ratio:.2f}"


def test_클리핑_비율(tmp_path: Path):
    black = np.zeros((100, 100, 3), dtype=np.uint8)
    assert measure(black).clip_black_pct > 99
    white = np.full((100, 100, 3), 255, dtype=np.uint8)
    assert measure(white).clip_white_pct > 99


def test_그레이월드_게인은_색편향을_되돌린다():
    """파랑이 강한 이미지는 b 게인이 1보다 작아야 합니다."""
    img = np.zeros((60, 60, 3), dtype=np.uint8)
    img[..., 0] = 200  # B
    img[..., 1] = 100
    img[..., 2] = 60   # R
    g = measure(img).wb_gains
    assert g["b"] < 1.0 < g["r"]


def test_단색_검정에서_0나눗셈이_없다():
    g = measure(np.zeros((30, 30, 3), dtype=np.uint8)).wb_gains
    assert all(np.isfinite(v) for v in g.values())


def test_mean_hue는_원형평균():
    """359도와 1도의 평균은 180도가 아니라 0도 근처여야 합니다."""
    hsv = np.zeros((40, 40, 3), dtype=np.uint8)
    hsv[:20, :, 0] = 179  # H≈358
    hsv[20:, :, 0] = 1    # H≈2
    hsv[..., 1] = 255
    hsv[..., 2] = 255
    img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    h = measure(img).mean_hue
    assert h < 20 or h > 340, f"원형 평균이 아님: {h}"


def test_히스토그램_거리(tmp_path: Path):
    a = measure(imread(make_image(tmp_path / "1.jpg", 400, 300, brightness=60)))
    b = measure(imread(make_image(tmp_path / "2.jpg", 400, 300, brightness=60)))
    c = measure(imread(make_image(tmp_path / "3.jpg", 400, 300, brightness=220)))
    assert hist_distance(a.hist_L, b.hist_L) < 0.1
    assert hist_distance(a.hist_L, c.hist_L) > 0.5
