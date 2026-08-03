"""1단계 규칙과 클램프 히트 기록 (섹션 6)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.exif import Exif
from app.grade import compute_grade
from app.measure import Stats
from app.schemas import GradeRules


def mkstats(**kw) -> Stats:
    base = dict(
        median_L=50.0, p05_L=20.0, p95_L=75.0, spread_L=55.0,
        clip_black_pct=0.1, clip_white_pct=0.1, mean_sat=0.42,
        sharpness=200.0, wb_gains={"r": 1.0, "g": 1.0, "b": 1.0},
        hist_L=[1 / 32] * 32, mean_hue=180.0, width=4000, height=3000,
    )
    base.update(kw)
    return Stats(**base)


@pytest.fixture
def rules() -> GradeRules:
    return GradeRules()


def test_타깃과_일치하면_보정이_거의_없다(rules):
    r = compute_grade(mkstats(), Exif(), rules)
    assert abs(r.gamma - 1.0) < 0.02
    assert abs(r.contrast - 1.0) < 0.02
    assert abs(r.saturation - 1.0) < 0.02
    assert r.clamped == []


def test_어두운_사진은_감마가_올라간다(rules):
    r = compute_grade(mkstats(median_L=30.0), Exif(), rules)
    assert r.gamma > 1.0


def test_밝은_사진은_감마가_내려간다(rules):
    r = compute_grade(mkstats(median_L=75.0), Exif(), rules)
    assert r.gamma < 1.0


def test_클램프에_걸리면_기록된다(rules):
    """이 목록이 이 도구의 실질적 출력입니다."""
    r = compute_grade(mkstats(median_L=5.0, spread_L=5.0, mean_sat=0.02), Exif(), rules)
    assert "gamma" in r.clamped
    assert "contrast" in r.clamped
    assert "saturation" in r.clamped
    assert r.gamma <= rules.gamma.max
    assert r.contrast <= rules.contrast.max


def test_클리핑이_심하면_대비에_페널티(rules):
    # spread를 클램프 대역 안(0.92~1.28)에 두어야 페널티가 눈에 보인다.
    without = compute_grade(mkstats(spread_L=52.0), Exif(), rules)
    with_clip = compute_grade(mkstats(spread_L=52.0, clip_white_pct=5.0), Exif(), rules)
    assert without.clamped == []
    assert with_clip.contrast == pytest.approx(
        without.contrast - rules.contrast.clip_penalty, abs=1e-6
    )


def test_야간_가드는_감마를_1_10으로_제한한다(rules):
    """완료 기준: 야경 사진에 야간 가드가 걸려 감마가 1.10을 넘지 않는다."""
    dark = mkstats(median_L=20.0)  # 가드 없으면 감마가 1.35까지 올라갈 상황

    no_guard = compute_grade(dark, Exif(), rules)
    assert no_guard.gamma > 1.10  # 대조군: 가드가 없으면 넘어간다

    for exif in (
        Exif(iso=3200),
        Exif(exposure_time=1 / 8),
        Exif(datetime_original=datetime(2024, 5, 1, 22, 30)),
    ):
        r = compute_grade(dark, exif, rules)
        assert "night" in r.guards_applied, f"야간 판정 실패: {exif}"
        assert r.gamma <= 1.10 + 1e-9, f"야간 감마 상한 초과: {r.gamma}"


def test_야간_시간대는_자정을_넘어간다(rules):
    """hour_range [19, 6]은 19시~다음날 6시입니다."""
    dark = mkstats(median_L=20.0)

    def guards_at(hour: int) -> list[str]:
        exif = Exif(datetime_original=datetime(2024, 5, 1, hour, 0))
        return compute_grade(dark, exif, rules).guards_applied

    assert "night" in guards_at(2)       # 자정 넘어 새벽
    assert "night" in guards_at(21)      # 저녁
    assert "night" not in guards_at(12)  # 한낮


def test_lowkey_가드는_exif가_없을_때_폴백(rules):
    r = compute_grade(mkstats(median_L=20.0), Exif(), rules)
    assert "lowkey" in r.guards_applied
    assert r.gamma <= rules.guards.lowkey.gamma_max + 1e-9


def test_highcontrast_가드(rules):
    r = compute_grade(mkstats(spread_L=85.0), Exif(), rules)
    assert "highcontrast" in r.guards_applied
    assert r.contrast <= rules.guards.highcontrast.contrast_max + 1e-9


def test_얼굴이_있으면_채도_상한이_skin_max(rules):
    low_sat = mkstats(mean_sat=0.20)  # 보정 없으면 채도가 2.1배까지 올라갈 상황
    no_face = compute_grade(low_sat, Exif(), rules, has_face=False)
    with_face = compute_grade(low_sat, Exif(), rules, has_face=True)
    assert with_face.saturation <= rules.saturation.skin_max + 1e-9
    assert with_face.saturation < no_face.saturation
    assert "face" in with_face.guards_applied


def test_화이트밸런스_편차_상한(rules):
    r = compute_grade(mkstats(wb_gains={"r": 2.0, "g": 1.0, "b": 0.4}), Exif(), rules)
    assert r.wb["r"] <= 1.0 + rules.whitebalance.max_deviation + 1e-9
    assert r.wb["b"] >= 1.0 - rules.whitebalance.max_deviation - 1e-9
    assert "whitebalance" in r.clamped


def test_선명한_사진은_언샤프가_약하다(rules):
    soft = compute_grade(mkstats(sharpness=50.0), Exif(), rules)
    sharp = compute_grade(mkstats(sharpness=450.0), Exif(), rules)
    assert sharp.unsharp < soft.unsharp


def test_감마_비활성화(rules):
    rules.gamma.enabled = False
    r = compute_grade(mkstats(median_L=20.0), Exif(), rules)
    assert r.gamma == 1.0


def test_완전_검정에서_터지지_않는다(rules):
    r = compute_grade(
        mkstats(median_L=0.0, spread_L=0.0, mean_sat=0.0, clip_black_pct=100.0),
        Exif(), rules,
    )
    assert all(
        v == v and abs(v) < 1e6 for v in (r.gamma, r.contrast, r.saturation, r.unsharp)
    )
