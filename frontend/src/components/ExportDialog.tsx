import { api } from "../api";
import { useStore } from "../store";
import { Button, Panel } from "./ui";

/**
 * 최종 산출물은 영상 파일이 아니라 **검증된 grade.yaml + motion.yaml**입니다.
 * 나중에 만들 배치 파이프라인이 이 두 파일만 읽어서 수백 장을 처리합니다.
 */
export function ExportDialog({ onClose }: { onClose: () => void }) {
  const { photos, motionEval, saveRules, busy } = useStore();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg">
        <Panel
          title="내보내기"
          right={
            <Button variant="ghost" onClick={onClose}>
              닫기
            </Button>
          }
        >
          <div className="space-y-3 text-xs">
            <p className="leading-relaxed text-slate-400">
              최종 산출물은 영상 하나가 아니라 <strong className="text-slate-200">검증된
              규칙 파일</strong>입니다. 배치 파이프라인이 이 두 파일만 읽어서 수백 장을
              자동 처리하게 됩니다.
            </p>

            <ul className="space-y-1.5 rounded bg-ink-900/60 p-3">
              {[
                ["grade.yaml", "1단계 화질 보정 규칙"],
                ["motion.yaml", "2단계 영상 효과 규칙"],
                ["build.sh", "UI에서 본 것과 동일한 mp4를 만드는 재현 스크립트"],
                ["stats.csv", `사진 ${photos.length}장의 측정값·적용값·클램프 히트`],
              ].map(([name, desc]) => (
                <li key={name} className="flex gap-2">
                  <code className="w-24 shrink-0 text-sky-300">{name}</code>
                  <span className="text-slate-500">{desc}</span>
                </li>
              ))}
            </ul>

            {motionEval && (
              <p className="text-slate-500">
                타임라인 {motionEval.clips.length}개 클립 ·{" "}
                {motionEval.total_duration_sec.toFixed(1)}초
              </p>
            )}

            <div className="flex flex-wrap gap-2 pt-1">
              <a
                href={api.exportUrl()}
                download="photo-video-tuner-export.zip"
                className="rounded border border-sky-500 bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500"
              >
                zip 내려받기
              </a>
              <Button onClick={() => void saveRules()} disabled={!!busy}>
                {busy ? "저장 중…" : "규칙을 저장소에 쓰기"}
              </Button>
            </div>
            <p className="text-[11px] text-slate-600">
              zip을 풀고 <code className="text-slate-400">./build.sh ./photos ./final.mp4</code>
              를 실행하면 같은 영상이 나옵니다.
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
