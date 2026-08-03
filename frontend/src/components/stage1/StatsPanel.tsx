import { useSelectedParams, useSelectedPhoto, useStore } from "../../store";
import { ClampBadge, ClampSummary, GuardBadge, Panel, Stat } from "../ui";

function Histogram({ bins }: { bins: number[] }) {
  const max = Math.max(...bins, 1e-6);
  return (
    <div className="flex h-12 items-end gap-px" title="휘도 히스토그램 (32빈)">
      {bins.map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-sm bg-slate-500"
          style={{ height: `${Math.max((v / max) * 100, 2)}%` }}
        />
      ))}
    </div>
  );
}

export function StatsPanel() {
  const photo = useSelectedPhoto();
  const params = useSelectedParams();
  const gradeEval = useStore((s) => s.gradeEval);

  return (
    <div className="space-y-3">
      {gradeEval && (
        <Panel title="규칙 적합도">
          <ClampSummary
            rate={gradeEval.clamp_rate}
            counts={gradeEval.clamp_counts}
            stage={1}
          />
        </Panel>
      )}

      {photo && (
        <Panel title="측정값">
          <Histogram bins={photo.stats.hist_L} />
          <div className="mt-2">
            <Stat label="median_L" value={photo.stats.median_L.toFixed(1)} />
            <Stat
              label="spread_L"
              value={photo.stats.spread_L.toFixed(1)}
              unit={`(p05 ${photo.stats.p05_L.toFixed(0)} · p95 ${photo.stats.p95_L.toFixed(0)})`}
            />
            <Stat label="mean_sat" value={photo.stats.mean_sat.toFixed(3)} />
            <Stat
              label="sharpness"
              value={photo.stats.sharpness.toFixed(0)}
              unit="(1024px 정규화)"
            />
            <Stat label="clip_black" value={photo.stats.clip_black_pct.toFixed(2)} unit="%" />
            <Stat label="clip_white" value={photo.stats.clip_white_pct.toFixed(2)} unit="%" />
            <Stat
              label="wb_gains"
              value={`${photo.stats.wb_gains.r.toFixed(2)} / ${photo.stats.wb_gains.g.toFixed(2)} / ${photo.stats.wb_gains.b.toFixed(2)}`}
            />
            <Stat label="얼굴" value={photo.faces.length} unit="개" />
          </div>
        </Panel>
      )}

      {photo && (
        <Panel title="EXIF">
          <Stat label="ISO" value={photo.exif.iso ?? "—"} />
          <Stat
            label="셔터"
            value={
              photo.exif.exposure_time
                ? photo.exif.exposure_time >= 1
                  ? `${photo.exif.exposure_time.toFixed(1)}초`
                  : `1/${Math.round(1 / photo.exif.exposure_time)}초`
                : "—"
            }
          />
          <Stat label="조리개" value={photo.exif.f_number ? `f/${photo.exif.f_number}` : "—"} />
          <Stat
            label="촬영시각"
            value={photo.exif.datetime_original?.replace("T", " ") ?? "—"}
          />
          {!photo.exif.datetime_original && (
            <p className="pt-1 text-[11px] text-slate-500">
              촬영시각이 없어 2단계 정렬에서 뒤로 밀립니다
            </p>
          )}
        </Panel>
      )}

      {params && (
        <Panel
          title="적용 파라미터"
          right={
            <div className="flex gap-1">
              <GuardBadge items={params.guards_applied} />
              <ClampBadge items={params.clamped} />
            </div>
          }
        >
          <Stat label="gamma" value={params.gamma.toFixed(3)} />
          <Stat label="contrast" value={params.contrast.toFixed(3)} />
          <Stat label="saturation" value={params.saturation.toFixed(3)} />
          <Stat label="unsharp" value={params.unsharp.toFixed(3)} />
          <Stat
            label="whitebalance"
            value={
              params.wb_enabled
                ? `${params.wb.r.toFixed(3)} / ${params.wb.g.toFixed(3)} / ${params.wb.b.toFixed(3)}`
                : "꺼짐"
            }
          />
          {params.clamped.length > 0 && (
            <p className="pt-2 text-[11px] leading-snug text-clamp">
              클램프에 걸렸습니다 — 규칙이 이 사진을 감당하지 못한다는 뜻입니다.
            </p>
          )}
        </Panel>
      )}
    </div>
  );
}
