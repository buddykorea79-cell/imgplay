import { create } from "zustand";
import { api, ApiError } from "./api";
import type {
  GradeEvaluation,
  GradeRules,
  MotionEvaluation,
  MotionRules,
  Photo,
  TimelineItem,
  TransitionSpec,
} from "./types";

/** 슬라이더 onChange마다 서버를 때리면 안 됩니다. 150ms 디바운스. */
function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  let t: ReturnType<typeof setTimeout> | undefined;
  return (...a: A) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

interface State {
  // 공통
  stage: 1 | 2;
  committed: boolean;
  busy: string | null;
  error: string | null;
  /** 백엔드에 닿지 못함. 정적 호스팅에만 올린 경우가 대부분입니다. */
  backendDown: boolean;
  ready: boolean;

  // 1단계
  photos: Photo[];
  selectedId: string | null;
  gradeRules: GradeRules | null;
  gradeEval: GradeEvaluation | null;
  compareMode: "fit" | "crop";

  // 2단계
  motionRules: MotionRules | null;
  motionEval: MotionEvaluation | null;
  timeline: TimelineItem[];
  transitions: TransitionSpec[];
  order: string[];

  // 액션
  init: () => Promise<void>;
  addFiles: (files: File[]) => Promise<void>;
  select: (id: string | null) => void;
  setCompareMode: (m: "fit" | "crop") => void;
  updateGradeRules: (patch: (r: GradeRules) => GradeRules) => void;
  commit: (onProgress: (done: number, total: number, name?: string) => void) => Promise<void>;
  backToStage1: () => Promise<void>;
  goStage: (s: 1 | 2) => void;
  updateMotionRules: (patch: (r: MotionRules) => MotionRules) => void;
  reorder: (order: string[]) => Promise<void>;
  sortByTime: () => Promise<void>;
  saveRules: () => Promise<void>;
  reset: () => Promise<void>;
  clearError: () => void;
}

