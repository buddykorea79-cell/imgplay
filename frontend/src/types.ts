/** 백엔드 스키마와 1:1로 대응합니다 (backend/app/schemas.py). */

export interface Stats {
  median_L: number;
  p05_L: number;
  p95_L: number;
  spread_L: number;
  clip_black_pct: number;
  clip_white_pct: number;
  mean_sat: number;
  sharpness: number;
  wb_gains: { r: number; g: number; b: number };
  hist_L: number[];
  mean_hue: number;
  width: number;
  height: number;
}

export interface Exif {
  iso: number | null;
  exposure_time: number | null;
  f_number: number | null;
  flash: boolean | null;
  datetime_original: string | null;
  focal_length: number | null;
  orientation: number | null;
}

export interface FaceBox {
  x: number;
  y: number;
  w: number;
  h: number;
  confidence: number;
}

export interface Photo {
  id: string;
  filename: string;
  width: number;
  height: number;
  stats: Stats;
  exif: Exif;
  faces: FaceBox[];
  thumb_url: string;
}

// ---------------------------------------------------------------- 1단계 규칙

export interface GradeRules {
  version: number;
  target: { median_L: number; spread_L: number; mean_sat: number };
  gamma: { enabled: boolean; min: number; max: number };
  contrast: {
    min: number;
    max: number;
    clip_threshold_pct: number;
    clip_penalty: number;
  };
  saturation: { min: number; max: number; skin_max: number };
  unsharp: { base: number; divisor: number; min: number; max: number };
  whitebalance: { enabled: boolean; max_deviation: number };
  guards: {
    night: {
      enabled: boolean;
      iso_min: number;
      shutter_max: number;
      hour_range: [number, number];
      gamma_max: number;
      saturation_max: number;
    };
    lowkey: { enabled: boolean; median_L_below: number; gamma_max: number };
    highcontrast: {
      enabled: boolean;
      spread_L_above: number;
      contrast_max: number;
    };
  };
}

export interface GradeParams {
  id: string;
  gamma: number;
  contrast: number;
  saturation: number;
  unsharp: number;
  wb: { r: number; g: number; b: number };
  wb_enabled: boolean;
  clamped: string[];
  guards_applied: string[];
}

export interface GradeEvaluation {
  params: GradeParams[];
  clamp_rate: number;
  clamp_counts: Record<string, number>;
}

// ---------------------------------------------------------------- 2단계 규칙

export interface MotionRules {
  version: number;
  output: { width: number; height: number; fps: number; preview_height: number };
  duration: {
    base_sec: number;
    min_sec: number;
    max_sec: number;
    complexity_bonus: number;
  };
  zoom: {
    enabled: boolean;
    amount: number;
    hard_max: number;
    safety: number;
    direction: "auto" | "in" | "out" | "alternate";
    ease: "linear" | "ease_in_out";
  };
  pan: { enabled: boolean; toward_poi: boolean; max_offset: number };
  aspect: {
    mode: "blur_fill" | "crop" | "pad";
    blur_sigma: number;
    deviation_threshold: number;
  };
  transition: {
    default: string;
    duration_sec: number;
    similar_threshold: number;
    different_threshold: number;
    on_similar: string;
    on_different: string;
    on_scene_gap_min: number;
  };
}

export interface MotionParams {
  id: string;
  index: number;
  duration_sec: number;
  zoom_start: number;
  zoom_end: number;
  dx: number;
  dy: number;
  poi_x: number;
  poi_y: number;
  max_zoom: number;
  aspect_dev: number;
  aspect_mode: string;
  ease: string;
  clamped: string[];
}

export interface TransitionSpec {
  index: number;
  type: string;
  duration_sec: number;
  hist_distance: number;
  gap_minutes: number | null;
  reason: string;
}

export interface MotionEvaluation {
  clips: MotionParams[];
  transitions: TransitionSpec[];
  total_duration_sec: number;
  sum_duration_sec: number;
  transition_saving_sec: number;
  clamp_counts: Record<string, number>;
  clamp_rate: number;
}

export interface TimelineItem extends MotionParams {
  filename: string;
  captured_at: string | null;
  poi_source: string;
}

export interface StageStatus {
  uploaded: number;
  committed: boolean;
  committed_count: number;
  stage2_unlocked: boolean;
  graded_dir: string;
}

export interface RenderProgress {
  job_id: string;
  phase: "queued" | "clips" | "concat" | "done" | "error";
  done: number;
  total: number;
  percent: number;
  message: string;
  error: string | null;
  elapsed_sec: number;
  ready: boolean;
}
