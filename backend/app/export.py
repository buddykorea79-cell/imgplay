"""내보내기: `grade.yaml`, `motion.yaml`, `build.sh`, `stats.csv`를 zip으로.

완료 기준에서 가장 중요한 항목은 **내보낸 `build.sh`가 UI에서 본 것과 동일한
mp4를 만드는 것**입니다. 그래서 `build.sh`는 UI와 별도의 로직을 쓰지 않고,
`ffmpeg_grade`/`ffmpeg_motion`이 실제로 만들어낸 필터 문자열을 그대로 박아넣습니다.
같은 코드가 만든 같은 문자열이므로 결과가 갈라질 여지가 없습니다.
"""

from __future__ import annotations

import csv
import io
import zipfile

import yaml

from .ffmpeg_grade import build_grade_filters
from .ffmpeg_motion import _VIDEO_ARGS, build_clip_filter
from .grade import compute_grade
from .pipeline import evaluate_motion
from .schemas import GradeRules, MotionRules
from .state import AppState
from .timeline import xfade_offsets

__all__ = ["build_export_zip", "generate_build_script", "stats_csv"]


def _sh_quote(s: str) -> str:
    """작은따옴표 셸 인용. 한글 파일명이 그대로 들어가도 안전합니다."""
    return "'" + s.replace("'", "'\\''") + "'"


def generate_build_script(
    state: AppState, grade_rules: GradeRules, motion_rules: MotionRules,
    order: list[str] | None = None, single_pass: bool = True,
) -> str:
    """UI와 동일한 결과를 내는 재현 스크립트."""
    evald = evaluate_motion(state, motion_rules, order)
    out = motion_rules.output
    photos = {p.id: p for p in state.ordered_photos(order)}

    lines = [
        "#!/usr/bin/env bash",
        "# photo-video-tuner가 생성한 재현 스크립트.",
        "# UI에서 본 것과 동일한 mp4를 만듭니다 - 필터 문자열이 UI와 같은 코드에서 나왔습니다.",
        "#",
        "# 사용법:  ./build.sh [사진폴더] [출력파일]",
        "#   사진폴더 기본값 ./photos, 출력 기본값 ./final.mp4",
        "set -euo pipefail",
        "",
        'SRC_DIR="${1:-./photos}"',
        'OUT="${2:-./final.mp4}"',
        'TMP="$(mktemp -d)"',
        'trap \'rm -rf "$TMP"\' EXIT',
        "",
        f"# 출력 규격: {out.width}x{out.height} @ {out.fps}fps",
        f"# 총 길이: {evald.total_duration_sec:.2f}초 "
        f"(클립 합 {evald.sum_duration_sec:.2f}초 - 전환 {evald.transition_saving_sec:.2f}초)",
        "",
        "echo '=== 1/2 클립 렌더 ==='",
    ]

    clip_vars: list[str] = []
    for i, mp in enumerate(evald.clips):
        photo = photos[mp.id]
        chain = build_clip_filter(mp, out, motion_rules)
        if single_pass:
            g = compute_grade(photo.stats, photo.exif, grade_rules, has_face=bool(photo.faces))
            gf = build_grade_filters(g)
            if gf:
                chain = ",".join(gf) + "," + chain
        frames = max(round(mp.duration_sec * out.fps), 1)
        var = f"C{i}"
        clip_vars.append(var)
        lines += [
            f'echo "  [{i + 1}/{len(evald.clips)}] {photo.filename}"',
            f'{var}="$TMP/clip_{i:04d}.mp4"',
            "ffmpeg -hide_banner -loglevel error -y -loop 1 \\",
            f'  -i "$SRC_DIR"/{_sh_quote(photo.filename)} \\',
            f'  -filter_complex {_sh_quote(chain)} \\',
            f"  -frames:v {frames} -r {out.fps} {' '.join(_VIDEO_ARGS)} -an \\",
            f'  "${var}"',
            "",
        ]

    lines.append("echo '=== 2/2 전환 결합 ==='")
    if not evald.transitions:
        lines += (
            [f'cp "${clip_vars[0]}" "$OUT"']
            if clip_vars
            else ["echo '사진이 없습니다'; exit 1"]
        )
    else:
        offsets = xfade_offsets(evald.clips, evald.transitions)
        lines.append(f'ACC="${clip_vars[0]}"')
        for i, t in enumerate(evald.transitions):
            step = f'"$TMP/step_{i:04d}.mp4"'
            xfade = (
                f"[0:v][1:v]xfade=transition={t.type}:duration={t.duration_sec:g}"
                f":offset={offsets[i]:g},format=yuv420p,fps={out.fps}"
            )
            lines += [
                f'echo "  전환 {i + 1}/{len(evald.transitions)}: {t.type} ({t.reason})"',
                f'ffmpeg -hide_banner -loglevel error -y -i "$ACC" -i "${clip_vars[i + 1]}" \\',
                f"  -filter_complex {_sh_quote(xfade)} \\",
                f"  -r {out.fps} {' '.join(_VIDEO_ARGS)} -an {step}",
                f"ACC={step}",
                "",
            ]
        lines.append('cp "$ACC" "$OUT"')

    lines += ["", 'echo "완료: $OUT"']
    return "\n".join(lines) + "\n"


