"""CLI 검증 도구 (섹션 15).

UI를 먼저 만들면 계산 로직 버그가 UI 버그로 위장돼 디버깅이 몇 배 어려워집니다.
그래서 백엔드를 여기서 먼저 검증합니다.

    pvt ingest ./사진폴더        # 측정 + 통계 표
    pvt grade                    # 보정 파라미터 + 클램프 히트율
    pvt commit                   # graded/ PNG 생성
    pvt poi --out ./poi          # POI 마커를 그려 눈으로 검증
    pvt motion                   # 모션 파라미터 + 전환 + 총 길이
    pvt clip <id|index>          # 단일 클립 렌더
    pvt render                   # 전체 렌더
    pvt export ./export.zip
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .cache import sha256_file
from .compose import draw_poi_marker
from .export import build_export_zip
from .ffmpeg_motion import render_clip
from .imageio import imread, imwrite
from .pipeline import (
    IMAGE_SUFFIXES,
    commit_grade,
    ensure_compositions,
    evaluate_grade,
    evaluate_motion,
    ingest_file,
)
from .render import RenderJob, run_render
from .state import get_state


def _iter_images(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            yield p


def cmd_ingest(args) -> int:
    st = get_state()
    root = Path(args.path)
    if not root.exists():
        print(f"경로가 없습니다: {root}", file=sys.stderr)
        return 1

    t0 = time.time()
    count = 0
    for f in _iter_images(root):
        try:
            p = ingest_file(st, f, f.name)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {f.name}: {exc}", file=sys.stderr)
            continue
        count += 1
        s = p.stats
        print(
            f"  {p.filename:<32.32s} {s.width}x{s.height}  "
            f"L={s.median_L:5.1f} spread={s.spread_L:5.1f} sat={s.mean_sat:.3f} "
            f"sharp={s.sharpness:7.1f} faces={len(p.faces)} "
            f"iso={p.exif.iso or '-'}"
        )
    print(f"\n{count}장 측정 완료 ({time.time() - t0:.1f}초)")
    return 0


def cmd_grade(args) -> int:
    st = get_state()
    rules = st.load_grade_rules()
    res = evaluate_grade(st, rules)
    if not res.params:
        print("업로드된 사진이 없습니다. 먼저 `pvt ingest`를 실행하세요.", file=sys.stderr)
        return 1

    print(f"{'파일':<30.30s} {'gamma':>7} {'contr':>7} {'sat':>7} {'unsh':>6}  클램프 / 가드")
    print("-" * 96)
    for p in res.params:
        photo = st.photos[p.id]
        print(
            f"{photo.filename:<30.30s} {p.gamma:7.3f} {p.contrast:7.3f} "
            f"{p.saturation:7.3f} {p.unsharp:6.3f}  "
            f"{','.join(p.clamped) or '-':<24s} {','.join(p.guards_applied) or '-'}"
        )
    print("-" * 96)
    print(f"클램프 히트율: {res.clamp_rate * 100:.1f}%  항목별: {res.clamp_counts or '없음'}")
    if res.clamp_rate > 0.30:
        print("→ 30% 초과: 사진 성격이 너무 다양합니다. grade.yaml 분리를 검토하세요.")
    elif res.clamp_rate > 0.10:
        print("→ 10~30%: 클램프 범위나 target 조정으로 해결 가능한 수준입니다.")
    else:
        print("→ 10% 미만: 규칙이 잘 맞습니다.")
    return 0


def cmd_commit(args) -> int:
    st = get_state()
    rules = st.load_grade_rules()

    def prog(done: int, total: int, name: str) -> None:
        print(f"  [{done}/{total}] {name}")

    n = commit_grade(st, rules, prog)
    print(f"\n{n}장 확정 → {st.work.graded}")
    return 0


def cmd_poi(args) -> int:
    st = get_state()
    rules = st.load_motion_rules()
    ensure_compositions(st, rules)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for p in st.ordered_photos():
        c = p.composition
        src = p.graded_path if p.graded_path and p.graded_path.is_file() else p.path
        imwrite(out / f"{Path(p.filename).stem}_poi.jpg", draw_poi_marker(imread(src), c))
        print(
            f"  {p.filename:<30.30s} poi=({c.poi_x:.3f},{c.poi_y:.3f}) [{c.poi_source}] "
            f"max_zoom={c.max_zoom:.3f} headroom={c.headroom:.2f} dev={c.aspect_dev:.3f}"
        )
    print(f"\nPOI 마커 이미지 → {out}")
    return 0


def cmd_motion(args) -> int:
    st = get_state()
    rules = st.load_motion_rules()
    res = evaluate_motion(st, rules)
    if not res.clips:
        print("사진이 없습니다.", file=sys.stderr)
        return 1

    print(f"{'#':>3} {'파일':<28.28s} {'초':>5} {'줌':>13} {'팬 dx,dy':>15} {'종횡비':>10}  클램프")
    print("-" * 100)
    for c in res.clips:
        photo = st.photos[c.id]
        print(
            f"{c.index:3d} {photo.filename:<28.28s} {c.duration_sec:5.2f} "
            f"{c.zoom_start:5.3f}→{c.zoom_end:5.3f}  "
            f"{c.dx:+7.4f},{c.dy:+7.4f} {c.aspect_mode:>10}  {','.join(c.clamped) or '-'}"
        )
    print("-" * 100)
    for t in res.transitions:
        print(f"  {t.index:3d}→{t.index + 1:<3d} {t.type:<10s} {t.duration_sec:.2f}초  {t.reason}")
    print("-" * 100)
    print(
        f"총 길이 {res.total_duration_sec:.2f}초 "
        f"(= 클립 합 {res.sum_duration_sec:.2f} - 전환 {res.transition_saving_sec:.2f})"
    )
    print(f"클램프 히트율: {res.clamp_rate * 100:.1f}%  항목별: {res.clamp_counts or '없음'}")
    return 0


def cmd_clip(args) -> int:
    st = get_state()
    rules = st.load_motion_rules()
    res = evaluate_motion(st, rules)
    if args.target.isdigit() and int(args.target) < len(res.clips):
        mp = res.clips[int(args.target)]
    else:
        mp = next((c for c in res.clips if c.id.startswith(args.target)), None)
    if mp is None:
        print(f"클립을 찾을 수 없습니다: {args.target}", file=sys.stderr)
        return 1

    p = st.photos[mp.id]
    src = p.graded_path if p.graded_path and p.graded_path.is_file() else p.path
    dst = Path(args.out)
    t0 = time.time()
    render_clip(src, dst, mp, rules.output, rules, args.height)
    print(f"{dst}  ({time.time() - t0:.1f}초, {mp.duration_sec:.1f}초 분량)")
    print(f"  줌 {mp.zoom_start:.3f}→{mp.zoom_end:.3f}, 팬 ({mp.dx:+.4f},{mp.dy:+.4f}), "
          f"종횡비 모드 {mp.aspect_mode}")
    return 0


def cmd_render(args) -> int:
    st = get_state()
    job = RenderJob(id="cli")
    run_render(st, job, st.load_motion_rules(),
               st.load_grade_rules() if args.single_pass else None,
               None, args.single_pass)
    if job.phase == "error":
        print(f"렌더 실패: {job.error}", file=sys.stderr)
        return 1
    print(f"완료: {job.output}  ({job.payload()['elapsed_sec']}초)")
    return 0


def cmd_export(args) -> int:
    st = get_state()
    data = build_export_zip(st, st.load_grade_rules(), st.load_motion_rules())
    Path(args.out).write_bytes(data)
    print(f"{args.out}  ({len(data) / 1024:.1f} KB)")
    return 0


def cmd_reset(args) -> int:
    get_state().reset()
    print("초기화 완료")
    return 0


def cmd_hash(args) -> int:
    print(sha256_file(args.path))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pvt", description="사진 → 영상 2단계 튜닝 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="사진 폴더 측정")
    p.add_argument("path")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("grade", help="1단계 보정 파라미터 + 클램프 히트율")
    p.set_defaults(fn=cmd_grade)

    p = sub.add_parser("commit", help="1단계 확정 (graded PNG 생성)")
    p.set_defaults(fn=cmd_commit)

    p = sub.add_parser("poi", help="POI 마커 이미지 생성")
    p.add_argument("--out", default="./poi")
    p.set_defaults(fn=cmd_poi)

    p = sub.add_parser("motion", help="2단계 모션 파라미터 + 전환")
    p.set_defaults(fn=cmd_motion)

    p = sub.add_parser("clip", help="단일 클립 렌더")
    p.add_argument("target", help="타임라인 인덱스 또는 id 앞부분")
    p.add_argument("--out", default="./clip.mp4")
    p.add_argument("--height", type=int, default=None, help="미리보기 높이 (기본: 출력 해상도)")
    p.set_defaults(fn=cmd_clip)

    p = sub.add_parser("render", help="전체 렌더")
    p.add_argument("--single-pass", action="store_true", help="중간본 없이 원본에서 직접")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("export", help="내보내기 zip")
    p.add_argument("out", nargs="?", default="./export.zip")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("reset", help="업로드·중간본 초기화")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("hash", help="파일 SHA-256")
    p.add_argument("path")
    p.set_defaults(fn=cmd_hash)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
