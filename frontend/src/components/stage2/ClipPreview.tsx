import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useStore } from "../../store";
import { ClampBadge, Panel, Stat } from "../ui";

/**
 * 단일 클립 / 전환 미리보기.
 *
 * 미리보기도 **반드시 ffmpeg로** 만듭니다. CSS transform으로 흉내내면 실제
 * 렌더와 달라지고, 눈으로 맞춘 값이 최종 영상에서 재현되지 않습니다.
 */
export function ClipPreview({
  clipId,
  transitionIndex,
}: {
  clipId: string | null;
  transitionIndex: number | null;
}) {
  const { motionRules, order, motionEval, timeline } = useStore();
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!motionRules) return;
    if (clipId === null && transitionIndex === null) return;

    let cancelled = false;
    let created: string | null = null;
    setLoading(true);
    setError(null);
    const t0 = performance.now();

    const request =
      transitionIndex !== null
        ? api.transitionPreview(transitionIndex, motionRules, order.length ? order : undefined)
        : api.clipPreview(clipId!, motionRules, order.length ? order : undefined);

    request
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        created = u;
        setElapsed((performance.now() - t0) / 1000);
        setUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return u;
        });
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [clipId, transitionIndex, motionRules, order]);

  const clip = motionEval?.clips.find((c) => c.id === clipId);
  const item = timeline.find((t) => t.id === clipId);
  const transition =
    transitionIndex !== null ? motionEval?.transitions[transitionIndex] : null;

  return (
    <div className="space-y-3">
      <Panel
        title={transitionIndex !== null ? `전환 ${transitionIndex + 1} 미리보기` : "클립 미리보기"}
        right={
          elapsed !== null && !loading ? (
            <span className="font-mono text-[10px] text-slate-500">
              {elapsed.toFixed(1)}초 만에 렌더
            </span>
          ) : null
        }
      >
        <div className="relative aspect-video overflow-hidden rounded bg-ink-900">
          {url && (
            <video
              ref={videoRef}
              src={url}
              controls
              autoPlay
              loop
              muted
              playsInline
              className="h-full w-full"
            />
          )}
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-ink-900/70 text-xs text-sky-300">
              ffmpeg 렌더 중…
            </div>
          )}
          {!url && !loading && !error && (
            <div className="absolute inset-0 flex items-center justify-center text-xs text-slate-600">
              타임라인에서 클립이나 전환을 선택하세요
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center p-3 text-center text-xs text-red-400">
              {error.slice(0, 300)}
            </div>
          )}
        </div>
      </Panel>

      {transition && (
        <Panel title="전환 판단 근거">
          <Stat label="방식" value={transition.type} />
          <Stat label="길이" value={transition.duration_sec.toFixed(2)} unit="초" />
          <Stat label="히스토그램 거리" value={transition.hist_distance.toFixed(3)} />
          <Stat
            label="촬영 간격"
            value={transition.gap_minutes !== null ? transition.gap_minutes.toFixed(0) : "—"}
            unit={transition.gap_minutes !== null ? "분" : undefined}
          />
          <p className="pt-2 text-[11px] text-slate-500">{transition.reason}</p>
        </Panel>
      )}

      {clip && (
        <Panel
          title="클립 파라미터"
          right={<ClampBadge items={clip.clamped} />}
        >
          <Stat label="지속시간" value={clip.duration_sec.toFixed(2)} unit="초" />
          <Stat
            label="줌"
            value={`${clip.zoom_start.toFixed(3)} → ${clip.zoom_end.toFixed(3)}`}
          />
          <Stat label="안전 줌 상한" value={clip.max_zoom.toFixed(3)} />
          <Stat label="팬 dx, dy" value={`${clip.dx.toFixed(4)}, ${clip.dy.toFixed(4)}`} />
          <Stat
            label="POI"
            value={`${clip.poi_x.toFixed(3)}, ${clip.poi_y.toFixed(3)}`}
            unit={item?.poi_source ? `(${item.poi_source})` : undefined}
          />
          <Stat label="종횡비 편차" value={clip.aspect_dev.toFixed(3)} />
          <Stat label="종횡비 처리" value={clip.aspect_mode} />

          {clip.clamped.includes("max_zoom") && (
            <p className="pt-2 text-[11px] leading-snug text-clamp">
              원본 해상도가 요청한 줌량을 감당하지 못합니다. 출력을 낮추거나
              zoom.amount를 줄이세요.
            </p>
          )}
          {item && (
            <div className="mt-2 border-t border-ink-700 pt-2">
              <p className="truncate text-[11px] text-slate-400">{item.filename}</p>
              {item.captured_at && (
                <p className="font-mono text-[10px] text-slate-600">
                  {item.captured_at.replace("T", " ")}
                </p>
              )}
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