def stats_csv(state: AppState, grade_rules: GradeRules, motion_rules: MotionRules) -> str:
    """사진별 측정값·보정값·모션값·클램프 히트를 한 표로."""
    evald = evaluate_motion(state, motion_rules)
    motion_by_id = {c.id: c for c in evald.clips}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "filename", "id", "width", "height",
        "median_L", "p05_L", "p95_L", "spread_L",
        "clip_black_pct", "clip_white_pct", "mean_sat", "sharpness", "mean_hue",
        "iso", "exposure_time", "datetime_original", "faces",
        "gamma", "contrast", "saturation", "unsharp", "wb_r", "wb_g", "wb_b",
        "grade_clamped", "guards",
        "duration_sec", "zoom_start", "zoom_end", "dx", "dy",
        "poi_x", "poi_y", "poi_source", "max_zoom", "aspect_dev", "aspect_mode",
        "motion_clamped",
    ])
    for p in state.ordered_photos():
        s, g = p.stats, compute_grade(p.stats, p.exif, grade_rules, has_face=bool(p.faces))
        m = motion_by_id.get(p.id)
        comp = p.composition
        w.writerow([
            p.filename, p.id[:12], s.width, s.height,
            f"{s.median_L:.2f}", f"{s.p05_L:.2f}", f"{s.p95_L:.2f}", f"{s.spread_L:.2f}",
            f"{s.clip_black_pct:.3f}", f"{s.clip_white_pct:.3f}",
            f"{s.mean_sat:.4f}", f"{s.sharpness:.1f}", f"{s.mean_hue:.1f}",
            p.exif.iso or "", p.exif.exposure_time or "",
            p.exif.datetime_original.isoformat() if p.exif.datetime_original else "",
            len(p.faces),
            f"{g.gamma:.4f}", f"{g.contrast:.4f}", f"{g.saturation:.4f}", f"{g.unsharp:.4f}",
            f"{g.wb['r']:.4f}", f"{g.wb['g']:.4f}", f"{g.wb['b']:.4f}",
            "|".join(g.clamped), "|".join(g.guards_applied),
            f"{m.duration_sec:.2f}" if m else "", f"{m.zoom_start:.4f}" if m else "",
            f"{m.zoom_end:.4f}" if m else "", f"{m.dx:.4f}" if m else "",
            f"{m.dy:.4f}" if m else "",
            f"{comp.poi_x:.4f}" if comp else "", f"{comp.poi_y:.4f}" if comp else "",
            comp.poi_source if comp else "", f"{comp.max_zoom:.4f}" if comp else "",
            f"{comp.aspect_dev:.4f}" if comp else "", m.aspect_mode if m else "",
            "|".join(m.clamped) if m else "",
        ])
    return buf.getvalue()


def build_export_zip(
    state: AppState, grade_rules: GradeRules, motion_rules: MotionRules
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "grade.yaml",
            yaml.safe_dump(grade_rules.model_dump(), allow_unicode=True, sort_keys=False),
        )
        z.writestr(
            "motion.yaml",
            yaml.safe_dump(motion_rules.model_dump(), allow_unicode=True, sort_keys=False),
        )
        script = generate_build_script(state, grade_rules, motion_rules)
        info = zipfile.ZipInfo("build.sh")
        info.external_attr = 0o755 << 16  # 압축 해제 후 바로 실행 가능하게
        z.writestr(info, script)
        z.writestr("stats.csv", stats_csv(state, grade_rules, motion_rules))
        z.writestr("README.txt", _readme(state, motion_rules))
    return buf.getvalue()


def _readme(state: AppState, motion_rules: MotionRules) -> str:
    names = "\n".join(f"  {i + 1:3d}. {p.filename}" for i, p in enumerate(state.ordered_photos()))
    return (
        "photo-video-tuner 내보내기\n"
        "==========================\n\n"
        "grade.yaml   1단계 화질 보정 규칙\n"
        "motion.yaml  2단계 영상 효과 규칙\n"
        "build.sh     UI와 동일한 결과를 내는 재현 스크립트\n"
        "stats.csv    사진별 측정값·적용값·클램프 히트\n\n"
        "실행:\n"
        "  1) 원본 사진을 ./photos/ 에 둡니다 (파일명 그대로)\n"
        "  2) ./build.sh ./photos ./final.mp4\n\n"
        f"출력 규격: {motion_rules.output.width}x{motion_rules.output.height} "
        f"@ {motion_rules.output.fps}fps\n\n"
        f"타임라인 순서 ({len(state.photos)}장):\n{names}\n"
    )
