"""FastAPI 앱 (섹션 11).

2단계 엔드포인트는 1단계 확정 전에 호출되면 409를 돌려줍니다. 화질과 모션은
판단 기준이 다르고, 섞어서 보면 둘 다 제대로 못 봅니다.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .cache import params_key
from .export import build_export_zip, generate_build_script
from .faces import face_model_available
from .ffmpeg_grade import render_preview_jpeg
from .ffmpeg_motion import clip_cache_name, render_clip, render_transition_preview
from .grade import compute_grade
from .pipeline import IMAGE_SUFFIXES, evaluate_grade, evaluate_motion, ingest_many
from .render import start_render
from .schemas import (
    CommitRequest,
    GradeEvaluateRequest,
    GradeEvaluateResponse,
    MotionEvaluateRequest,
    MotionEvaluateResponse,
    OrderRequest,
    RenderRequest,
    StageStatus,
)
from .state import REPO_ROOT, get_state
from .timeline import TimelineEntry, sort_by_capture_time

app = FastAPI(title="photo-video-tuner", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # 로컬 실행 전제입니다. 인증도 멀티테넌시도 없으므로 개발 서버만 열어둡니다.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _require_committed() -> None:
    if not get_state().committed:
        raise HTTPException(
            status_code=409,
            detail="1단계 그레이딩이 확정되지 않았습니다. /api/grade/commit 을 먼저 호출하세요.",
        )


def _photo_or_404(photo_id: str):
    p = get_state().photos.get(photo_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"알 수 없는 사진 id: {photo_id}")
    return p


# ------------------------------------------------------------------ 공통


@app.get("/api/health")
def health() -> dict:
    from .ffmpeg_motion import ffmpeg_version

    st = get_state()
    try:
        ff = ffmpeg_version()
    except Exception as exc:  # noqa: BLE001
        ff = f"사용 불가: {exc}"
    return {
        "ok": True,
        "ffmpeg": ff,
        "face_model": face_model_available(),
        "photos": len(st.photos),
        "committed": st.committed,
    }


@app.get("/api/rules/{kind}")
def get_rules(kind: str) -> dict:
    if kind not in ("grade", "motion"):
        raise HTTPException(400, "kind는 grade 또는 motion이어야 합니다")
    st = get_state()
    rules = st.load_grade_rules() if kind == "grade" else st.load_motion_rules()
    return rules.model_dump()


@app.put("/api/rules/{kind}")
def put_rules(kind: str, body: dict) -> dict:
    if kind not in ("grade", "motion"):
        raise HTTPException(400, "kind는 grade 또는 motion이어야 합니다")
    st = get_state()
    from .schemas import GradeRules, MotionRules

    model = GradeRules if kind == "grade" else MotionRules
    try:
        parsed = model(**body)  # 스키마 검증: 오타난 키를 파일에 쓰지 않는다
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"규칙 검증 실패: {exc}") from exc
    st.write_rules(kind, parsed.model_dump())
    return parsed.model_dump()


# ------------------------------------------------------------------ 1단계


@app.post("/api/photos")
async def upload_photos(files: list[UploadFile]) -> list[dict]:
    st = get_state()
    errors: list[dict] = []
    staged: list[tuple[Path, str]] = []

    # 업로드는 순차로 받아 임시 파일에 쓰고(네트워크 바운드), 측정은 병렬로
    # 돌립니다(CPU 바운드). 섞으면 둘 다 느려집니다.
    for uf in files:
        name = Path(uf.filename or "unnamed").name
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
            errors.append({"filename": name, "error": "지원하지 않는 확장자"})
            continue
        with tempfile.NamedTemporaryFile(suffix=Path(name).suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            size = 0
            while chunk := await uf.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    break
                tmp.write(chunk)
        if size > MAX_UPLOAD_BYTES:
            tmp_path.unlink(missing_ok=True)
            errors.append({"filename": name, "error": "파일이 너무 큽니다"})
            continue
        staged.append((tmp_path, name))

    try:
        photos, failures = await asyncio.to_thread(ingest_many, st, staged)
    finally:
        for tmp_path, _ in staged:
            tmp_path.unlink(missing_ok=True)

    errors += [{"filename": n, "error": e} for n, e in failures]
    results = [p.to_payload() for p in photos]

    if errors and not results:
        raise HTTPException(422, {"errors": errors})
    return results + ([{"_errors": errors}] if errors else [])


@app.get("/api/photos")
def list_photos() -> list[dict]:
    return [p.to_payload() for p in get_state().ordered_photos()]


@app.delete("/api/photos")
def reset_photos() -> dict:
    get_state().reset()
    return {"ok": True}


@app.post("/api/grade/evaluate", response_model=GradeEvaluateResponse)
def grade_evaluate(body: GradeEvaluateRequest) -> GradeEvaluateResponse:
    """순수 계산 — 재측정이 없어 200장도 수십 ms입니다."""
    return evaluate_grade(get_state(), body.rules, body.ids)


@app.get("/api/grade/preview/{photo_id}")
async def grade_preview(
    photo_id: str,
    mode: str = Query("fit", pattern="^(fit|crop)$"),
    long_edge: int = Query(1280, ge=120, le=4096),
    crop_size: int = Query(900, ge=100, le=4096),
) -> Response:
    """보정본 미리보기. 규칙은 디스크의 grade.yaml을 씁니다."""
    st = get_state()
    p = _photo_or_404(photo_id)
    rules = st.load_grade_rules()
    g = compute_grade(p.stats, p.exif, rules, has_face=bool(p.faces))
    data = await asyncio.to_thread(
        render_preview_jpeg, p.path, g, mode, long_edge, crop_size
    )
    return Response(content=data, media_type="image/jpeg")


@app.post("/api/grade/preview/{photo_id}")
async def grade_preview_with_rules(
    photo_id: str,
    body: GradeEvaluateRequest,
    mode: str = Query("fit", pattern="^(fit|crop)$"),
    long_edge: int = Query(1280, ge=120, le=4096),
    crop_size: int = Query(900, ge=100, le=4096),
) -> Response:
    """슬라이더로 조정 중인 규칙을 그대로 적용한 미리보기."""
    p = _photo_or_404(photo_id)
    g = compute_grade(p.stats, p.exif, body.rules, has_face=bool(p.faces))
    data = await asyncio.to_thread(
        render_preview_jpeg, p.path, g, mode, long_edge, crop_size
    )
    return Response(content=data, media_type="image/jpeg")


@app.get("/api/grade/original/{photo_id}")
async def grade_original(
    photo_id: str,
    mode: str = Query("fit", pattern="^(fit|crop)$"),
    long_edge: int = Query(1280, ge=120, le=4096),
    crop_size: int = Query(900, ge=100, le=4096),
) -> Response:
    """원본을 **동일한 스케일로** 렌더. 비교 뷰의 좌측입니다."""
    p = _photo_or_404(photo_id)
    data = await asyncio.to_thread(
        render_preview_jpeg, p.path, None, mode, long_edge, crop_size
    )
    return Response(content=data, media_type="image/jpeg")


@app.post("/api/grade/commit")
async def grade_commit(body: CommitRequest) -> StreamingResponse:
    """확정: 원본 해상도 보정본을 PNG로 굽고 2단계를 엽니다. 진행률 SSE."""
    st = get_state()
    if not st.photos:
        raise HTTPException(400, "업로드된 사진이 없습니다")

    from .ffmpeg_grade import render_graded

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    photos = list(st.photos.values())

    def work() -> None:
        try:
            for i, p in enumerate(photos):
                g = compute_grade(p.stats, p.exif, body.rules, has_face=bool(p.faces))
                dst = st.work.graded / f"{p.id}.png"
                render_graded(p.path, dst, g)
                p.graded_path = dst
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"done": i + 1, "total": len(photos), "filename": p.filename},
                )
            with st.lock:
                st.committed = True
                st.composition_sig = None  # graded 이미지가 새로 생겼으니 구도 재계산
                st.save()
            loop.call_soon_threadsafe(
                queue.put_nowait, {"done": len(photos), "total": len(photos), "ready": True}
            )
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, {"error": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.get_running_loop().run_in_executor(None, work)

    async def stream() -> AsyncIterator[str]:
        while (item := await queue.get()) is not None:
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/grade/uncommit")
def grade_uncommit() -> dict:
    """1단계로 되돌아가기. graded/와 clips/를 정리하고 2단계를 잠급니다."""
    st = get_state()
    st.invalidate_stage2()
    return {"ok": True, "committed": False}


@app.get("/api/grade/status", response_model=StageStatus)
def grade_status() -> StageStatus:
    st = get_state()
    committed_count = sum(
        1 for p in st.photos.values() if p.graded_path and p.graded_path.is_file()
    )
    return StageStatus(
        uploaded=len(st.photos),
        committed=st.committed,
        committed_count=committed_count,
        stage2_unlocked=st.committed and committed_count > 0,
        graded_dir=str(st.work.graded),
    )


# ------------------------------------------------------------------ 2단계


@app.get("/api/timeline")
def get_timeline() -> dict:
    _require_committed()
    st = get_state()
    rules = st.load_motion_rules()
    evald = evaluate_motion(st, rules)
    photos = {p.id: p for p in st.ordered_photos()}

    def item(c) -> dict:
        p = photos[c.id]
        return {
            **c.model_dump(),
            "filename": p.filename,
            "captured_at": p.captured_at.isoformat() if p.captured_at else None,
            "poi_source": p.composition.poi_source if p.composition else "",
        }

    return {
        "order": [c.id for c in evald.clips],
        "items": [item(c) for c in evald.clips],
        "transitions": [t.model_dump() for t in evald.transitions],
        "total_duration_sec": evald.total_duration_sec,
        "sum_duration_sec": evald.sum_duration_sec,
        "transition_saving_sec": evald.transition_saving_sec,
        "clamp_counts": evald.clamp_counts,
        "clamp_rate": evald.clamp_rate,
    }


@app.put("/api/timeline/order")
def put_order(body: OrderRequest) -> dict:
    _require_committed()
    st = get_state()
    unknown = [i for i in body.order if i not in st.photos]
    if unknown:
        raise HTTPException(400, f"알 수 없는 id: {unknown}")
    missing = [i for i in st.photos if i not in body.order]
    with st.lock:
        st.order = list(body.order) + missing  # 빠진 사진은 뒤에 붙여 유실을 막는다
        st.save()
    return {"order": st.order}


@app.post("/api/timeline/sort")
def sort_timeline() -> dict:
    """EXIF 촬영시각 순으로 되돌립니다."""
    _require_committed()
    st = get_state()
    entries = [TimelineEntry(p.id, p.filename, p.captured_at) for p in st.photos.values()]
    with st.lock:
        st.order = sort_by_capture_time(entries)
        st.save()
    return {"order": st.order}


@app.post("/api/motion/evaluate", response_model=MotionEvaluateResponse)
def motion_evaluate(body: MotionEvaluateRequest) -> MotionEvaluateResponse:
    _require_committed()
    return evaluate_motion(get_state(), body.rules, body.order)


@app.post("/api/motion/clip/{photo_id}")
async def motion_clip_preview(photo_id: str, body: MotionEvaluateRequest) -> FileResponse:
    """단일 클립 미리보기 (preview_height). 목표는 1초 이내."""
    _require_committed()
    st = get_state()
    p = _photo_or_404(photo_id)
    rules = body.rules
    evald = evaluate_motion(st, rules, body.order)
    mp = next((c for c in evald.clips if c.id == photo_id), None)
    if mp is None:
        raise HTTPException(404, "타임라인에 없는 사진입니다")

    src = p.graded_path if p.graded_path and p.graded_path.is_file() else p.path
    height = rules.output.preview_height
    dst = st.work.clips / clip_cache_name(f"{p.id}p", mp, rules.output, rules, height)
    if not dst.is_file():
        await asyncio.to_thread(
            render_clip, src, dst, mp, rules.output, rules, height, None, True
        )
    return FileResponse(dst, media_type="video/mp4", filename=dst.name)


@app.post("/api/motion/transition/{index}")
async def motion_transition_preview(index: int, body: MotionEvaluateRequest) -> FileResponse:
    """전환 1개 미리보기: 앞뒤 클립에서 각 2초분만 잘라 xfade."""
    _require_committed()
    st = get_state()
    rules = body.rules
    evald = evaluate_motion(st, rules, body.order)
    if not 0 <= index < len(evald.transitions):
        raise HTTPException(404, f"전환 인덱스 범위를 벗어났습니다: {index}")

    spec = evald.transitions[index]
    height = rules.output.preview_height
    clips: list[Path] = []
    for mp in (evald.clips[index], evald.clips[index + 1]):
        p = st.photos[mp.id]
        src = p.graded_path if p.graded_path and p.graded_path.is_file() else p.path
        cdst = st.work.clips / clip_cache_name(f"{p.id}p", mp, rules.output, rules, height)
        if not cdst.is_file():
            await asyncio.to_thread(
                render_clip, src, cdst, mp, rules.output, rules, height, None, True
            )
        clips.append(cdst)

    key = params_key(spec.model_dump(), [c.name for c in clips])
    dst = st.work.clips / f"trans_{index:04d}_{key}.mp4"
    if not dst.is_file():
        await asyncio.to_thread(
            render_transition_preview, clips[0], clips[1], spec, rules.output, dst
        )
    return FileResponse(dst, media_type="video/mp4", filename=dst.name)


@app.post("/api/render")
def post_render(body: RenderRequest, _bg: BackgroundTasks) -> dict:
    _require_committed()
    st = get_state()
    job = start_render(st, body.motion_rules, body.grade_rules, body.order, body.single_pass)
    return {"job_id": job.id}


@app.get("/api/render/{job_id}")
async def render_progress(job_id: str) -> StreamingResponse:
    st = get_state()
    if job_id not in st.jobs:
        raise HTTPException(404, "알 수 없는 job_id")

    async def stream() -> AsyncIterator[str]:
        while True:
            job = st.jobs[job_id]
            yield f"data: {json.dumps(job.payload(), ensure_ascii=False)}\n\n"
            if job.phase in ("done", "error"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/render/{job_id}/status")
def render_status(job_id: str) -> dict:
    st = get_state()
    if job_id not in st.jobs:
        raise HTTPException(404, "알 수 없는 job_id")
    return st.jobs[job_id].payload()


@app.get("/api/render/{job_id}/file")
def render_file(job_id: str) -> FileResponse:
    st = get_state()
    job = st.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "알 수 없는 job_id")
    if job.phase != "done" or job.output is None:
        raise HTTPException(409, f"아직 준비되지 않았습니다 (phase={job.phase})")
    return FileResponse(job.output, media_type="video/mp4", filename="final.mp4")


# ------------------------------------------------------------------ 내보내기


@app.get("/api/export")
def export_zip() -> Response:
    st = get_state()
    data = build_export_zip(st, st.load_grade_rules(), st.load_motion_rules())
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="photo-video-tuner-export.zip"'},
    )


@app.get("/api/export/build.sh")
def export_script() -> Response:
    st = get_state()
    script = generate_build_script(st, st.load_grade_rules(), st.load_motion_rules())
    return Response(content=script, media_type="text/x-shellscript")


@app.exception_handler(ValueError)
def value_error_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# 프로덕션 빌드가 있으면 FastAPI가 정적 서빙해 단일 프로세스로 합칩니다.
# 패키지가 site-packages에 설치되면 REPO_ROOT 추론이 빗나가므로, 컨테이너처럼
# 위치가 확실한 환경에서는 PVT_STATIC_DIR로 못 박습니다.
_DIST = Path(os.environ.get("PVT_STATIC_DIR", REPO_ROOT / "frontend" / "dist"))
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
else:
    @app.get("/")
    def _root() -> dict:
        return {
            "message": "프론트엔드 개발 서버는 http://localhost:5173 입니다.",
            "docs": "/docs",
        }
