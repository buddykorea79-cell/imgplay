"""ffmpeg 렌더 검증 (섹션 10). ffmpeg 바이너리가 필요합니다."""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.ffmpeg_motion import build_clip_filter, clip_cache_name, render_clip
from app.ffmpeg_util import ffprobe_duration
from app.imageio import imwrite
from app.schemas import MotionParams, MotionRules

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg가 없습니다"
)


def mkparams(**kw) -> MotionParams:
    base = dict(
        id="x", index=0, duration_sec=2.0, zoom_start=1.0, zoom_end=1.12,
        dx=0.0, dy=0.0, poi_x=0.5, poi_y=0.5, max_zoom=1.35,
        aspect_dev=0.0, aspect_mode="none", ease="linear", clamped=[],
    )
    base.update(kw)
    return MotionParams(**base)


@pytest.fixture
def chart(tmp_path: Path) -> Path:
    """무노이즈 차트: 25% 지점에 완벽한 수평 엣지."""
    h, w = 2160, 3840
    img = np.zeros((h, w, 3), np.uint8)
    img[int(h * 0.25):] = 255
    p = tmp_path / "chart.png"
    imwrite(p, img)
    return p


def _edge_positions(path: Path) -> np.ndarray:
    """프레임별 엣지의 서브픽셀 y좌표 (50% 밝기 교차점).

    기울기 무게중심 방식은 lanczos 링잉에 흔들리므로 교차점을 씁니다.
    """
    cap = cv2.VideoCapture(str(path))
    ys: list[float] = []
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            col = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32).mean(axis=1)
            mid = (col.min() + col.max()) / 2
            i = int(np.argmax(col > mid))
            if i == 0:
                continue
            y0, y1 = col[i - 1], col[i]
            ys.append(i - 1 + (mid - y0) / max(y1 - y0, 1e-9))
    finally:
        cap.release()
    return np.asarray(ys)


# ------------------------------------------------------------------ 필터 문자열


def test_d는_초가_아니라_프레임_수다():
    """가장 흔한 버그입니다."""
    rules = MotionRules()
    chain = build_clip_filter(mkparams(duration_sec=5.0), rules.output, rules)
    assert ":d=150" in chain, f"d가 프레임 수가 아님: {chain}"


def test_fps가_명시된다():
    """생략하면 25로 기본값이 잡혀 출력 fps와 어긋납니다."""
    rules = MotionRules()
    chain = build_clip_filter(mkparams(), rules.output, rules)
    assert f":fps={rules.output.fps}" in chain


def test_업스케일_후_zoompan():
    """확대 전에 업스케일하지 않으면 뭉개지고 떨립니다."""
    from app.ffmpeg_motion import UPSCALE_FACTOR

    rules = MotionRules()
    chain = build_clip_filter(mkparams(), rules.output, rules)
    sw = rules.output.width * UPSCALE_FACTOR
    assert f"scale={sw}:" in chain
    assert chain.index("scale=") < chain.index("zoompan="), "업스케일이 zoompan보다 뒤"
    assert f"s={rules.output.width}x{rules.output.height}" in chain


def test_blur_fill_배경은_zoompan보다_먼저():
    """순서가 반대면 배경까지 같이 줌돼서 어지러워집니다."""
    rules = MotionRules()
    chain = build_clip_filter(mkparams(aspect_mode="blur_fill"), rules.output, rules)
    assert "gblur" in chain
    assert chain.index("gblur") < chain.index("zoompan="), "블러 배경이 zoompan 뒤에 있음"
    assert "overlay" in chain


def test_yuv420p로_통일된다():
    """xfade는 두 입력의 픽셀포맷이 완전히 같아야 합니다."""
    rules = MotionRules()
    assert "format=yuv420p" in build_clip_filter(mkparams(), rules.output, rules)


def test_클립_캐시_키는_파라미터가_바뀌면_달라진다():
    """모션 슬라이더를 만져도 바뀐 클립만 다시 렌더되어야 합니다."""
    rules, out = MotionRules(), MotionRules().output
    a = clip_cache_name("hash1", mkparams(), out, rules, None)
    assert a == clip_cache_name("hash1", mkparams(), out, rules, None)
    assert a != clip_cache_name("hash1", mkparams(zoom_end=1.2), out, rules, None)
    assert a != clip_cache_name("hash2", mkparams(), out, rules, None)
    assert a != clip_cache_name("hash1", mkparams(), out, rules, 540)
    # index는 캐시 키에서 빠져야 한다 — 순서만 바꿨는데 전부 다시 렌더되면 안 된다
    assert a == clip_cache_name("hash1", mkparams(index=7), out, rules, None)


# ------------------------------------------------------------------ 실제 렌더


