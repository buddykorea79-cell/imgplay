import { useState } from "react";
import { api } from "../../api";
import { useStore } from "../../store";
import { Button, Panel, Toggle } from "../ui";
import type { RenderProgress } from "../../types";

export function RenderDialog({ onClose }: { onClose: () => void }) {
  const { motionRules, gradeRules, order, motionEval } = useStore();
  const [progress, setProgress] = useState<RenderProgress | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [singlePass, setSinglePass] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const running = progress !== null && !progress.ready && progress.phase !== "error";

  const start = async () => {
    if (!motionRules) return;
    setError(null);
    setProgress(null);
    try {
      const { job_id } = await api.startRender(motionRules, {
        order: order.length ? order : undefined,
        single_pass: singlePass,
        // 단일 패스는 중간본을 안 쓰므로 보정을 여기서 같이 걸어야 한다.
        grade_rules: singlePass ? (gradeRules ?? undefined) : undefined,
      });
      setJobId(job_id);
      const final = await api.watchRender(job_id, setProgress);
      if (final.phase === "error") setError(final.error ?? "렌더 실패");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg space-y-3">
        <Panel
          title="전체 렌더"
          right={
            <Button variant="ghost" onClick={onClose} disabled={running}>
              닫기
            </Button>
          }
        >
          <div className="space-y-3">
            <div className="rounded bg-ink-900/60 p-3 text-xs">
              <p className="text-slate-300">
                {motionEval?.clips.length ?? 0}개 클립 ·{" "}
                {(motionEval?.total_duration_sec ?? 0).toFixed(1)}초 ·{" "}
                {motionRules?.output.width}×{motionRules?.output.height} @{" "}
                {motionRules?.output.fps}fps
              </p>
              <p className="mt-1 text-slate-600">
                클립은 개별 렌더 후 결합됩니다. 이미 렌더된 클립은 캐시에서 재사용됩니다.
              </p>
            </div>

            <Toggle
              label="중간본 없이 원본에서 단일 패스"
              checked={singlePass}
              hint="디스크를 아낍니다. 결과는 동일합니다."
              onChange={setSinglePass}
            />

            {progress && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">
                    {
                      {
                        queued: "대기 중",
                        clips: "클립 렌더 중",
                        concat: "전환 결합 중",
                        done: "완료",
                        error: "실패",
                      }[progress.phase]
                    }
                    {progress.message && (
                      <span className="ml-2 text-slate-500">{progress.message}</span>
                    )}
                  </span>
                  <span className="font-mono tabular-nums text-slate-400">
                    {progress.done}/{progress.total} · {progress.elapsed_sec.toFixed(0)}초
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-ink-700">
                  <div
                    className={`h-full transition-all ${
                      progress.phase === "error" ? "bg-red-500" : "bg-sky-500"
                    }`}
                    style={{ width: `${progress.percent}%` }}
                  />
                </div>
              </div>
            )}

            {error && (
              <p className="rounded bg-red-950/60 p-2 text-xs text-red-300">{error}</p>
            )}

            <div className="flex gap-2">
              <Button variant="primary" onClick={() => void start()} disabled={running}>
                {running ? "렌더 중…" : progress?.ready ? "다시 렌더" : "렌더 시작"}
              </Button>
              {progress?.ready && jobId && (
                <a
                  href={api.renderFileUrl(jobId)}
                  download="final.mp4"
                  className="rounded border border-emerald-500 bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500"
                >
                  mp4 내려받기
                </a>
              )}
            </div>

            {progress?.ready && jobId && (
              <video
                src={api.renderFileUrl(jobId)}
                controls
                className="w-full rounded bg-ink-900"
              />
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
