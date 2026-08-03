"""파이프라인 통합: 인제스트 → 확정 → 모션 → 결합 → 내보내기."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.export import build_export_zip, generate_build_script, stats_csv
from app.ffmpeg_motion import concat_with_transitions, render_clip, render_transition_preview
from app.ffmpeg_util import ffprobe_duration
from app.pipeline import commit_grade, evaluate_grade, evaluate_motion, ingest_file
from app.schemas import MotionRules

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg가 없습니다")


@pytest.fixture
def loaded(state, photo_dir: Path):
    for f in sorted(photo_dir.glob("*.jpg")):
        ingest_file(state, f, f.name)
    return state


# ------------------------------------------------------------------ 1단계


def test_인제스트는_원본을_수정하지_않는다(state, photo_dir: Path):
    """섹션 12-9: 원본 파일을 절대 수정하지 않습니다."""
    src = next(photo_dir.glob("*.jpg"))
    before = src.read_bytes()
    ingest_file(state, src, src.name)
    assert src.read_bytes() == before


def test_같은_파일을_두_번_올려도_한_장(state, photo_dir: Path):
    """캐시 키는 파일명이 아니라 내용 해시입니다."""
    src = next(photo_dir.glob("*.jpg"))
    a = ingest_file(state, src, src.name)
    copy = src.parent / "다른 이름.jpg"
    shutil.copy2(src, copy)
    b = ingest_file(state, copy, copy.name)
    assert a.id == b.id
    assert len(state.photos) == 1


def test_한글_파일명_전체_경로가_동작한다(loaded):
    assert len(loaded.photos) == 5
    assert any("한" <= c <= "힣" for p in loaded.photos.values() for c in p.filename)


def test_세로_사진이_세로로_측정된다(loaded):
    portrait = next(p for p in loaded.photos.values() if "세로" in p.filename)
    assert portrait.stats.height > portrait.stats.width


def test_평가는_재측정_없이_동작한다(loaded, monkeypatch):
    """슬라이더 조작 시 이미지를 다시 읽으면 안 됩니다."""
    import app.pipeline as pipeline

    def boom(*a, **k):
        raise AssertionError("evaluate 중에 이미지를 다시 읽었습니다")

    monkeypatch.setattr(pipeline, "imread", boom)
    res = evaluate_grade(loaded, loaded.load_grade_rules())
    assert len(res.params) == 5


def test_확정하면_graded_png가_생긴다(loaded):
    """완료 기준: 확정 시 work/graded/에 PNG가 생성되고 2단계가 열린다."""
    n = commit_grade(loaded, loaded.load_grade_rules())
    assert n == 5
    assert loaded.committed
    pngs = list(loaded.work.graded.glob("*.png"))
    assert len(pngs) == 5
    for p in loaded.photos.values():
        assert p.graded_path.is_file()
        # 중간본은 원본 해상도를 유지해야 한다
        from app.imageio import read_exif_oriented_size

        assert read_exif_oriented_size(p.graded_path) == (p.stats.width, p.stats.height)


def test_되돌아가면_graded가_비워지고_통계는_남는다(loaded):
    commit_grade(loaded, loaded.load_grade_rules())
    assert list(loaded.work.graded.glob("*.png"))

    loaded.invalidate_stage2()
    assert not list(loaded.work.graded.glob("*.png"))
    assert not loaded.committed
    # 통계 캐시는 유지 — 원본이 안 바뀌었으므로
    assert len(loaded.photos) == 5
    assert all(p.stats.width > 0 for p in loaded.photos.values())


# ------------------------------------------------------------------ 2단계


def test_모션_평가와_총_길이(loaded):
    commit_grade(loaded, loaded.load_grade_rules())
    rules = loaded.load_motion_rules()
    res = evaluate_motion(loaded, rules)

    assert len(res.clips) == 5
    assert len(res.transitions) == 4
    expected = res.sum_duration_sec - res.transition_saving_sec
    assert res.total_duration_sec == pytest.approx(expected)


def test_저해상도_사진에_max_zoom_배지(loaded):
    commit_grade(loaded, loaded.load_grade_rules())
    res = evaluate_motion(loaded, loaded.load_motion_rules())
    low = next(c for c in res.clips if "저해상도" in loaded.photos[c.id].filename)
    assert "max_zoom" in low.clamped


def test_전환_결합_길이가_계산과_일치한다(loaded, tmp_path: Path):
    """완료 기준: 전환 반영된 총 길이가 UI에 정확히 표시된다."""
    commit_grade(loaded, loaded.load_grade_rules())
    rules = MotionRules()
    rules.duration.base_sec = 1.5
    rules.duration.min_sec = 1.5
    rules.output.width, rules.output.height = 640, 360  # 테스트를 빠르게
    res = evaluate_motion(loaded, rules)

    clips = []
    for mp in res.clips:
        p = loaded.photos[mp.id]
        dst = tmp_path / f"c{mp.index}.mp4"
        render_clip(p.graded_path, dst, mp, rules.output, rules)
        clips.append(dst)

    final = tmp_path / "final.mp4"
    concat_with_transitions(clips, res.clips, res.transitions, rules.output, final)
    assert final.is_file()
    assert ffprobe_duration(final) == pytest.approx(res.total_duration_sec, abs=0.25)


def test_전환_미리보기(loaded, tmp_path: Path):
    commit_grade(loaded, loaded.load_grade_rules())
    rules = MotionRules()
    rules.output.width, rules.output.height = 640, 360
    res = evaluate_motion(loaded, rules)

    clips = []
    for mp in res.clips[:2]:
        p = loaded.photos[mp.id]
        dst = tmp_path / f"c{mp.index}.mp4"
        render_clip(p.graded_path, dst, mp, rules.output, rules)
        clips.append(dst)

    out = tmp_path / "t.mp4"
    render_transition_preview(clips[0], clips[1], res.transitions[0], rules.output, out)
    assert out.is_file()
    # 앞뒤 2초씩만 잘라내므로 전체 클립보다 훨씬 짧아야 한다
    assert 0.5 < ffprobe_duration(out) < 5.0


# ------------------------------------------------------------------ 내보내기


def test_export_zip_구성(loaded):
    commit_grade(loaded, loaded.load_grade_rules())
    data = build_export_zip(loaded, loaded.load_grade_rules(), loaded.load_motion_rules())
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        names = set(z.namelist())
        assert {"grade.yaml", "motion.yaml", "build.sh", "stats.csv"} <= names
        script = z.read("build.sh").decode()
        assert script.startswith("#!/usr/bin/env bash")
        assert "zoompan" in script


def test_stats_csv에_클램프가_담긴다(loaded):
    commit_grade(loaded, loaded.load_grade_rules())
    csv_text = stats_csv(loaded, loaded.load_grade_rules(), loaded.load_motion_rules())
    lines = csv_text.strip().splitlines()
    assert len(lines) == 6  # 헤더 + 5장
    assert "grade_clamped" in lines[0]
    assert "motion_clamped" in lines[0]


def _psnr(a: Path, b: Path) -> float:
    """두 영상의 PSNR. ffmpeg가 계산합니다 (inf면 완전히 동일)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b),
         "-lavfi", "psnr=stats_file=-", "-f", "null", "-"],
        capture_output=True, check=True, timeout=300,
    )
    text = proc.stderr.decode("utf-8", "replace")
    for line in text.splitlines():
        if "average:" in line and "PSNR" in line:
            part = line.split("average:")[1].split()[0]
            return float("inf") if part == "inf" else float(part)
    raise AssertionError(f"PSNR을 파싱하지 못했습니다:\n{text[-800:]}")


