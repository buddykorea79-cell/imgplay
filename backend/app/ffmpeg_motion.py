"""클립 렌더, 전환, 이어붙이기 (섹션 10).

함정이 모여 있는 곳입니다. 지켜야 할 것:

* 사진 200장을 하나의 `filter_complex`로 묶지 않습니다 — ffmpeg가 감당하지
  못하고, 한 장만 고쳐도 전체를 다시 렌더해야 합니다.
* `zoompan`의 `d`는 **프레임 수**입니다. 초가 아닙니다.
* `zoompan`에 `fps`를 명시하지 않으면 25로 잡혀 출력 fps와 어긋납니다.
* 확대 전에 업스케일하지 않으면 계단식 떨림(jitter)이 생깁니다 — zoompan이
  `x`/`y`를 정수로 자르기 때문입니다. 4배로 키운 뒤 `s=`로 내보내면 잘림 단위가
  1/4로 줄어 매끄러워집니다.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .cache import params_key
from .ffmpeg_util import ffmpeg_path, run_ffmpeg
from .schemas import MotionParams, MotionRules, OutputSpec, TransitionSpec
from .timeline import xfade_offsets

__all__ = [
    "build_clip_filter",
    "render_clip",
    "clip_cache_name",
    "concat_with_transitions",
    "render_transition_preview",
    "UPSCALE_FACTOR",
]

UPSCALE_FACTOR = 4  # 섹션 10.2(c). 이 값을 1로 두면 줌이 떨립니다.
_VIDEO_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
# 미리보기 전용 인코더 설정. **필터 체인은 최종 렌더와 완전히 동일합니다** —
# 바뀌는 것은 압축 품질뿐이라 눈으로 판단하는 모션은 그대로입니다.
_PREVIEW_VIDEO_ARGS = [
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
]


def _aspect_prelude(mode: str, w: int, h: int, sigma: float) -> str:
    """종횡비 불일치 처리 (섹션 10.3).

    **zoompan보다 먼저** 겁니다. 순서가 반대면 배경 블러까지 같이 줌돼서
    어지러워집니다.
    """
    if mode == "blur_fill":
        return (
            f"split[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma={sigma:g}[bg];"
            f"[fg]scale=-2:{h}:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:0"
        )
    if mode == "crop":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h}"
        )
    # pad (레터박스)
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    )


def _zoom_expr(p: MotionParams, frames: int) -> str:
    """zoompan의 `z` 식.

    선형은 프레임당 고정 증분을 누적합니다. ease_in_out은 누적 대신 `on`(현재
    프레임 인덱스)으로 직접 곡선을 계산합니다 — smoothstep 3t²-2t³.
    """
    start, end = p.zoom_start, p.zoom_end
    if abs(end - start) < 1e-6:
        return f"{start:.4f}"

    if p.ease == "ease_in_out":
        t = f"(on/{max(frames - 1, 1)})"
        smooth = f"({t}*{t}*(3-2*{t}))"
        return f"{start:.4f}+({end - start:.6f})*{smooth}"

    step = (end - start) / max(frames - 1, 1)
    if end > start:
        return f"min(zoom+{step:.8f},{end:.4f})"
    # 줌아웃: 시작 줌을 zoom_start로 두고 감소시킨다. zoompan의 zoom 변수는
    # 첫 프레임에 1.0에서 출발하므로 max()의 하한이 아니라 상한 쪽을 잡아준다.
    return f"max({start:.4f}{step:.8f}*on,{end:.4f})"


def build_clip_filter(
    p: MotionParams, out: OutputSpec, rules: MotionRules, height: int | None = None
) -> str:
    """단일 클립의 필터 체인 전체.

    `height`를 주면 미리보기 해상도로 렌더합니다(종횡비는 출력 규격을 따름).
    """
    out_h = height or out.height
    out_w = int(round(out_h * out.width / out.height))
    out_w += out_w % 2  # H.264는 짝수 치수를 요구한다

    fps = out.fps
    frames = max(round(p.duration_sec * fps), 1)  # (a) d는 초가 아니라 프레임 수

    sw, sh = out_w * UPSCALE_FACTOR, out_h * UPSCALE_FACTOR

    parts: list[str] = []
    if p.aspect_mode != "none":
        parts.append(_aspect_prelude(p.aspect_mode, sw, sh, rules.aspect.blur_sigma))
    else:
        parts.append(
            f"scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2"
        )

    zexpr = _zoom_expr(p, frames)
    # 팬: 중앙 기준 크롭 위치에 POI 방향 오프셋을 프레임 진행에 비례해 더한다.
    x_expr = f"iw/2-(iw/zoom/2)+{p.dx:.5f}*iw*on/{frames}"
    y_expr = f"ih/2-(ih/zoom/2)+{p.dy:.5f}*ih*on/{frames}"

    parts.append(
        f"zoompan=z='{zexpr}':d={frames}"
        f":x='{x_expr}':y='{y_expr}'"
        f":s={out_w}x{out_h}:fps={fps}"  # (b) fps 명시 — 생략하면 25로 잡힌다
    )
    # xfade는 두 입력의 해상도·픽셀포맷·fps가 완전히 같아야 하므로 여기서 통일한다.
    parts.append("format=yuv420p")
    parts.append(f"fps={fps}")

    chain = ",".join(parts)
    # blur_fill 프렐류드는 filter_complex 문법(라벨)을 쓰므로 그대로 이어붙인다.
    return chain


def clip_cache_name(
    image_hash: str,
    p: MotionParams,
    out: OutputSpec,
    rules: MotionRules,
    height: int | None,
) -> str:
    """클립 캐시 키 = 이미지 해시 + 모션 파라미터 + 출력 규격.

    모션 슬라이더를 만져도 실제로 바뀐 클립만 다시 렌더됩니다.
    """
    key = params_key(
        image_hash,
        p.model_dump(exclude={"index"}),
        out.model_dump(),
        rules.aspect.model_dump(),
        height,
        UPSCALE_FACTOR,
    )
    return f"{image_hash[:12]}_{key}.mp4"


def render_clip(
    src: Path,
    dst: Path,
    p: MotionParams,
    out: OutputSpec,
    rules: MotionRules,
    height: int | None = None,
    grade_filters: list[str] | None = None,
    preview: bool = False,
) -> Path:
    """사진 1장 → 클립 mp4.

    `grade_filters`를 주면 중간본 없이 원본에서 단일 패스로 렌더합니다
    (디스크 절약용, 결과는 동일).

    `preview=True`는 인코더만 빠른 설정으로 바꿉니다. 필터 체인은 그대로라
    미리보기에서 본 모션이 최종 렌더에서 그대로 재현됩니다.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    chain = build_clip_filter(p, out, rules, height)
    if grade_filters:
        chain = ",".join(grade_filters) + "," + chain

    frames = max(round(p.duration_sec * out.fps), 1)
    args = [
        "-loop", "1",
        "-i", str(src),
        "-filter_complex", chain,
        "-frames:v", str(frames),
        "-r", str(out.fps),
        *(_PREVIEW_VIDEO_ARGS if preview else _VIDEO_ARGS),
        "-an",
        str(dst),
    ]
    run_ffmpeg(args)
    return dst