export const useStore = create<State>((set, get) => {
  const evaluateGrade = debounce(async (rules: GradeRules) => {
    try {
      set({ gradeEval: await api.evaluateGrade(rules) });
    } catch (e) {
      set({ error: describe(e) });
    }
  }, 150);

  const evaluateMotion = debounce(async (rules: MotionRules, order: string[]) => {
    try {
      const motionEval = await api.evaluateMotion(rules, order.length ? order : undefined);
      set({ motionEval });
    } catch (e) {
      if (!(e instanceof ApiError && e.isLocked)) set({ error: describe(e) });
    }
  }, 150);

  return {
    stage: 1,
    committed: false,
    busy: null,
    error: null,
    backendDown: false,
    ready: false,
    photos: [],
    selectedId: null,
    gradeRules: null,
    gradeEval: null,
    compareMode: "fit",
    motionRules: null,
    motionEval: null,
    timeline: [],
    transitions: [],
    order: [],

    async init() {
      set({ busy: "불러오는 중" });
      try {
        // 규칙·사진을 부르기 전에 백엔드 존재부터 확인합니다. 여기서 실패하면
        // 나머지 요청이 전부 같은 이유로 깨지므로, 오류를 네 번 띄우는 대신
        // "백엔드에 못 닿음" 한 가지 상태로 정리합니다.
        await api.health();
      } catch {
        set({ backendDown: true, busy: null, ready: true });
        return;
      }
      try {
        const [gradeRules, motionRules, photos, status] = await Promise.all([
          api.getGradeRules(),
          api.getMotionRules(),
          api.listPhotos(),
          api.gradeStatus(),
        ]);
        set({
          gradeRules,
          motionRules,
          photos,
          committed: status.stage2_unlocked,
          selectedId: photos[0]?.id ?? null,
          order: photos.map((p) => p.id),
        });
        if (photos.length) evaluateGrade(gradeRules);
        if (status.stage2_unlocked) await refreshTimeline(set, get);
        set({ backendDown: false });
      } catch (e) {
        set({ error: describe(e) });
      } finally {
        set({ busy: null, ready: true });
      }
    },

    async addFiles(files) {
      if (!files.length) return;
      set({ busy: `${files.length}장 측정 중`, error: null });
      try {
        await api.uploadPhotos(files);
        const photos = await api.listPhotos();
        set({
          photos,
          order: photos.map((p) => p.id),
          selectedId: get().selectedId ?? photos[0]?.id ?? null,
        });
        const rules = get().gradeRules;
        if (rules) evaluateGrade(rules);
      } catch (e) {
        set({ error: describe(e) });
      } finally {
        set({ busy: null });
      }
    },

    select: (selectedId) => set({ selectedId }),
    setCompareMode: (compareMode) => set({ compareMode }),

    updateGradeRules(patch) {
      const current = get().gradeRules;
      if (!current) return;
      const gradeRules = patch(structuredClone(current));
      set({ gradeRules });
      evaluateGrade(gradeRules); // 재측정 없이 파라미터만 다시 계산 (수 ms)
    },

    async commit(onProgress) {
      const rules = get().gradeRules;
      if (!rules) return;
      set({ busy: "확정 중", error: null });
      try {
        await api.putGradeRules(rules); // 확정한 규칙을 디스크에 남긴다
        await api.commit(rules, (p) => onProgress(p.done, p.total, p.filename));
        set({ committed: true, stage: 2 });
        await refreshTimeline(set, get);
      } catch (e) {
        set({ error: describe(e) });
      } finally {
        set({ busy: null });
      }
    },

    async backToStage1() {
      set({ busy: "중간본 정리 중" });
      try {
        await api.uncommit();
        set({
          committed: false,
          stage: 1,
          motionEval: null,
          timeline: [],
          transitions: [],
        });
      } catch (e) {
        set({ error: describe(e) });
      } finally {
        set({ busy: null });
      }
    },

    goStage(stage) {
      if (stage === 2 && !get().committed) return; // 확정 전에는 잠겨 있다
      set({ stage });
    },

    updateMotionRules(patch) {
      const current = get().motionRules;
      if (!current) return;
      const motionRules = patch(structuredClone(current));
      set({ motionRules });
      evaluateMotion(motionRules, get().order);
    },

    async reorder(order) {
      set({ order });
      try {
        await api.putOrder(order);
        await refreshTimeline(set, get);
      } catch (e) {
        set({ error: describe(e) });
      }
    },

    async sortByTime() {
      try {
        const { order } = await api.sortByCaptureTime();
        set({ order });
        await refreshTimeline(set, get);
      } catch (e) {
        set({ error: describe(e) });
      }
    },

    async saveRules() {
      const { gradeRules, motionRules } = get();
      set({ busy: "규칙 저장 중" });
      try {
        if (gradeRules) await api.putGradeRules(gradeRules);
        if (motionRules) await api.putMotionRules(motionRules);
      } catch (e) {
        set({ error: describe(e) });
      } finally {
        set({ busy: null });
      }
    },

    async reset() {
      set({ busy: "초기화 중" });
      try {
        await api.resetPhotos();
        set({
          photos: [],
          order: [],
          selectedId: null,
          committed: false,
          stage: 1,
          gradeEval: null,
          motionEval: null,
          timeline: [],
          transitions: [],
        });
      } catch (e) {
        set({ error: describe(e) });
      } finally {
        set({ busy: null });
      }
    },

    clearError: () => set({ error: null }),
  };
});

async function refreshTimeline(
  set: (partial: Partial<State>) => void,
  get: () => State,
) {
  try {
    const tl = await api.timeline();
    set({
      timeline: tl.items,
      transitions: tl.transitions,
      order: tl.order,
      motionEval: {
        clips: tl.items,
        transitions: tl.transitions,
        total_duration_sec: tl.total_duration_sec,
        sum_duration_sec: tl.sum_duration_sec,
        transition_saving_sec: tl.transition_saving_sec,
        clamp_counts: tl.clamp_counts,
        clamp_rate: tl.clamp_rate,
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError && e.isLocked)) set({ error: describe(e) });
  }
  void get;
}

function describe(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const parsed = JSON.parse(e.message) as { detail?: unknown };
      if (parsed.detail) return String(parsed.detail);
    } catch {
      /* 평문 응답 */
    }
    return `${e.status}: ${e.message.slice(0, 300)}`;
  }
  return e instanceof Error ? e.message : String(e);
}

/** 선택된 사진의 보정 파라미터. 여러 패널이 공유합니다. */
export function useSelectedParams() {
  const { selectedId, gradeEval } = useStore();
  if (!selectedId || !gradeEval) return null;
  return gradeEval.params.find((p) => p.id === selectedId) ?? null;
}

export function useSelectedPhoto() {
  const { selectedId, photos } = useStore();
  return photos.find((p) => p.id === selectedId) ?? null;
}
