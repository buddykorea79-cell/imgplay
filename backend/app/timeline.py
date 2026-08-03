"""순서·지속시간·전환 오프셋 계산.

전환이 들어가면 총 길이가 `sum(durations) - (n-1) * transition_duration`으로
줄어듭니다. 나레이션 길이를 맞출 거라면 이 값이 UI에 보여야 합니다(섹션 10.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .measure import hist_distance
from .schemas import MotionParams, MotionRules, TransitionSpec

__all__ = ["sort_by_capture_time", "decide_transitions", "total_duration", "TimelineEntry"]


@dataclass(slots=True)
class TimelineEntry:
    id: str
    filename: str
    captured_at: datetime | None


def sort_by_capture_time(entries: list[TimelineEntry]) -> list[str]:
    """EXIF 촬영시각 기준 정렬. 시각이 없는 사진은 파일명 순으로 뒤에 붙입니다.

    시각 없는 사진을 1970년으로 취급해 맨 앞에 몰아넣으면 타임라인이 엉망이 되므로
    분리해서 뒤에 붙입니다.
    """
    dated = [e for e in entries if e.captured_at is not None]
    undated = [e for e in entries if e.captured_at is None]
    dated.sort(key=lambda e: (e.captured_at, e.filename))
    undated.sort(key=lambda e: e.filename)
    return [e.id for e in dated + undated]


def _gap_minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return abs((b - a).total_seconds()) / 60.0


def decide_transitions(
    order: list[str],
    hists: dict[str, list[float]],
    captured: dict[str, datetime | None],
    rules: MotionRules,
) -> list[TransitionSpec]:
    """인접 사진 통계 차이로 전환 방식을 결정한다."""
    t = rules.transition
    specs: list[TransitionSpec] = []

    for i in range(len(order) - 1):
        a, b = order[i], order[i + 1]
        dist = hist_distance(hists.get(a, []), hists.get(b, []))
        gap = _gap_minutes(captured.get(a), captured.get(b))

        if gap is not None and gap >= t.on_scene_gap_min:
            kind = t.on_different
            reason = f"촬영 간격 {gap:.0f}분 ≥ {t.on_scene_gap_min:.0f}분"
        elif dist > t.different_threshold:
            kind = t.on_different
            reason = f"히스토그램 거리 {dist:.2f} > {t.different_threshold:.2f}"
        elif dist < t.similar_threshold:
            kind = t.on_similar
            reason = f"히스토그램 거리 {dist:.2f} < {t.similar_threshold:.2f}"
        else:
            kind, reason = t.default, f"히스토그램 거리 {dist:.2f} (중간)"

        specs.append(
            TransitionSpec(
                index=i,
                type=kind,
                duration_sec=0.0 if kind == "none" else t.duration_sec,
                hist_distance=round(dist, 4),
                gap_minutes=round(gap, 2) if gap is not None else None,
                reason=reason,
            )
        )
    return specs


def total_duration(
    clips: list[MotionParams], transitions: list[TransitionSpec]
) -> tuple[float, float, float]:
    """(총 길이, 클립 길이 합, 전환으로 줄어든 시간).

    xfade는 앞뒤 클립을 겹쳐 재생하므로 겹친 만큼 전체가 짧아집니다. `none`
    전환은 컷이라 겹침이 없습니다.
    """
    total_clips = sum(c.duration_sec for c in clips)
    saving = sum(t.duration_sec for t in transitions)
    return round(total_clips - saving, 3), round(total_clips, 3), round(saving, 3)


def xfade_offsets(
    clips: list[MotionParams], transitions: list[TransitionSpec]
) -> list[float]:
    """i번째 전환의 xfade offset (누적 결합 기준).

    두 클립씩 순차 결합하며 누적할 때, offset은 **지금까지 만들어진 결과물의 길이
    - 전환 길이**입니다. 클립 길이가 아니라 누적 길이인 게 핵심입니다.
    """
    offsets: list[float] = []
    acc = clips[0].duration_sec if clips else 0.0
    for i, t in enumerate(transitions):
        offsets.append(round(max(acc - t.duration_sec, 0.0), 4))
        acc = acc - t.duration_sec + clips[i + 1].duration_sec
    return offsets
