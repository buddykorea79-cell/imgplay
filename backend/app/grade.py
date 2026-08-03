"""통계 + grade.yaml → 보정 파라미터 (섹션 6).

적용 순서는 고정입니다:
  1. 원시값 계산
  2. 가드 적용 (상한 덮어쓰기)
  3. 클램프
  4. **어떤 항목이 클램프에 걸렸는지 기록**

4번이 이 도구의 실질적 출력입니다. 클램프에 걸렸다는 건 규칙이 감당하지 못하는
사진이 있다는 뜻이고, 사용자가 알아야 할 유일한 신호입니다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .exif import Exif
from .measure import Stats
from .schemas import GradeRules

__all__ = ["GradeResult", "compute_grade", "clamp"]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(slots=True)
class GradeResult:
    gamma: float
    contrast: float
    saturation: float
    unsharp: float
    wb: dict[str, float]
    wb_enabled: bool
    clamped: list[str] = field(default_factory=list)
    guards_applied: list[str] = field(default_factory=list)


def _is_night(exif: Exif, rules: GradeRules) -> bool:
    """EXIF 기반 야경 판정. 근거가 하나도 없으면 판정하지 않는다."""
    g = rules.guards.night
    if not g.enabled:
        return False
    if exif.iso is not None and exif.iso >= g.iso_min:
        return True
    if exif.exposure_time is not None and exif.exposure_time >= g.shutter_max:
        # 셔터가 느리다 = 빛이 부족했다. shutter_max는 "이보다 느리면 야간".
        return True
    if exif.datetime_original is not None:
        start, end = g.hour_range
        hour = exif.datetime_original.hour
        # 19~6처럼 자정을 넘는 구간을 지원한다.
        in_range = (start <= hour or hour < end) if start > end else (start <= hour < end)
        if in_range:
            return True
    return False


def _apply_wb_deviation(gains: dict[str, float], max_dev: float) -> dict[str, float]:
    """화이트밸런스 게인을 1.0 기준 ±max_deviation으로 제한한다.

    그레이월드는 화면이 한 색으로 덮인 사진(노을, 단풍, 수영장)에서 크게 틀립니다.
    편차 상한이 그 폭주를 막습니다.
    """
    return {k: clamp(v, 1.0 - max_dev, 1.0 + max_dev) for k, v in gains.items()}


def compute_grade(
    stats: Stats,
    exif: Exif,
    rules: GradeRules,
    has_face: bool = False,
) -> GradeResult:
    """통계 한 장 + 규칙 → 보정 파라미터."""
    clamped: list[str] = []
    guards: list[str] = []

    # --- 1. 원시값 -----------------------------------------------------
    tgt = rules.target

    if rules.gamma.enabled and stats.median_L > 0.5:
        # eq의 gamma는 out = in^(1/gamma) 이므로, median_L을 target으로 옮기려면
        # log 비율을 그대로 쓰면 된다.
        gamma_raw = math.log(stats.median_L / 100.0) / math.log(tgt.median_L / 100.0)
    else:
        gamma_raw = 1.0

    spread = max(stats.spread_L, 1e-3)
    contrast_raw = tgt.spread_L / spread
    if max(stats.clip_black_pct, stats.clip_white_pct) > rules.contrast.clip_threshold_pct:
        contrast_raw -= rules.contrast.clip_penalty

    sat = max(stats.mean_sat, 1e-3)
    saturation_raw = tgt.mean_sat / sat

    unsharp_raw = rules.unsharp.base - stats.sharpness / rules.unsharp.divisor

    # --- 2. 가드: 상한 덮어쓰기 ----------------------------------------
    gamma_max = rules.gamma.max
    sat_max = rules.saturation.max
    contrast_max = rules.contrast.max

    if _is_night(exif, rules):
        guards.append("night")
        gamma_max = min(gamma_max, rules.guards.night.gamma_max)
        sat_max = min(sat_max, rules.guards.night.saturation_max)
    elif rules.guards.lowkey.enabled and stats.median_L < rules.guards.lowkey.median_L_below:
        # EXIF가 없는 사진의 폴백. 야간 가드가 이미 걸렸으면 중복 적용하지 않는다.
        guards.append("lowkey")
        gamma_max = min(gamma_max, rules.guards.lowkey.gamma_max)

    hc = rules.guards.highcontrast
    if hc.enabled and stats.spread_L > hc.spread_L_above:
        guards.append("highcontrast")
        contrast_max = min(contrast_max, hc.contrast_max)

    if has_face:
        guards.append("face")
        sat_max = min(sat_max, rules.saturation.skin_max)

    # --- 3+4. 클램프 및 히트 기록 --------------------------------------
    def _clamped(name: str, raw: float, lo: float, hi: float) -> float:
        out = clamp(raw, lo, hi)
        # 부동소수 비교이므로 허용오차를 둔다. 1e-9는 규칙 값의 유효자리보다 훨씬 작다.
        if abs(out - raw) > 1e-9:
            clamped.append(name)
        return out

    gamma = _clamped("gamma", gamma_raw, rules.gamma.min, gamma_max)
    contrast = _clamped("contrast", contrast_raw, rules.contrast.min, contrast_max)
    saturation = _clamped("saturation", saturation_raw, rules.saturation.min, sat_max)
    unsharp = _clamped("unsharp", unsharp_raw, rules.unsharp.min, rules.unsharp.max)

    wb_enabled = rules.whitebalance.enabled
    wb = _apply_wb_deviation(stats.wb_gains, rules.whitebalance.max_deviation)
    if wb_enabled and any(
        abs(wb[k] - stats.wb_gains[k]) > 1e-9 for k in ("r", "g", "b")
    ):
        clamped.append("whitebalance")

    return GradeResult(
        gamma=gamma,
        contrast=contrast,
        saturation=saturation,
        unsharp=unsharp,
        wb=wb,
        wb_enabled=wb_enabled,
        clamped=clamped,
        guards_applied=guards,
    )
