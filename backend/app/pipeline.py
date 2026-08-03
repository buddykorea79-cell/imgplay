"""1·2단계 계산 파이프라인. API와 CLI가 공유합니다.

`evaluate_*`는 순수 계산입니다 — 이미지를 다시 읽지 않습니다. 슬라이더를 만질
때 200장이 수십 ms 안에 다시 계산되는 이유가 이것입니다(섹션 11).
"""

from __future__ import annotations

import os
import shutil
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .cache import sha256_file
from .compose import analyze_composition
from .exif import read_exif
from .faces import detect_faces
from .ffmpeg_grade import render_graded
from .grade import compute_grade
from .imageio import imread
from .measure import Stats, measure
from .motion import compute_motion
from .schemas import (
    FaceBox,
    GradeEvaluateResponse,
    GradeParams,
    GradeRules,
    MotionEvaluateResponse,
    MotionRules,
)
from .state import AppState, Photo
from .timeline import decide_transitions, total_duration

__all__ = [
    "ingest_file",
    "ingest_many",
    "evaluate_grade",
    "commit_grade",
    "evaluate_motion",
    "ensure_compositions",
    "IMAGE_SUFFIXES",
]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif"}


# ------------------------------------------------------------------ 1단계


def ingest_many(
    state: AppState,
    sources: list[tuple[Path, str]],
    workers: int | None = None,
    progress=None,
) -> tuple[list[Photo], list[tuple[str, str]]]:
    """여러 장을 병렬로 들인다. `(성공 목록, [(파일명, 오류)])`.

    측정은 CPU 바운드이지만 OpenCV/numpy가 GIL을 놓기 때문에 스레드로 충분히
    병렬화됩니다. 한 장이 실패해도 나머지는 계속 진행합니다.
    """
    if workers is None:
        workers = max(1, min(len(sources), (os.cpu_count() or 2)))

    photos: list[Photo] = []
    errors: list[tuple[str, str]] = []
    lock = threading.Lock()

    def one(item: tuple[Path, str]) -> None:
        src, name = item
        try:
            photo = ingest_file(state, src, name, defer_save=True)
        except Exception as exc:  # noqa: BLE001 - 한 장 실패로 전체를 막지 않는다
            with lock:
                errors.append((name, str(exc)))
            return
        with lock:
            photos.append(photo)
            if progress:
                progress(len(photos) + len(errors), len(sources), name)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, sources))

    with state.lock:
        state.save()  # 장마다 쓰지 않고 마지막에 한 번만 기록한다
    return photos, errors


def ingest_file(
    state: AppState,
    src: Path,
    original_name: str | None = None,
    defer_save: bool = False,
) -> Photo:
    """파일 1장을 업로드 폴더로 들이고 측정한다. 해시가 같으면 캐시를 씁니다.

    **원본 파일은 절대 수정하지 않습니다**(섹션 12-9). 업로드 폴더로 복사만 합니다.
    """
    name = original_name or src.name
    photo_id = sha256_file(src)

    with state.lock:
        existing = state.photos.get(photo_id)
        if existing is not None and existing.path.is_file():
            return existing

    dest = state.work.uploads / f"{photo_id}{src.suffix.lower()}"
    if not dest.is_file():
        shutil.copy2(src, dest)

    cached = state.measure_cache.get(photo_id)
    if cached is not None:
        stats = Stats(**cached["stats"])
        faces = [FaceBox(**f) for f in cached["faces"]]
    else:
        img = imread(dest)  # EXIF 회전이 이미 적용되어 있다
        stats = measure(img)
        faces = detect_faces(img)
        state.measure_cache.set(
            photo_id,
            {"stats": stats.to_dict(), "faces": [f.model_dump() for f in faces]},
        )

    photo = Photo(
        id=photo_id,
        filename=name,
        path=dest,
        stats=stats,
        exif=read_exif(dest),
        faces=faces,
    )
    with state.lock:
        state.photos[photo_id] = photo
        # `state.order`는 **사용자가 명시적으로 정한 순서**만 담습니다. 인제스트가
        # 여기에 손대면 병렬 처리 완료 순서가 그대로 타임라인이 되어버립니다.
        # 비워두면 `ordered_photos`가 EXIF 촬영시각으로 정렬합니다.
        if not defer_save:
            state.save()
    return photo


