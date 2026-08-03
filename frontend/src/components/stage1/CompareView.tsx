import { useEffect, useState } from "react";
import { api } from "../../api";
import { useSelectedPhoto, useStore } from "../../store";
import { Button } from "../ui";

/**
 * 원본 ↔ 보정본 비교.
 *
 * 두 이미지 모두 ffmpeg가 **같은 스케일로** 렌더합니다. 프론트에서 CSS 필터로
 * 흉내내면 실제 렌더와 미묘하게 달라지고, 눈으로 튜닝한 값이 재현되지 않으면
 * 이 도구는 존재 이유를 잃습니다.
 */
export function CompareView() {
  const photo = useSelectedPhoto();
  const { gradeRules, compareMode, setCompareMode } = useStore();
  const [gradedUrl, setGradedUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [split, setSplit] = useState(50);

  useEffect(() => {
    if (!photo || !gradeRules) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setLoading(true);

    // 슬라이더를 계속 만지는 동안 요청이 쌓이지 않도록 살짝 미룬다.
    const timer = setTimeout(() => {
      api
        .previewBlob(photo.id, gradeRules, compareMode, {
          longEdge: 1280,
          cropSize: 900,
        })
        .then((url) => {
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          objectUrl = url;
          setGradedUrl((old) => {
            if (old) URL.revokeObjectURL(old);
            return url;
          });
        })
        .catch(() => undefined)
        .finally(() => !cancelled && setLoading(false));
    }, 200);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [photo, gradeRules, compareMode]);

  if (!photo) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        사진을 선택하세요
      </div>
    );
  }

  const originalUrl = api.originalUrl(photo.id, compareMode, {
    longEdge: 1280,
    cropSize: 900,
  });

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1">
          <Button
            variant={compareMode === "fit" ? "primary" : "default"}
            onClick={() => setCompareMode("fit")}
            title="전체 구도 확인"
          >
            전체
          </Button>
          <Button
            variant={compareMode === "crop" ? "primary" : "default"}
            onClick={() => setCompareMode("crop")}
            title="100% 크롭 — 언샤프 과다를 여기서 판단하세요"
          >
            100% 크롭
          </Button>
        </div>
        <span className="truncate font-mono text-[11px] text-slate-500">
          {photo.filename} · {photo.width}×{photo.height}
          {loading && <span className="ml-2 text-sky-400">렌더 중…</span>}
        </span>
      </div>

      <div className="relative flex-1 select-none overflow-hidden rounded-lg bg-ink-900">
        <img
          src={originalUrl}
          alt="원본"
          className="absolute inset-0 h-full w-full object-contain"
        />
        {gradedUrl && (
          <div
            className="absolute inset-0 overflow-hidden"
            style={{ clipPath: `inset(0 0 0 ${split}%)` }}
          >
            <img
              src={gradedUrl}
              alt="보정본"
              className="absolute inset-0 h-full w-full object-contain"
            />
          </div>
        )}

        <div
          className="pointer-events-none absolute inset-y-0 w-px bg-sky-400"
          style={{ left: `${split}%` }}
        />
        <input
          type="range"
          min={0}
          max={100}
          value={split}
          onChange={(e) => setSplit(Number(e.target.value))}
          aria-label="비교 슬라이더"
          className="absolute inset-x-0 bottom-0 w-full cursor-ew-resize opacity-0"
          style={{ height: "100%" }}
        />

        <span className="pointer-events-none absolute left-2 top-2 rounded bg-ink-900/80 px-1.5 py-0.5 text-[10px] text-slate-400">
          원본
        </span>
        <span className="pointer-events-none absolute right-2 top-2 rounded bg-ink-900/80 px-1.5 py-0.5 text-[10px] text-sky-300">
          보정본
        </span>
      </div>
      <p className="text-center text-[11px] text-slate-600">
        좌우로 드래그해 비교 · 100% 크롭에서 언샤프 과다를 판단하세요
      </p>
    </div>
  );
}
