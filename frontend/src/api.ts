import type {
  GradeEvaluation,
  GradeRules,
  MotionEvaluation,
  MotionRules,
  Photo,
  RenderProgress,
  StageStatus,
  TimelineItem,
  TransitionSpec,
} from "./types";

/**
 * API 서버 주소.
 *
 * 로컬에서는 Vite 프록시(`/api` → localhost:8000)를 타므로 기본값이면 됩니다.
 * 백엔드를 다른 호스트에 띄운 경우(Vercel에 프론트만 올린 경우 등)에는 빌드
 * 시점에 `VITE_API_BASE`로 절대 주소를 넘기세요:
 *
 *     VITE_API_BASE=https://tuner-api.example.com/api
 *
 * `vercel.json`의 rewrite로는 처리할 수 없습니다 — Vercel은 rewrite 목적지에
 * 환경변수를 넣는 것을 지원하지 않고, 프록시를 거치면 클립 mp4 스트리밍이
 * 응답 크기 제한에 걸립니다. 브라우저가 백엔드로 직접 붙는 편이 낫습니다.
 */
const BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/+$/, "");

/** 백엔드가 이 앱과 다른 출처에 있는가 (안내 문구 분기용). */
export const isRemoteBackend = /^https?:\/\//i.test(BASE);
export const apiBase = BASE;

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** 409는 "1단계가 아직 확정되지 않음"입니다. 오류가 아니라 잠금 상태입니다. */
  get isLocked() {
    return this.status === 409;
  }
}

export const api = {
  health: () => json<{ ok: boolean; ffmpeg: string; face_model: boolean }>("/health"),

  // ------------------------------------------------------------ 규칙
  getGradeRules: () => json<GradeRules>("/rules/grade"),
  getMotionRules: () => json<MotionRules>("/rules/motion"),
  putGradeRules: (rules: GradeRules) =>
    json<GradeRules>("/rules/grade", { method: "PUT", body: JSON.stringify(rules) }),
  putMotionRules: (rules: MotionRules) =>
    json<MotionRules>("/rules/motion", { method: "PUT", body: JSON.stringify(rules) }),

  // ------------------------------------------------------------ 1단계
  async uploadPhotos(files: File[]): Promise<Photo[]> {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const res = await fetch(`${BASE}/photos`, { method: "POST", body: form });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    const data = (await res.json()) as (Photo | { _errors: unknown[] })[];
    return data.filter((d): d is Photo => "id" in d);
  },

  listPhotos: () => json<Photo[]>("/photos"),
  resetPhotos: () => json<{ ok: boolean }>("/photos", { method: "DELETE" }),

  evaluateGrade: (rules: GradeRules) =>
    json<GradeEvaluation>("/grade/evaluate", {
      method: "POST",
      body: JSON.stringify({ rules }),
    }),

  gradeStatus: () => json<StageStatus>("/grade/status"),
  uncommit: () => json<{ ok: boolean }>("/grade/uncommit", { method: "POST" }),

  /** 조정 중인 규칙을 그대로 적용한 미리보기 URL이 아니라, 실제 blob을 받습니다. */
  async previewBlob(
    id: string,
    rules: GradeRules,
    mode: "fit" | "crop",
    opts: { longEdge?: number; cropSize?: number } = {},
  ): Promise<string> {
    const q = new URLSearchParams({ mode });
    if (opts.longEdge) q.set("long_edge", String(opts.longEdge));
    if (opts.cropSize) q.set("crop_size", String(opts.cropSize));
    const res = await fetch(`${BASE}/grade/preview/${id}?${q}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules }),
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return URL.createObjectURL(await res.blob());
  },

  originalUrl(
    id: string,
    mode: "fit" | "crop",
    opts: { longEdge?: number; cropSize?: number } = {},
  ): string {
    const q = new URLSearchParams({ mode });
    if (opts.longEdge) q.set("long_edge", String(opts.longEdge));
    if (opts.cropSize) q.set("crop_size", String(opts.cropSize));
    return `${BASE}/grade/original/${id}?${q}`;
  },

  /** 확정. SSE로 진행률이 흘러옵니다. */
  async commit(
    rules: GradeRules,
    onProgress: (p: { done: number; total: number; filename?: string }) => void,
  ): Promise<void> {
    const res = await fetch(`${BASE}/grade/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules }),
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    for await (const evt of readSse(res)) {
      if (evt.error) throw new Error(String(evt.error));
      onProgress(evt as { done: number; total: number; filename?: string });
    }
  },

  // ------------------------------------------------------------ 2단계
  timeline: () =>
    json<{
      order: string[];
      items: TimelineItem[];
      transitions: TransitionSpec[];
      total_duration_sec: number;
      sum_duration_sec: number;
      transition_saving_sec: number;
      clamp_counts: Record<string, number>;
      clamp_rate: number;
    }>("/timeline"),

  putOrder: (order: string[]) =>
    json<{ order: string[] }>("/timeline/order", {
      method: "PUT",
      body: JSON.stringify({ order }),
    }),

  sortByCaptureTime: () =>
    json<{ order: string[] }>("/timeline/sort", { method: "POST" }),

  evaluateMotion: (rules: MotionRules, order?: string[]) =>
    json<MotionEvaluation>("/motion/evaluate", {
      method: "POST",
      body: JSON.stringify({ rules, order }),
    }),

  async clipPreview(id: string, rules: MotionRules, order?: string[]): Promise<string> {
    const res = await fetch(`${BASE}/motion/clip/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules, order }),
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return URL.createObjectURL(await res.blob());
  },

  async transitionPreview(
    index: number,
    rules: MotionRules,
    order?: string[],
  ): Promise<string> {
    const res = await fetch(`${BASE}/motion/transition/${index}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules, order }),
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    return URL.createObjectURL(await res.blob());
  },

  /**
   * `single_pass`면 중간본 없이 원본에서 직접 렌더하므로 보정 필터를 함께
   * 걸어야 합니다 — `grade_rules`를 빠뜨리면 무보정 영상이 나옵니다.
   */
  startRender: (
    motion_rules: MotionRules,
    opts: { order?: string[]; single_pass?: boolean; grade_rules?: GradeRules } = {},
  ) =>
    json<{ job_id: string }>("/render", {
      method: "POST",
      body: JSON.stringify({ motion_rules, ...opts }),
    }),

  async watchRender(
    jobId: string,
    onProgress: (p: RenderProgress) => void,
  ): Promise<RenderProgress> {
    const res = await fetch(`${BASE}/render/${jobId}`);
    if (!res.ok) throw new ApiError(res.status, await res.text());
    let last: RenderProgress | null = null;
    for await (const evt of readSse(res)) {
      last = evt as unknown as RenderProgress;
      onProgress(last);
    }
    if (!last) throw new Error("렌더 진행률을 받지 못했습니다");
    return last;
  },

  renderFileUrl: (jobId: string) => `${BASE}/render/${jobId}/file`,
  exportUrl: () => `${BASE}/export`,
};

/** SSE 스트림을 파싱한다. EventSource는 POST를 못 하므로 직접 읽습니다. */
async function* readSse(res: Response): AsyncGenerator<Record<string, unknown>> {
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        yield JSON.parse(line.slice(5).trim());
      } catch {
        // 부분 수신된 프레임은 건너뛴다
      }
    }
  }
}
