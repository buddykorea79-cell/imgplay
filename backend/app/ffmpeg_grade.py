"""1단계 필터 조립 및 렌더 (섹션 7).

순서가 결과를 바꿉니다:
    colorchannelmixer (화이트밸런스) → eq (감마·대비·채도) → unsharp (마지막)

샤픈이 마지막인 이유는 밝기·대비 보정이 노이즈를 증폭시키기 때문입니다. 먼저
걸면 그 노이즈까지 강조됩니다.

미리보기도 **반드시 ffmpeg로** 만듭니다(섹션 12-4). OpenCV로 흉내내면 실제
렌더와 미묘하게 달라지고, 눈으로 튜닝한 값이 재현되지 않으면 이 도구는
존재 이유를 잃습니다.
"""

from __future__ import annotations

from pathlib import Path

from .ffmpeg_util import run_ffmpeg
from .grade import GradeResult

__all__ = ["build_grade_filters", "render_graded", "render_preview_jpeg"]


def build_grade_filters(g: GradeResult) -> list[str]:
    """보정 필터 목록. 비어 있을 수 있습니다(무보정)."""
    filters: list[str] = []
    if g.wb_enabled:
        filters.append(
            f"colorchannelmixer=rr={g.wb['r']:.4f}:gg={g.wb['g']:.4f}:bb={g.wb['b']:.4f}"
        )
    filters.append(
        f"eq=gamma={g.gamma:.4f}:contrast={g.contrast:.4f}:saturation={g.saturation:.4f}"
    )
    if g.unsharp > 0.01:
        # 마지막 인자 0.0은 채도 채널 샤픈을 끕니다. 색 경계 링잉 방지용.
        filters.append(f"unsharp=5:5:{g.unsharp:.3f}:5:5:0.0")
    return filters


def _scale_filter(mode: str, long_edge: int | None, crop_size: int | None) -> list[str]:
    """미리보기용 스케일/크롭 필터.

    fit  : 긴 변을 long_edge로 축소 (전체 구도 확인)
    crop : 중앙 crop_size 픽셀을 1:1로 잘라냄 (100% 크롭 — 언샤프 과다 판단용)
    """
    if mode == "crop" and crop_size:
        return [f"crop='min(iw,{crop_size})':'min(ih,{crop_size})'"]
    if long_edge:
        return [
            f"scale='if(gt(iw,ih),{long_edge},-2)':'if(gt(iw,ih),-2,{long_edge})':flags=lanczos"
        ]
    return []


def render_graded(
    src: Path,
    dst: Path,
    g: GradeResult,
    long_edge: int | None = None,
) -> Path:
    """보정본을 파일로 렌더한다. 확장자가 .png면 무손실입니다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    chain = _scale_filter("fit", long_edge, None) + build_grade_filters(g)
    args = ["-i", str(src)]
    if chain:
        args += ["-vf", ",".join(chain)]
    args += ["-frames:v", "1"]
    if dst.suffix.lower() == ".png":
        # 중간본은 PNG 무손실. JPEG로 두면 2단계에서 재인코딩 손실이 누적됩니다.
        args += ["-compression_level", "6", "-pix_fmt", "rgb24"]
    else:
        args += ["-q:v", "2"]
    run_ffmpeg(args + [str(dst)])
    return dst


def render_preview_jpeg(
    src: Path,
    g: GradeResult | None,
    mode: str = "fit",
    long_edge: int = 1280,
    crop_size: int = 900,
    quality: int = 3,
) -> bytes:
    """미리보기 JPEG를 메모리로 받는다.

    `g`가 None이면 원본을 같은 스케일로 렌더합니다 — 비교 뷰가 동일한 리샘플링을
    거쳐야 차이가 보정 때문인지 축소 때문인지 헷갈리지 않습니다.
    """
    chain = _scale_filter(mode, long_edge if mode == "fit" else None, crop_size)
    if g is not None:
        chain += build_grade_filters(g)
    args = ["-i", str(src)]
    if chain:
        args += ["-vf", ",".join(chain)]
    args += ["-frames:v", "1", "-q:v", str(quality), "-f", "mjpeg", "pipe:1"]
    return run_ffmpeg(args, capture=True)
