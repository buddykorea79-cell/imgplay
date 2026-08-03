"""2단계 규칙: 구도, 모션, 전환, 타임라인 (섹션 8~10)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from app.compose import Composition, analyze_composition, poi_from_edges, safe_max_zoom
from app.measure import Stats
from app.motion import compute_motion
from app.schemas import FaceBox, MotionParams, MotionRules, TransitionSpec
from app.timeline import (
    TimelineEntry,
    decide_transitions,
    sort_by_capture_time,
    total_duration,
    xfade_offsets,
)


def mkstats(width=4000, height=3000, **kw) -> Stats:
    base = dict(
        median_L=50.0, p05_L=20.0, p95_L=75.0, spread_L=55.0,
        clip_black_pct=0.1, clip_white_pct=0.1, mean_sat=0.42, sharpness=200.0,
        wb_gains={"r": 1.0, "g": 1.0, "b": 1.0}, hist_L=[1 / 32] * 32,
        mean_hue=180.0, width=width, height=height,
    )
    base.update(kw)
    return Stats(**base)


def mkcomp(**kw) -> Composition:
    base = dict(poi_x=0.5, poi_y=0.5, poi_source="edges", max_zoom=1.35,
                aspect_dev=0.0, headroom=1.5)
    base.update(kw)
    return Composition(**base)


# ------------------------------------------------------------------ 구도


def test_poi는_엣지가_몰린_쪽으로_간다():
    """무작위가 아니라 사진에서 계산되어야 합니다."""
    img = np.zeros((400, 600, 3), dtype=np.uint8)
    # 우상단에만 고주파 패턴을 넣는다
    img[40:120, 420:560:4] = 255
    x, y = poi_from_edges(img)
    assert x > 0.6, f"POI가 우측으로 가지 않음: {x}"
    assert y < 0.4, f"POI가 상단으로 가지 않음: {y}"


def test_평탄한_이미지는_중앙():
    assert poi_from_edges(np.full((200, 200, 3), 128, np.uint8)) == (0.5, 0.5)


def test_얼굴이_있으면_얼굴이_우선(monkeypatch):
    faces = [FaceBox(x=0.7, y=0.1, w=0.1, h=0.1, confidence=0.9)]
    c = analyze_composition(None, 4000, 3000, faces, 1920, 1080, 0.9, 1.35)
    assert c.poi_source == "face"
    assert c.poi_x == pytest.approx(0.75)
    assert c.poi_y == pytest.approx(0.15)


def test_큰_얼굴이_무게중심을_끈다():
    faces = [
        FaceBox(x=0.05, y=0.4, w=0.3, h=0.3, confidence=0.9),   # 큰 얼굴 (앞쪽)
        FaceBox(x=0.9, y=0.4, w=0.05, h=0.05, confidence=0.9),  # 작은 얼굴 (뒤쪽)
    ]
    c = analyze_composition(None, 4000, 3000, faces, 1920, 1080, 0.9, 1.35)
    assert c.poi_x < 0.4


def test_안전_줌은_해상도_여유로_제한된다():
    """2MP 사진에 1.3배 줌을 걸면 뭉개집니다."""
    big, _ = safe_max_zoom(6000, 4000, 1920, 1080, 0.9, 1.35)
    assert big == pytest.approx(1.35)  # hard_max에 도달

    small, headroom = safe_max_zoom(1600, 1200, 1920, 1080, 0.9, 1.35)
    assert headroom < 1.0
    assert small == 1.0, "저해상도인데 줌이 허용됨"


def test_종횡비_편차():
    c = analyze_composition(None, 1920, 1080, [], 1920, 1080, 0.9, 1.35)
    assert c.aspect_dev == pytest.approx(0.0)
    portrait = analyze_composition(None, 1080, 1920, [], 1920, 1080, 0.9, 1.35)
    assert portrait.aspect_dev > 0.5


# ------------------------------------------------------------------ 모션


def test_저해상도는_max_zoom_클램프가_걸린다():
    """완료 기준: 저해상도 사진에서 max_zoom 클램프가 걸리고 배지가 표시된다."""
    rules = MotionRules()
    m = compute_motion("a", 0, mkstats(1600, 1200), mkcomp(max_zoom=1.0), rules)
    assert "max_zoom" in m.clamped
    assert m.zoom_start == m.zoom_end == 1.0


def test_충분한_해상도에서는_클램프가_없다():
    m = compute_motion("a", 0, mkstats(), mkcomp(), MotionRules())
    assert "max_zoom" not in m.clamped
    assert max(m.zoom_start, m.zoom_end) == pytest.approx(1.12)


def test_줌_방향_alternate():
    rules = MotionRules()
    rules.zoom.direction = "alternate"
    even = compute_motion("a", 0, mkstats(), mkcomp(), rules)
    odd = compute_motion("b", 1, mkstats(), mkcomp(), rules)
    assert even.zoom_start < even.zoom_end   # in
    assert odd.zoom_start > odd.zoom_end     # out


def test_줌_방향_auto는_poi에서_계산된다():
    """무작위 줌 방향 금지 — 구도에서 결정되어야 합니다."""
    rules = MotionRules()
    off = compute_motion("a", 0, mkstats(), mkcomp(poi_x=0.85), rules)
    assert off.zoom_start < off.zoom_end, "POI가 치우쳤는데 줌인이 아님"
    centered = compute_motion("b", 0, mkstats(), mkcomp(poi_x=0.5, poi_y=0.5), rules)
    assert centered.zoom_start > centered.zoom_end

    # 결정적이어야 한다: 같은 입력 → 같은 출력
    again = compute_motion("a", 0, mkstats(), mkcomp(poi_x=0.85), rules)
    assert (again.zoom_start, again.zoom_end) == (off.zoom_start, off.zoom_end)


def test_팬은_poi_방향이고_상한이_있다():
    rules = MotionRules()
    m = compute_motion("a", 0, mkstats(), mkcomp(poi_x=0.9, poi_y=0.1), rules)
    assert m.dx > 0 and m.dy < 0
    assert abs(m.dx) <= rules.pan.max_offset + 1e-9
    assert abs(m.dy) <= rules.pan.max_offset + 1e-9


def test_종횡비_임계값_초과시_모드가_적용된다():
    rules = MotionRules()
    ok = compute_motion("a", 0, mkstats(), mkcomp(aspect_dev=0.05), rules)
    assert ok.aspect_mode == "none"
    bad = compute_motion("b", 0, mkstats(), mkcomp(aspect_dev=0.6), rules)
    assert bad.aspect_mode == "blur_fill"
    assert "aspect" in bad.clamped


def test_지속시간_클램프():
    rules = MotionRules()
    rules.duration.base_sec = 20.0
    m = compute_motion("a", 0, mkstats(), mkcomp(), rules)
    assert m.duration_sec == rules.duration.max_sec
    assert "duration" in m.clamped


# ------------------------------------------------------------------ 타임라인


def test_촬영시각_정렬():
    t = datetime(2024, 5, 1, 12, 0)
    entries = [
        TimelineEntry("c", "c.jpg", t + timedelta(minutes=10)),
        TimelineEntry("a", "a.jpg", t),
        TimelineEntry("b", "b.jpg", t + timedelta(minutes=5)),
    ]
    assert sort_by_capture_time(entries) == ["a", "b", "c"]


def test_시각이_없는_사진은_뒤로_간다():
    """1970년으로 취급해 맨 앞에 몰아넣으면 타임라인이 엉망이 됩니다."""
    t = datetime(2024, 5, 1, 12, 0)
    entries = [
        TimelineEntry("no", "zzz.jpg", None),
        TimelineEntry("yes", "aaa.jpg", t),
    ]
    assert sort_by_capture_time(entries) == ["yes", "no"]


def test_전환_유사하면_fade_다르면_fadeblack():
    rules = MotionRules()
    flat = [1 / 32] * 32
    dark = [1.0] + [0.0] * 31
    hists = {"a": flat, "b": flat, "c": dark}
    caps = {"a": None, "b": None, "c": None}

    specs = decide_transitions(["a", "b", "c"], hists, caps, rules)
    assert specs[0].type == rules.transition.on_similar
    assert specs[1].type == rules.transition.on_different


def test_촬영_간격이_크면_fadeblack():
    """완료 기준: 촬영 간격이 큰 지점에서 전환이 fadeblack으로 바뀐다."""
    rules = MotionRules()
    flat = [1 / 32] * 32
    t = datetime(2024, 5, 1, 12, 0)
    specs = decide_transitions(
        ["a", "b"],
        {"a": flat, "b": flat},                      # 그림은 똑같지만
        {"a": t, "b": t + timedelta(hours=3)},       # 3시간 뒤에 찍혔다
        rules,
    )
    assert specs[0].type == rules.transition.on_different
    assert specs[0].gap_minutes == pytest.approx(180.0)
    assert "간격" in specs[0].reason


def test_총_길이는_전환만큼_짧아진다():
    """완료 기준: 전환 반영된 총 길이가 정확히 표시된다."""
    clips = [
        MotionParams(id=str(i), index=i, duration_sec=5.0, zoom_start=1.0, zoom_end=1.1,
                     dx=0, dy=0, poi_x=0.5, poi_y=0.5, max_zoom=1.35, aspect_dev=0,
                     aspect_mode="none", ease="linear")
        for i in range(3)
    ]
    trans = [
        TransitionSpec(index=i, type="fade", duration_sec=0.8, hist_distance=0.3,
                       gap_minutes=None, reason="")
        for i in range(2)
    ]
    total, clip_sum, saving = total_duration(clips, trans)
    assert clip_sum == 15.0
    assert saving == 1.6
    assert total == pytest.approx(13.4)


def test_xfade_오프셋은_누적_길이_기준():
    """클립 길이가 아니라 지금까지 만들어진 결과물의 길이여야 합니다."""
    clips = [
        MotionParams(id=str(i), index=i, duration_sec=d, zoom_start=1.0, zoom_end=1.0,
                     dx=0, dy=0, poi_x=0.5, poi_y=0.5, max_zoom=1.35, aspect_dev=0,
                     aspect_mode="none", ease="linear")
        for i, d in enumerate([5.0, 4.0, 6.0])
    ]
    trans = [
        TransitionSpec(index=i, type="fade", duration_sec=1.0, hist_distance=0.3,
                       gap_minutes=None, reason="")
        for i in range(2)
    ]
    offsets = xfade_offsets(clips, trans)
    assert offsets[0] == pytest.approx(4.0)   # 5 - 1
    # 1차 결합 결과 길이 = 5 - 1 + 4 = 8 → 두 번째 오프셋 = 8 - 1 = 7
    assert offsets[1] == pytest.approx(7.0)
