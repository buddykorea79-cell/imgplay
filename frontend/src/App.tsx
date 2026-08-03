import { useEffect, useState } from "react";
import { useStore } from "./store";
import { UploadZone } from "./components/UploadZone";
import { FilmStrip } from "./components/stage1/FilmStrip";
import { CompareView } from "./components/stage1/CompareView";
import { StatsPanel } from "./components/stage1/StatsPanel";
import { GradePanel } from "./components/stage1/GradePanel";
import { Timeline } from "./components/stage2/Timeline";
import { ClipPreview } from "./components/stage2/ClipPreview";
import { MotionPanel } from "./components/stage2/MotionPanel";
import { RenderDialog } from "./components/stage2/RenderDialog";
import { ExportDialog } from "./components/ExportDialog";
import { Button } from "./components/ui";

export default function App() {
  const {
    stage,
    goStage,
    committed,
    photos,
    error,
    clearError,
    init,
    commit,
    backToStage1,
    busy,
    reset,
  } = useStore();

  const [commitProgress, setCommitProgress] = useState<{ done: number; total: number } | null>(
    null,
  );
  const [showRender, setShowRender] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [clipId, setClipId] = useState<string | null>(null);
  const [transitionIndex, setTransitionIndex] = useState<number | null>(null);

  useEffect(() => {
    void init();
  }, [init]);

  const doCommit = async () => {
    setCommitProgress({ done: 0, total: photos.length });
    await commit((done, total) => setCommitProgress({ done, total }));
    setCommitProgress(null);
  };

  const doBack = async () => {
    const ok = window.confirm(
      "1단계로 돌아가면 확정된 보정 중간본(graded/)과 렌더된 클립(clips/)이 " +
        "삭제됩니다.\n측정 통계는 유지되므로 다시 측정하지는 않습니다.\n\n계속할까요?",
    );
    if (ok) await backToStage1();
  };

  return (
    <div className="flex h-screen flex-col bg-ink-900 text-slate-200">
      <header className="flex shrink-0 items-center gap-4 border-b border-ink-600 bg-ink-800 px-4 py-2">
        <h1 className="text-sm font-semibold">사진 → 영상 튜너</h1>

        <nav className="flex gap-1">
          <button
            type="button"
            onClick={() => goStage(1)}
            className={`rounded px-3 py-1 text-xs font-medium transition ${
              stage === 1 ? "bg-sky-600 text-white" : "text-slate-400 hover:bg-ink-700"
            }`}
          >
            1. 화질 보정
          </button>
          <button
            type="button"
            onClick={() => goStage(2)}
            disabled={!committed}
            title={committed ? undefined : "1단계 그레이딩을 먼저 확정하세요"}
            className={`rounded px-3 py-1 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
              stage === 2 ? "bg-sky-600 text-white" : "text-slate-400 hover:bg-ink-700"
            }`}
          >
            {committed ? "2. 영상 효과" : "🔒 2. 영상 효과"}
          </button>
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {busy && <span className="text-xs text-sky-300">{busy}…</span>}
          <span className="text-xs text-slate-500">{photos.length}장</span>
          {stage === 2 && (
            <>
              <Button onClick={() => setShowRender(true)}>전체 렌더</Button>
              <Button onClick={() => setShowExport(true)} variant="primary">
                내보내기
              </Button>
            </>
          )}
          {photos.length > 0 && (
            <Button
              variant="ghost"
              onClick={() => {
                if (window.confirm("업로드한 사진과 중간본을 모두 지웁니다. 계속할까요?"))
                  void reset();
              }}
            >
              초기화
            </Button>
          )}
        </div>
      </header>

      {error && (
        <div className="flex shrink-0 items-center gap-2 border-b border-red-900 bg-red-950/60 px-4 py-2 text-xs text-red-300">
          <span className="flex-1">{error}</span>
          <Button variant="ghost" onClick={clearError}>
            닫기
          </Button>
        </div>
      )}

      {photos.length === 0 ? (
        <main className="flex flex-1 items-center justify-center p-8">
          <div className="w-full max-w-xl space-y-4">
            <UploadZone />
            <p className="text-center text-xs leading-relaxed text-slate-600">
              화질과 모션은 판단 기준이 다릅니다. 화질은 정지 상태에서 픽셀을 봐야 하고,
              모션은 재생하면서 리듬을 봐야 합니다. 그래서 두 단계를 분리하고, 1단계를
              확정하기 전에는 2단계가 잠겨 있습니다.
            </p>
          </div>
        </main>
      ) : stage === 1 ? (
        <main className="flex min-h-0 flex-1">
          <aside className="w-72 shrink-0 overflow-y-auto border-r border-ink-600 p-3">
            <GradePanel />
          </aside>

          <section className="flex min-w-0 flex-1 flex-col gap-3 p-3">
            <div className="min-h-0 flex-1">
              <CompareView />
            </div>
            <FilmStrip />
            <div className="flex items-center gap-3 border-t border-ink-600 pt-3">
              <div className="w-64">
                <UploadZone compact />
              </div>
              <div className="flex-1" />
              {commitProgress ? (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-sky-300">
                    보정본 굽는 중 {commitProgress.done}/{commitProgress.total}
                  </span>
                  <div className="h-1.5 w-32 overflow-hidden rounded bg-ink-700">
                    <div
                      className="h-full bg-sky-500 transition-all"
                      style={{
                        width: `${(commitProgress.done / Math.max(commitProgress.total, 1)) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ) : (
                <>
                  <p className="max-w-md text-right text-[11px] leading-tight text-slate-500">
                    확정하면 원본 해상도 보정본을 PNG로 굽고 2단계가 열립니다.
                    <br />
                    무손실이라 2단계가 재인코딩 손실 없이 받습니다.
                  </p>
                  <Button variant="primary" onClick={() => void doCommit()} disabled={!!busy}>
                    그레이딩 확정 →
                  </Button>
                </>
              )}
            </div>
          </section>

          <aside className="w-72 shrink-0 overflow-y-auto border-l border-ink-600 p-3">
            <StatsPanel />
          </aside>
        </main>
      ) : (
        <main className="flex min-h-0 flex-1">
          <aside className="w-72 shrink-0 overflow-y-auto border-r border-ink-600 p-3">
            <MotionPanel />
          </aside>

          <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
            <Timeline
              selectedId={clipId}
              onSelect={(id) => {
                setClipId(id);
                setTransitionIndex(null);
              }}
              onPreviewTransition={(i) => {
                setTransitionIndex(i);
                setClipId(null);
              }}
            />
            <div className="flex items-center gap-3 border-t border-ink-600 pt-3">
              <Button variant="danger" onClick={() => void doBack()}>
                ← 1단계로 되돌아가기
              </Button>
              <p className="text-[11px] text-slate-600">
                되돌아가면 graded/와 clips/가 무효화됩니다 (통계는 유지)
              </p>
            </div>
          </section>

          <aside className="w-80 shrink-0 overflow-y-auto border-l border-ink-600 p-3">
            <ClipPreview clipId={clipId} transitionIndex={transitionIndex} />
          </aside>
        </main>
      )}

      {showRender && <RenderDialog onClose={() => setShowRender(false)} />}
      {showExport && <ExportDialog onClose={() => setShowExport(false)} />}
    </div>
  );
}