def evaluate_grade(
    state: AppState, rules: GradeRules, ids: list[str] | None = None
) -> GradeEvaluateResponse:
    """규칙 → 사진별 보정 파라미터 + 클램프 히트. 재측정 없음."""
    photos = [state.photos[i] for i in ids if i in state.photos] if ids else list(
        state.photos.values()
    )
    params: list[GradeParams] = []
    counts: Counter[str] = Counter()
    hit_photos = 0

    for p in photos:
        r = compute_grade(p.stats, p.exif, rules, has_face=bool(p.faces))
        counts.update(r.clamped)
        if r.clamped:
            hit_photos += 1
        params.append(
            GradeParams(
                id=p.id,
                gamma=round(r.gamma, 4),
                contrast=round(r.contrast, 4),
                saturation=round(r.saturation, 4),
                unsharp=round(r.unsharp, 4),
                wb={k: round(v, 4) for k, v in r.wb.items()},
                wb_enabled=r.wb_enabled,
                clamped=r.clamped,
                guards_applied=r.guards_applied,
            )
        )

    rate = hit_photos / len(photos) if photos else 0.0
    return GradeEvaluateResponse(
        params=params, clamp_rate=round(rate, 4), clamp_counts=dict(counts)
    )


def commit_grade(state: AppState, rules: GradeRules, progress=None) -> int:
    """확정: 원본 해상도 보정본을 `work/graded/`에 PNG로 굽는다.

    PNG인 이유는 2단계가 재인코딩 손실 없이 받기 위해서입니다(섹션 12-7).
    """
    photos = list(state.photos.values())
    for i, p in enumerate(photos):
        r = compute_grade(p.stats, p.exif, rules, has_face=bool(p.faces))
        dst = state.work.graded / f"{p.id}.png"
        render_graded(p.path, dst, r)
        p.graded_path = dst
        if progress:
            progress(i + 1, len(photos), p.filename)
    with state.lock:
        state.committed = bool(photos)
        state.save()
    return len(photos)


# ------------------------------------------------------------------ 2단계


def ensure_compositions(state: AppState, rules: MotionRules) -> None:
    """구도 분석을 채운다. 출력 규격이 바뀌면 안전 줌이 달라지므로 다시 계산합니다."""
    out = rules.output
    # POI는 출력 규격과 무관하지만 max_zoom/aspect_dev는 그렇지 않습니다. 규격이
    # 바뀌면 전부 다시 계산합니다(POI 재계산 비용은 축소본이라 무시할 수준).
    sig = (out.width, out.height, rules.zoom.safety, rules.zoom.hard_max)
    if state.composition_sig != sig:
        for p in state.photos.values():
            p.composition = None
        state.composition_sig = sig

    for p in state.photos.values():
        if p.composition is not None:
            continue
        img = None
        if not p.faces:
            # 얼굴이 없을 때만 이미지를 읽는다(엣지 무게중심용). 축소본으로 충분.
            source = p.graded_path if p.graded_path and p.graded_path.is_file() else p.path
            img = imread(source)
        p.composition = analyze_composition(
            img,
            p.stats.width,
            p.stats.height,
            p.faces,
            out.width,
            out.height,
            rules.zoom.safety,
            rules.zoom.hard_max,
        )


def evaluate_motion(
    state: AppState, rules: MotionRules, order: list[str] | None = None
) -> MotionEvaluateResponse:
    """규칙 → 클립별 모션 파라미터 + 전환 + 총 길이."""
    ensure_compositions(state, rules)
    photos = state.ordered_photos(order)

    clips = [
        compute_motion(p.id, i, p.stats, p.composition, rules)
        for i, p in enumerate(photos)
    ]
    transitions = decide_transitions(
        [p.id for p in photos],
        {p.id: p.stats.hist_L for p in photos},
        {p.id: p.captured_at for p in photos},
        rules,
    )
    total, clip_sum, saving = total_duration(clips, transitions)

    counts: Counter[str] = Counter()
    hit = 0
    for c in clips:
        counts.update(c.clamped)
        if c.clamped:
            hit += 1

    return MotionEvaluateResponse(
        clips=clips,
        transitions=transitions,
        total_duration_sec=total,
        sum_duration_sec=clip_sum,
        transition_saving_sec=saving,
        clamp_counts=dict(counts),
        clamp_rate=round(hit / len(clips), 4) if clips else 0.0,
    )