def _concat_demuxer(clips: list[Path], dst: Path) -> Path:
    """전환 없는 구간은 concat demuxer가 훨씬 빠릅니다 (재인코딩 없음)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for c in clips:
            # 경로에 작은따옴표가 있으면 concat 문법이 깨진다.
            escaped = str(c.resolve()).replace("'", r"'\''")
            fh.write(f"file '{escaped}'\n")
        listfile = Path(fh.name)
    try:
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(dst)]
        )
    finally:
        listfile.unlink(missing_ok=True)
    return dst


def concat_with_transitions(
    clips: list[Path],
    params: list[MotionParams],
    transitions: list[TransitionSpec],
    out: OutputSpec,
    dst: Path,
    progress=None,
) -> Path:
    """전환을 적용하며 순차 결합한다.

    두 클립씩 누적 결합합니다. 200장을 한 번에 묶으면 ffmpeg가 감당하지 못합니다.
    """
    if not clips:
        raise ValueError("결합할 클립이 없습니다")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        run_ffmpeg(["-i", str(clips[0]), "-c", "copy", str(dst)])
        return dst

    if all(t.type == "none" for t in transitions):
        return _concat_demuxer(clips, dst)

    offsets = xfade_offsets(params, transitions)
    tmpdir = Path(tempfile.mkdtemp(prefix="pvt_concat_"))
    try:
        acc = clips[0]
        for i, spec in enumerate(transitions):
            nxt = clips[i + 1]
            step_out = tmpdir / f"step_{i:04d}.mp4"
            if spec.type == "none":
                _concat_demuxer([acc, nxt], step_out)
            else:
                run_ffmpeg([
                    "-i", str(acc),
                    "-i", str(nxt),
                    "-filter_complex",
                    f"[0:v][1:v]xfade=transition={spec.type}"
                    f":duration={spec.duration_sec:g}:offset={offsets[i]:g},"
                    f"format=yuv420p,fps={out.fps}",
                    "-r", str(out.fps),
                    *_VIDEO_ARGS,
                    "-an",
                    str(step_out),
                ])
            acc = step_out
            if progress:
                progress(i + 1, len(transitions))
        dst.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(["-i", str(acc), "-c", "copy", str(dst)])
    finally:
        for f in tmpdir.glob("*"):
            f.unlink(missing_ok=True)
        tmpdir.rmdir()
    return dst


def render_transition_preview(
    clip_a: Path,
    clip_b: Path,
    spec: TransitionSpec,
    out: OutputSpec,
    dst: Path,
    tail_sec: float = 2.0,
) -> Path:
    """전환 1개 미리보기: 앞뒤 클립에서 각 2초분만 잘라 xfade (섹션 10.5)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if spec.type == "none":
        return _concat_demuxer([clip_a, clip_b], dst)

    dur = spec.duration_sec
    head = max(tail_sec, dur + 0.2)
    offset = max(tail_sec - dur, 0.0)
    run_ffmpeg([
        "-sseof", f"-{tail_sec:g}", "-i", str(clip_a),
        "-t", f"{head:g}", "-i", str(clip_b),
        "-filter_complex",
        f"[0:v]fps={out.fps},format=yuv420p[a];"
        f"[1:v]fps={out.fps},format=yuv420p[b];"
        f"[a][b]xfade=transition={spec.type}:duration={dur:g}:offset={offset:g},"
        f"format=yuv420p",
        "-r", str(out.fps),
        *_VIDEO_ARGS,
        "-an",
        str(dst),
    ])
    return dst


def ffmpeg_version() -> str:
    proc = subprocess.run(  # noqa: S603
        [ffmpeg_path(), "-version"], capture_output=True, check=False, timeout=30
    )
    return proc.stdout.decode("utf-8", "replace").splitlines()[0] if proc.stdout else "unknown"