def test_build_sh가_동일한_영상을_만든다(loaded, tmp_path: Path):
    """완료 기준 중 가장 중요한 항목:
    내보낸 build.sh가 UI에서 본 것과 동일한 mp4를 만든다.
    """
    grade_rules = loaded.load_grade_rules()
    commit_grade(loaded, grade_rules)

    rules = MotionRules()
    rules.duration.base_sec = 1.5
    rules.duration.min_sec = 1.5
    rules.output.width, rules.output.height = 640, 360

    # (1) 앱 경로: single_pass로 원본에서 직접 렌더
    from app.ffmpeg_grade import build_grade_filters
    from app.grade import compute_grade

    res = evaluate_motion(loaded, rules)
    app_clips = []
    for mp in res.clips:
        p = loaded.photos[mp.id]
        g = compute_grade(p.stats, p.exif, grade_rules, has_face=bool(p.faces))
        dst = tmp_path / f"app_{mp.index}.mp4"
        render_clip(p.path, dst, mp, rules.output, rules,
                    grade_filters=build_grade_filters(g))
        app_clips.append(dst)
    app_final = tmp_path / "app_final.mp4"
    concat_with_transitions(app_clips, res.clips, res.transitions, rules.output, app_final)

    # (2) 내보내기 경로: build.sh를 그대로 실행
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    for p in loaded.photos.values():
        shutil.copy2(p.path, photos_dir / p.filename)

    script = tmp_path / "build.sh"
    script.write_text(
        generate_build_script(loaded, grade_rules, rules, single_pass=True), encoding="utf-8"
    )
    script.chmod(0o755)
    sh_final = tmp_path / "sh_final.mp4"
    proc = subprocess.run(
        ["bash", str(script), str(photos_dir), str(sh_final)],
        capture_output=True, timeout=900, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    assert sh_final.is_file()

    assert ffprobe_duration(sh_final) == pytest.approx(ffprobe_duration(app_final), abs=0.1)
    psnr = _psnr(app_final, sh_final)
    assert psnr > 50 or psnr == float("inf"), f"build.sh 결과가 다릅니다 (PSNR {psnr})"


def test_build_sh는_한글_파일명을_인용한다(loaded):
    commit_grade(loaded, loaded.load_grade_rules())
    script = generate_build_script(
        loaded, loaded.load_grade_rules(), loaded.load_motion_rules()
    )
    for p in loaded.photos.values():
        assert f"'{p.filename}'" in script, f"파일명이 인용되지 않음: {p.filename}"


def test_기본_순서는_촬영시각_순이다(state, photo_dir: Path):
    """완료 기준: 사진이 EXIF 촬영시각 순으로 정렬된다.

    인제스트는 병렬이라 완료 순서가 매번 다릅니다. 그 순서가 타임라인이 되면
    안 됩니다.
    """
    from app.pipeline import ingest_many

    sources = [(f, f.name) for f in sorted(photo_dir.glob("*.jpg"))]
    ingest_many(state, sources)

    ordered = state.ordered_photos()
    dated = [p for p in ordered if p.captured_at]
    assert [p.captured_at for p in dated] == sorted(p.captured_at for p in dated)
    # 촬영시각이 없는 사진은 뒤로
    assert all(p.captured_at for p in ordered[: len(dated)])

    # 여러 번 불러도 같은 순서여야 한다
    assert [p.id for p in state.ordered_photos()] == [p.id for p in ordered]


def test_수동_순서가_유지되고_새_사진은_뒤에_붙는다(state, photo_dir: Path):
    from app.pipeline import ingest_many

    files = sorted(photo_dir.glob("*.jpg"))
    ingest_many(state, [(f, f.name) for f in files[:3]])

    manual = list(reversed([p.id for p in state.ordered_photos()]))
    state.order = manual
    assert [p.id for p in state.ordered_photos()] == manual

    ingest_many(state, [(f, f.name) for f in files[3:]])
    after = [p.id for p in state.ordered_photos()]
    assert after[: len(manual)] == manual, "수동 순서가 깨졌습니다"
    assert len(after) == len(files), "새로 추가된 사진이 유실됐습니다"
