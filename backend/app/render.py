"""렌더 작업: 클립 개별 렌더 → 전환 결합 → 최종 mp4.

동시성은 `asyncio.Semaphore`가 아니라 스레드 풀 + 세마포어로 제한합니다 —
ffmpeg는 subprocess라 CPU 바운드이고, 무제한으로 띄우면 머신이 멈춥니다.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .ffmpeg_grade import build_grade_filters
from .ffmpeg_motion import clip_cache_name, concat_with_transitions, render_clip
from .grade import compute_grade
from .pipeline import evaluate_motion
from .schemas import GradeRules, MotionParams, MotionRules
from .state import AppState

__all__ = ["RenderJob", "start_render", "MAX_PARALLEL"]

MAX_PARALLEL = int(os.environ.get("PVT_RENDER_PARALLEL", "3"))


@dataclass
class RenderJob:
    id: str
    total: int = 0
    done: int = 0
    phase: str = "queued"  # queued | clips | concat | done | error
    message: str = ""
    output: Path | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def payload(self) -> dict:
        pct = (self.done / self.total * 100.0) if self.total else 0.0
        return {
            "job_id": self.id,
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "percent": round(pct, 1),
            "message": self.message,
            "error": self.error,
            "elapsed_sec": round((self.finished_at or time.time()) - self.started_at, 2),
            "ready": self.phase == "done",
        }


def _clip_source(state: AppState, photo_id: str, single_pass: bool) -> tuple[Path, str]:
    """(소스 경로, 캐시용 해시). single_pass면 원본, 아니면 graded 중간본."""
    p = state.photos[photo_id]
    if single_pass or p.graded_path is None or not p.graded_path.is_file():
        return p.path, p.id
    return p.graded_path, f"{p.id}g"


def _render_all_clips(
    state: AppState,
    clips: list[MotionParams],
    motion_rules: MotionRules,
    grade_rules: GradeRules | None,
    single_pass: bool,
    height: int | None,
    job: RenderJob,
) -> list[Path]:
    out = motion_rules.output
    results: list[Path | None] = [None] * len(clips)
    lock = threading.Lock()

    def one(i: int, p: MotionParams) -> None:
        src, hash_key = _clip_source(state, p.id, single_pass)
        grade_filters = None
        if single_pass and grade_rules is not None:
            photo = state.photos[p.id]
            g = compute_grade(photo.stats, photo.exif, grade_rules, has_face=bool(photo.faces))
            grade_filters = build_grade_filters(g)
            hash_key = f"{hash_key}+{abs(hash(tuple(grade_filters))):x}"

        name = clip_cache_name(hash_key, p, out, motion_rules, height)
        dst = state.work.clips / name
        if not dst.is_file():  # 해시 캐시: 바뀐 클립만 다시 렌더된다
            render_clip(src, dst, p, out, motion_rules, height, grade_filters)
        results[i] = dst
        with lock:
            job.done += 1
            job.message = state.photos[p.id].filename

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        list(pool.map(lambda a: one(*a), list(enumerate(clips))))

    missing = [i for i, r in enumerate(results) if r is None]
    if missing:
        raise RuntimeError(f"클립 렌더 실패: index {missing}")
    return [r for r in results if r is not None]


def run_render(
    state: AppState,
    job: RenderJob,
    motion_rules: MotionRules,
    grade_rules: GradeRules | None,
    order: list[str] | None,
    single_pass: bool,
) -> None:
    try:
        evald = evaluate_motion(state, motion_rules, order)
        job.total = len(evald.clips) + max(len(evald.transitions), 1)
        job.phase = "clips"

        clips = _render_all_clips(
            state, evald.clips, motion_rules, grade_rules, single_pass, None, job
        )

        job.phase = "concat"
        job.message = "전환 적용 중"

        def on_step(i: int, total: int) -> None:
            job.done = len(evald.clips) + i
            job.message = f"전환 {i}/{total}"

        dst = state.work.out / f"final_{job.id[:8]}.mp4"
        concat_with_transitions(
            clips, evald.clips, evald.transitions, motion_rules.output, dst, progress=on_step
        )
        job.output = dst
        job.done = job.total
        job.phase = "done"
        job.message = f"완료: {dst.name}"
    except Exception as exc:  # noqa: BLE001 - 작업 실패를 job 상태로 노출해야 한다
        job.phase = "error"
        job.error = str(exc)
    finally:
        job.finished_at = time.time()


def start_render(
    state: AppState,
    motion_rules: MotionRules,
    grade_rules: GradeRules | None = None,
    order: list[str] | None = None,
    single_pass: bool = False,
) -> RenderJob:
    job = RenderJob(id=uuid.uuid4().hex)
    state.jobs[job.id] = job
    threading.Thread(
        target=run_render,
        args=(state, job, motion_rules, grade_rules, order, single_pass),
        daemon=True,
    ).start()
    return job
