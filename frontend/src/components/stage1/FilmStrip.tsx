import { useStore } from "../../store";
import { api } from "../../api";

/** 썸네일 목록. 클램프에 걸린 사진을 한눈에 찾는 것이 목적입니다. */
export function FilmStrip() {
  const { photos, selectedId, select, gradeEval } = useStore();
  const byId = new Map(gradeEval?.params.map((p) => [p.id, p]) ?? []);

  if (!photos.length) return null;

  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {photos.map((p) => {
        const params = byId.get(p.id);
        const hit = (params?.clamped.length ?? 0) > 0;
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => select(p.id)}
            title={`${p.filename}\n${p.width}×${p.height}${
              params?.clamped.length ? `\n클램프: ${params.clamped.join(", ")}` : ""
            }`}
            className={`relative shrink-0 overflow-hidden rounded border-2 transition ${
              selectedId === p.id
                ? "border-sky-400"
                : hit
                  ? "border-clamp/50 hover:border-clamp"
                  : "border-ink-600 hover:border-ink-600/60"
            }`}
          >
            <img
              src={api.originalUrl(p.id, "fit", { longEdge: 160 })}
              alt={p.filename}
              loading="lazy"
              className="h-20 w-28 bg-ink-900 object-contain"
            />
            {hit && (
              <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-clamp ring-2 ring-ink-900" />
            )}
            {params?.guards_applied.length ? (
              <span className="absolute left-1 top-1 h-2 w-2 rounded-full bg-sky-400 ring-2 ring-ink-900" />
            ) : null}
            <span className="block truncate bg-ink-900/90 px-1 py-0.5 text-[10px] text-slate-400">
              {p.filename}
            </span>
          </button>
        );
      })}
    </div>
  );
}
