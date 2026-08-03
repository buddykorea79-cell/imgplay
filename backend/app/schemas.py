"""규칙 파일 스키마와 API 모델.

규칙은 전부 yaml에서 옵니다. 코드에 상수를 심지 마세요 — 심는 순간 UI에서
튜닝한 값과 배치 파이프라인이 읽는 값이 갈라집니다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- 1단계 규칙


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GradeTarget(_Strict):
    median_L: float = 50.0
    spread_L: float = 55.0
    mean_sat: float = 0.42


class GammaRule(_Strict):
    enabled: bool = True
    min: float = 0.75
    max: float = 1.35


class ContrastRule(_Strict):
    min: float = 0.92
    max: float = 1.28
    clip_threshold_pct: float = 1.0
    clip_penalty: float = 0.06


class SaturationRule(_Strict):
    min: float = 0.88
    max: float = 1.32
    skin_max: float = 1.10


class UnsharpRule(_Strict):
    base: float = 1.2
    divisor: float = 400.0
    min: float = 0.2
    max: float = 1.2


class WhiteBalanceRule(_Strict):
    enabled: bool = True
    max_deviation: float = 0.15


class NightGuard(_Strict):
    enabled: bool = True
    iso_min: int = 1600
    shutter_max: float = 0.04
    hour_range: tuple[int, int] = (19, 6)
    gamma_max: float = 1.10
    saturation_max: float = 1.15


class LowKeyGuard(_Strict):
    enabled: bool = True
    median_L_below: float = 28.0
    gamma_max: float = 1.15


class HighContrastGuard(_Strict):
    enabled: bool = True
    spread_L_above: float = 78.0
    contrast_max: float = 1.05


class Guards(_Strict):
    night: NightGuard = Field(default_factory=NightGuard)
    lowkey: LowKeyGuard = Field(default_factory=LowKeyGuard)
    highcontrast: HighContrastGuard = Field(default_factory=HighContrastGuard)


class GradeRules(_Strict):
    version: int = 1
    target: GradeTarget = Field(default_factory=GradeTarget)
    gamma: GammaRule = Field(default_factory=GammaRule)
    contrast: ContrastRule = Field(default_factory=ContrastRule)
    saturation: SaturationRule = Field(default_factory=SaturationRule)
    unsharp: UnsharpRule = Field(default_factory=UnsharpRule)
    whitebalance: WhiteBalanceRule = Field(default_factory=WhiteBalanceRule)
    guards: Guards = Field(default_factory=Guards)


# ---------------------------------------------------------------- 2단계 규칙


class OutputSpec(_Strict):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    preview_height: int = 540

    @property
    def key(self) -> str:
        return f"{self.width}x{self.height}@{self.fps}"


class DurationRule(_Strict):
    base_sec: float = 5.0
    min_sec: float = 3.0
    max_sec: float = 8.0
    complexity_bonus: float = 0.0


class ZoomRule(_Strict):
    enabled: bool = True
    amount: float = 0.12
    hard_max: float = 1.35
    safety: float = 0.9
    direction: Literal["auto", "in", "out", "alternate"] = "auto"
    ease: Literal["linear", "ease_in_out"] = "linear"


class PanRule(_Strict):
    enabled: bool = True
    toward_poi: bool = True
    max_offset: float = 0.18


class AspectRule(_Strict):
    mode: Literal["blur_fill", "crop", "pad"] = "blur_fill"
    blur_sigma: float = 40.0
    deviation_threshold: float = 0.12


class TransitionRule(_Strict):
    default: str = "fade"
    duration_sec: float = 0.8
    similar_threshold: float = 0.25
    different_threshold: float = 0.60
    on_similar: str = "fade"
    on_different: str = "fadeblack"
    on_scene_gap_min: float = 30.0


class MotionRules(_Strict):
    version: int = 1
    output: OutputSpec = Field(default_factory=OutputSpec)
    duration: DurationRule = Field(default_factory=DurationRule)
    zoom: ZoomRule = Field(default_factory=ZoomRule)
    pan: PanRule = Field(default_factory=PanRule)
    aspect: AspectRule = Field(default_factory=AspectRule)
    transition: TransitionRule = Field(default_factory=TransitionRule)


# ---------------------------------------------------------------- API 모델


class FaceBox(BaseModel):
    x: float
    y: float
    w: float
    h: float
    confidence: float


class PhotoStats(BaseModel):
    """업로드 1장의 측정 결과. 1·2단계가 공유합니다."""

    id: str
    filename: str
    width: int
    height: int
    stats: dict
    exif: dict
    faces: list[FaceBox] = Field(default_factory=list)
    thumb_url: str = ""


class GradeParams(BaseModel):
    id: str
    gamma: float
    contrast: float
    saturation: float
    unsharp: float
    wb: dict[str, float]
    wb_enabled: bool
    clamped: list[str] = Field(default_factory=list)
    guards_applied: list[str] = Field(default_factory=list)


class GradeEvaluateRequest(BaseModel):
    rules: GradeRules
    ids: list[str] | None = None


class GradeEvaluateResponse(BaseModel):
    params: list[GradeParams]
    clamp_rate: float
    clamp_counts: dict[str, int]


class MotionParams(BaseModel):
    id: str
    index: int
    duration_sec: float
    zoom_start: float
    zoom_end: float
    dx: float
    dy: float
    poi_x: float
    poi_y: float
    max_zoom: float
    aspect_dev: float
    aspect_mode: str  # none | blur_fill | crop | pad
    ease: str
    clamped: list[str] = Field(default_factory=list)


class TransitionSpec(BaseModel):
    index: int  # i번째 클립과 i+1번째 클립 사이
    type: str
    duration_sec: float
    hist_distance: float
    gap_minutes: float | None
    reason: str


class MotionEvaluateRequest(BaseModel):
    rules: MotionRules
    order: list[str] | None = None


class MotionEvaluateResponse(BaseModel):
    clips: list[MotionParams]
    transitions: list[TransitionSpec]
    total_duration_sec: float
    sum_duration_sec: float
    transition_saving_sec: float
    clamp_counts: dict[str, int]
    clamp_rate: float


class OrderRequest(BaseModel):
    order: list[str]


class CommitRequest(BaseModel):
    rules: GradeRules


class RenderRequest(BaseModel):
    grade_rules: GradeRules | None = None
    motion_rules: MotionRules
    order: list[str] | None = None
    single_pass: bool = False  # True면 graded/ 중간본 없이 원본에서 직접


class StageStatus(BaseModel):
    uploaded: int
    committed: bool
    committed_count: int
    stage2_unlocked: bool
    graded_dir: str
