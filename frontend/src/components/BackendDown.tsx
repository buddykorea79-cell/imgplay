import { apiBase, isRemoteBackend } from "../api";
import { Button } from "./ui";
import { useStore } from "../store";

/**
 * 백엔드에 닿지 못할 때 보여주는 화면.
 *
 * 이 앱은 UI만으로는 아무것도 못 합니다 — 측정도 미리보기도 렌더도 전부
 * 파이썬 + ffmpeg 쪽에서 일어납니다. 정적 호스팅(Vercel 등)에는 프론트만
 * 올라가므로, 왜 비어 보이는지와 무엇을 해야 하는지를 분명히 알려줍니다.
 */
export function BackendDown() {
  const init = useStore((s) => s.init);

  return (
    <main className="flex flex-1 items-center justify-center overflow-y-auto p-6">
      <div className="w-full max-w-2xl space-y-4">
        <div className="rounded-lg border border-clamp/40 bg-clamp/10 p-4">
          <h2 className="text-sm font-semibold text-clamp">백엔드에 연결할 수 없습니다</h2>
          <p className="mt-1 text-xs leading-relaxed text-slate-300">
            지금 보고 계신 화면은 UI뿐입니다. 사진 측정·보정 미리보기·영상 렌더는
            모두 파이썬 백엔드와 <code className="text-slate-200">ffmpeg</code>가
            처리하므로, 백엔드가 떠 있어야 동작합니다.
          </p>
          <p className="mt-2 font-mono text-[11px] text-slate-500">
            요청 대상: {apiBase}
            {!isRemoteBackend && " (같은 출처)"}
          </p>
        </div>

        <section className="space-y-3 rounded-lg border border-ink-600 bg-ink-800/60 p-4 text-xs">
          <h3 className="font-semibold text-slate-300">해결 방법</h3>

          <div>
            <p className="text-slate-400">1. 로컬에서 전부 실행 (가장 간단)</p>
            <pre className="mt-1 overflow-x-auto rounded bg-ink-900 p-2 font-mono text-[11px] text-sky-300">
              docker compose up
            </pre>
            <p className="mt-1 text-slate-600">
              ffmpeg가 포함된 이미지가 뜨고 http://localhost:8000 에서 UI까지 함께
              제공됩니다.
            </p>
          </div>

          <div>
            <p className="text-slate-400">2. 백엔드를 별도 호스트에 배포</p>
            <p className="mt-1 leading-relaxed text-slate-600">
              이 저장소의 <code className="text-slate-400">Dockerfile</code>을 그대로
              쓸 수 있는 곳(Fly.io·Railway·Render 등)에 올린 뒤, 이 프론트엔드를
              빌드할 때 <code className="text-slate-400">VITE_API_BASE</code>에 그
              주소를 넣으세요. 백엔드에는{" "}
              <code className="text-slate-400">PVT_CORS_ORIGINS</code>로 이 페이지의
              주소를 허용해 줘야 합니다.
            </p>
            <pre className="mt-1 overflow-x-auto rounded bg-ink-900 p-2 font-mono text-[11px] text-sky-300">
              {`VITE_API_BASE=https://내-백엔드/api\nPVT_CORS_ORIGINS=https://내-프론트.vercel.app`}
            </pre>
          </div>

          <p className="border-t border-ink-700 pt-3 leading-relaxed text-slate-600">
            Vercel 같은 서버리스 플랫폼에는 백엔드를 올릴 수 없습니다. ffmpeg
            시스템 바이너리가 없고, 파일시스템이 읽기 전용이며(중간본·클립 캐시가
            남지 않습니다), 실행 시간 제한이 있어 렌더가 중간에 끊깁니다.
          </p>
        </section>

        <div className="flex justify-center">
          <Button variant="primary" onClick={() => void init()}>
            다시 연결 시도
          </Button>
        </div>
      </div>
    </main>
  );
}
