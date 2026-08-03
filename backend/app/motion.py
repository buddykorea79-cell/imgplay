"""통계 + 구도 + motion.yaml → 모션 파라미터 (섹션 9).

1단계와 동일하게 **클램프 히트를 기록합니다**. `max_zoom`에 걸린 사진 =
해상도가 부족한 사진이고, 사용자가 알아야 할 신호입니다.
"""

from __future__ import annotations

from .compose import Composition
from .grade import clamp
from .measure import Stats
from .schemas import MotionParams, MotionRules

__all__ = ["compute_motion"]


def _duration(stats: Stats, rules: MotionRules) -> tuple[float, bool]:
    """지속시간과 클램프 여부."""
    d = rules.duration
    raw = d.base_sec
    if d.complexity_bonus > 0:
        # 디테일이 많은 사진은 눈이 훑을 시간이 더 필요하다. sharpness를 0~1로
        # 눌러서 보너스를 배분한다(400은 measure의 unsharp divisor와 같은 척도).
        raw += d.complexity_bonus * min(stats.sharpness / 400.0, 1.0)
    out = clamp(raw, d.min_sec, d.max_sec)
    return out, abs(out - raw) > 1e-9


def _zoom_direction(rules: MotionRules, index: int, comp: Composition) -> str:
    """줌 방향. 무작위는 절대 쓰지 않습니다 — 구도에서 계산합니다."""
    mode = rules.zoom.direction
    if mode in ("in", "out"):
        return mode
    if mode == "alternate":
        return "in" if index % 2 == 0 else "out"
    # auto: POI가 중앙에서 멀수록 줌인(관심영역으로 파고든다).
    # 중앙에 있으면 전체를 보여주다 좁히는 쪽보다 열어주는 줌아웃이 자연스럽다.
    offset = max(abs(comp.poi_x - 0.5), abs(comp.poi_y - 0.5))
    return "in" if offset >= 0.10 else "out"


def compute_motion(
    photo_id: str,
    index: int,
    stats: Stats,
    comp: Composition,
    rules: MotionRules,
) -> MotionParams:
    """사진 1장의 모션 파라미터."""
    clamped: list[str] = []

    duration_sec, dur_clamped = _duration(stats, rules)
    if dur_clamped:
        clamped.append("duration")

    # --- 줌 -------------------------------------------------------------
    if rules.zoom.enabled:
        requested = 1.0 + rules.zoom.amount
        zoom_target = min(requested, comp.max_zoom)
        if zoom_target < requested - 1e-9:
            # 원본 해상도가 요청한 줌량을 감당하지 못한다.
            clamped.append("max_zoom")
        direction = _zoom_direction(rules, index, comp)
        if direction == "in":
            zoom_start, zoom_end = 1.0, zoom_target
        else:
            zoom_start, zoom_end = zoom_target, 1.0
    else:
        zoom_start = zoom_end = 1.0

    # --- 팬 -------------------------------------------------------------
    dx = dy = 0.0
    if rules.pan.enabled and rules.pan.toward_poi:
        m = rules.pan.max_offset
        raw_dx = (comp.poi_x - 0.5) * 2 * m
        raw_dy = (comp.poi_y - 0.5) * 2 * m
        dx, dy = clamp(raw_dx, -m, m), clamp(raw_dy, -m, m)
        if abs(dx - raw_dx) > 1e-9 or abs(dy - raw_dy) > 1e-9:
            clamped.append("pan")

    # --- 종횡비 ---------------------------------------------------------
    if comp.aspect_dev > rules.aspect.deviation_threshold:
        aspect_mode = rules.aspect.mode
        clamped.append("aspect")
    else:
        aspect_mode = "none"

    return MotionParams(
        id=photo_id,
        index=index,
        duration_sec=round(duration_sec, 4),
        zoom_start=round(zoom_start, 5),
        zoom_end=round(zoom_end, 5),
        dx=round(dx, 5),
        dy=round(dy, 5),
        poi_x=comp.poi_x,
        poi_y=comp.poi_y,
        max_zoom=comp.max_zoom,
        aspect_dev=comp.aspect_dev,
        aspect_mode=aspect_mode,
        ease=rules.zoom.ease,
        clamped=clamped,
    )
