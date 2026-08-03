"""측정 스펙 (섹션 5)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
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


def _reference_stats(img: np.ndarray) -> dict:
    """정의 그대로의 느린 구현. 최적화된 measure()의 기준값입니다."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L = lab[..., 0].astype(np.float32) * 100.0 / 255.0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    p05, p95 = (float(v) for v in np.percentile(L, [5, 95]))
    h = hsv[..., 0].astype(np.float32) * 2.0
    mask = hsv[..., 1] >= 25
    if mask.any():
        rad = np.deg2rad(h[mask])
        hue = float(np.rad2deg(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean()))) % 360.0
    else:
        hue = 0.0
    b, g, r = (img[..., i].astype(np.float32).mean() for i in range(3))
    neutral = (b + g + r) / 3.0
    return {
        "median_L": float(np.median(L)),
        "p05_L": p05,
        "p95_L": p95,
        "clip_black_pct": float((L < 2).mean() * 100.0),
        "clip_white_pct": float((L > 98).mean() * 100.0),
        "mean_sat": float(hsv[..., 1].mean() / 255.0),
        "mean_hue": hue,
        "wb_r": float(neutral / max(r, 1e-6)),
        "wb_b": float(neutral / max(b, 1e-6)),
    }


def test_히스토그램_기반_통계가_정의와_일치한다(tmp_path: Path):
    """measure()는 속도를 위해 256빈 히스토그램에서 백분위를 뽑습니다.

    L 채널이 이미 uint8이라 정보 손실이 없어야 합니다 — 정의 그대로 계산한
    값과 부동소수 오차 수준에서 같아야 합니다.
    """
    for i, (w, h, bright) in enumerate([(800, 600, 60), (640, 480, 128), (500, 700, 200)]):
        img = imread(make_image(tmp_path / f"{i}.jpg", w, h, brightness=bright))
        ref = _reference_stats(img)
        got = measure(img)
        for key in ("median_L", "p05_L", "p95_L", "clip_black_pct", "clip_white_pct",
                    "mean_sat", "mean_hue"):
            assert getattr(got, key) == pytest.approx(ref[key], abs=1e-3), key
        assert got.wb_gains["r"] == pytest.approx(ref["wb_r"], abs=1e-4)
        assert got.wb_gains["b"] == pytest.approx(ref["wb_b"], abs=1e-4)


def test_클리핑_경계가_정확하다():
    """L < 2, L > 98 경계에서 한 칸씩 밀리기 쉬운 자리입니다."""
    # lab L = 5 → 0~100 스케일로 1.96 (< 2 이므로 검정 클리핑)
    # lab L = 6 → 2.35 (>= 2 이므로 아님)
    for lab_l, expect_black in ((5, True), (6, False)):
        img = np.zeros((40, 40, 3), np.uint8)
        img[:] = cv2.cvtColor(
            np.full((1, 1, 3), (lab_l, 128, 128), np.uint8), cv2.COLOR_LAB2BGR
        )[0, 0]
        s = measure(img)
        ref = _reference_stats(img)
        assert s.clip_black_pct == pytest.approx(ref["clip_black_pct"], abs=1e-6)
        assert (s.clip_black_pct > 50) is expect_black, f"lab_L={lab_l}"

    for lab_l, expect_white in ((251, True), (249, False)):
        img = np.zeros((40, 40, 3), np.uint8)
        img[:] = cv2.cvtColor(
            np.full((1, 1, 3), (lab_l, 128, 128), np.uint8), cv2.COLOR_LAB2BGR
        )[0, 0]
        s = measure(img)
        ref = _reference_stats(img)
        assert s.clip_white_pct == pytest.approx(ref["clip_white_pct"], abs=1e-6)
        assert (s.clip_white_pct > 50) is expect_white, f"lab_L={lab_l}"