def test_클립_길이와_규격(chart: Path, tmp_path: Path):
    rules = MotionRules()
    dst = tmp_path / "c.mp4"
    render_clip(chart, dst, mkparams(duration_sec=2.0), rules.output, rules)
    assert dst.is_file()
    assert ffprobe_duration(dst) == pytest.approx(2.0, abs=0.1)

    cap = cv2.VideoCapture(str(dst))
    assert int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == rules.output.width
    assert int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == rules.output.height
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 60  # 2초 × 30fps
    cap.release()


def test_미리보기_높이(chart: Path, tmp_path: Path):
    rules = MotionRules()
    dst = tmp_path / "p.mp4"
    render_clip(chart, dst, mkparams(duration_sec=1.0), rules.output, rules, height=540)
    cap = cv2.VideoCapture(str(dst))
    assert int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 540
    assert int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 960  # 16:9 유지
    cap.release()


def test_업스케일이_떨림을_줄인다(chart: Path, tmp_path: Path):
    """완료 기준: 줌이 떨리지 않는다 (4배 업스케일 확인).

    zoompan은 크롭 좌표를 정수로 자릅니다. 업스케일 없이 1080p에서 바로 줌하면
    프레임당 이동이 0.2px 수준이라 4~5프레임에 한 번씩 1px씩 튀어오릅니다.
    4배로 키워두면 그 계단이 1/4로 줄어듭니다.
    """
    import app.ffmpeg_motion as fm

    rules = MotionRules()
    p = mkparams(duration_sec=4.0, zoom_end=1.12)
    original = fm.UPSCALE_FACTOR
    measurements = {}
    try:
        for factor in (1, 4):
            fm.UPSCALE_FACTOR = factor
            dst = tmp_path / f"x{factor}.mp4"
            render_clip(chart, dst, p, rules.output, rules)
            steps = np.diff(_edge_positions(dst))
            med = float(np.median(steps))
            measurements[factor] = {
                "sigma": float(np.std(steps)),
                "max_dev": float(np.max(np.abs(steps - med))),
            }
    finally:
        fm.UPSCALE_FACTOR = original

    x1, x4 = measurements[1], measurements[4]
    assert x4["sigma"] < x1["sigma"] / 3, (
        f"4배 업스케일이 떨림을 줄이지 못함: σ x1={x1['sigma']:.3f} x4={x4['sigma']:.3f}"
    )
    assert x4["max_dev"] < 1.0, f"프레임당 이탈이 1px를 넘음: {x4['max_dev']:.3f}px"


def test_줌아웃도_동작한다(chart: Path, tmp_path: Path):
    """줌아웃은 시작 줌을 target으로 두고 감소시킵니다."""
    rules = MotionRules()
    dst = tmp_path / "out.mp4"
    render_clip(chart, dst, mkparams(zoom_start=1.12, zoom_end=1.0), rules.output, rules)

    ys = _edge_positions(dst)
    assert len(ys) > 10
    # 줌인과 반대 방향으로 엣지가 움직여야 한다
    dst_in = tmp_path / "in.mp4"
    render_clip(chart, dst_in, mkparams(zoom_start=1.0, zoom_end=1.12), rules.output, rules)
    ys_in = _edge_positions(dst_in)
    assert np.sign(ys[-1] - ys[0]) == -np.sign(ys_in[-1] - ys_in[0])


def test_세로_사진은_블러_배경으로_채워진다(tmp_path: Path):
    """완료 기준: 세로 사진이 블러 배경으로 채워지고, 배경이 같이 줌되지 않는다."""
    portrait = np.zeros((1600, 900, 3), np.uint8)
    portrait[:, :] = (40, 90, 200)
    portrait[600:1000, 200:700] = (255, 255, 255)  # 중앙 흰 블록
    src = tmp_path / "portrait.png"
    imwrite(src, portrait)

    rules = MotionRules()
    dst = tmp_path / "p.mp4"
    render_clip(
        src, dst, mkparams(duration_sec=1.0, aspect_mode="blur_fill", aspect_dev=0.6),
        rules.output, rules,
    )
    cap = cv2.VideoCapture(str(dst))
    ok, frame = cap.read()
    cap.release()
    assert ok
    assert frame.shape[:2] == (1080, 1920)
    # 좌우 가장자리는 블러 배경 — 레터박스(검정)가 아니어야 한다
    left_edge = frame[:, :40].mean()
    assert left_edge > 20, f"좌측이 검정 레터박스입니다 (평균 {left_edge:.1f})"


def test_ease_in_out_식이_생성된다():
    rules = MotionRules()
    chain = build_clip_filter(mkparams(ease="ease_in_out"), rules.output, rules)
    assert "3-2*" in chain, "smoothstep 곡선이 없습니다"
