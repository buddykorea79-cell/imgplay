import { useStore } from "../../store";
import { ClampSummary, Panel, Select, Slider, Toggle } from "../ui";

export function MotionPanel() {
  const rules = useStore((s) => s.motionRules);
  const update = useStore((s) => s.updateMotionRules);
  const motionEval = useStore((s) => s.motionEval);
  if (!rules) return null;

  return (
    <div className="space-y-3">
      {motionEval && (
        <Panel title="규칙 적합도">
          <ClampSummary
            rate={motionEval.clamp_rate}
            counts={motionEval.clamp_counts}
            stage={2}
          />
        </Panel>
      )}

      <Panel title="출력">
        <Select
          label="해상도"
          value={`${rules.output.width}x${rules.output.height}`}
          options={[
            { value: "1920x1080", label: "1920 × 1080 (FHD)" },
            { value: "1280x720", label: "1280 × 720 (HD)" },
            { value: "3840x2160", label: "3840 × 2160 (4K)" },
            { value: "1080x1920", label: "1080 × 1920 (세로)" },
          ]}
          onChange={(v) => {
            const [width, height] = v.split("x").map(Number);
            update((r) => ({ ...r, output: { ...r.output, width, height } }));
          }}
        />
        <Slider
          label="fps"
          value={rules.output.fps}
          min={24}
          max={60}
          step={1}
          format={(v) => v.toFixed(0)}
          onChange={(v) => update((r) => ({ ...r, output: { ...r.output, fps: v } }))}
        />
        <Slider
          label="미리보기 높이"
          value={rules.output.preview_height}
          min={180}
          max={1080}
          step={90}
          format={(v) => `${v.toFixed(0)}p`}
          hint="낮출수록 클립 미리보기가 빨라집니다"
          onChange={(v) =>
            update((r) => ({ ...r, output: { ...r.output, preview_height: v } }))
          }
        />
      </Panel>

      <Panel title="지속시간">
        <Slider
          label="기본"
          value={rules.duration.base_sec}
          min={1}
          max={15}
          step={0.1}
          format={(v) => `${v.toFixed(1)}초`}
          hint="어지럽다면 zoom.amount보다 이 값을 먼저 늘려보세요"
          onChange={(v) =>
            update((r) => ({ ...r, duration: { ...r.duration, base_sec: v } }))
          }
        />
        <Slider
          label="최소"
          value={rules.duration.min_sec}
          min={0.5}
          max={10}
          step={0.1}
          format={(v) => `${v.toFixed(1)}초`}
          onChange={(v) => update((r) => ({ ...r, duration: { ...r.duration, min_sec: v } }))}
        />
        <Slider
          label="최대"
          value={rules.duration.max_sec}
          min={1}
          max={20}
          step={0.1}
          format={(v) => `${v.toFixed(1)}초`}
          onChange={(v) => update((r) => ({ ...r, duration: { ...r.duration, max_sec: v } }))}
        />
        <Slider
          label="복잡도 보너스"
          value={rules.duration.complexity_bonus}
          min={0}
          max={5}
          step={0.1}
          format={(v) => (v === 0 ? "비활성" : `+${v.toFixed(1)}초`)}
          hint="디테일이 많은 사진에 시간을 더 줍니다"
          onChange={(v) =>
            update((r) => ({ ...r, duration: { ...r.duration, complexity_bonus: v } }))
          }
        />
      </Panel>

      <Panel title="줌">
        <Toggle
          label="활성화"
          checked={rules.zoom.enabled}
          onChange={(v) => update((r) => ({ ...r, zoom: { ...r.zoom, enabled: v } }))}
        />
        <Slider
          label="줌량"
          value={rules.zoom.amount}
          min={0}
          max={0.6}
          step={0.01}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={(v) => update((r) => ({ ...r, zoom: { ...r.zoom, amount: v } }))}
        />
        <Slider
          label="hard_max"
          value={rules.zoom.hard_max}
          min={1}
          max={2}
          step={0.01}
          format={(v) => `${v.toFixed(2)}×`}
          onChange={(v) => update((r) => ({ ...r, zoom: { ...r.zoom, hard_max: v } }))}
        />
        <Slider
          label="안전 계수"
          value={rules.zoom.safety}
          min={0.5}
          max={1}
          step={0.01}
          hint="원본 해상도 여유 × 이 값 = 사진별 줌 상한"
          onChange={(v) => update((r) => ({ ...r, zoom: { ...r.zoom, safety: v } }))}
        />
        <Select
          label="방향"
          value={rules.zoom.direction}
          options={[
            { value: "auto", label: "auto — POI가 치우칠수록 줌인" },
            { value: "in", label: "in — 항상 줌인" },
            { value: "out", label: "out — 항상 줌아웃" },
            { value: "alternate", label: "alternate — 번갈아" },
          ]}
          onChange={(v) => update((r) => ({ ...r, zoom: { ...r.zoom, direction: v } }))}
        />
        <Select
          label="가속"
          value={rules.zoom.ease}
          options={[
            { value: "linear", label: "linear — 등속" },
            { value: "ease_in_out", label: "ease_in_out — 부드럽게" },
          ]}
          onChange={(v) => update((r) => ({ ...r, zoom: { ...r.zoom, ease: v } }))}
        />
      </Panel>

      <Panel title="팬">
        <Toggle
          label="활성화"
          checked={rules.pan.enabled}
          onChange={(v) => update((r) => ({ ...r, pan: { ...r.pan, enabled: v } }))}
        />
        <Toggle
          label="관심영역(POI)으로 수렴"
          checked={rules.pan.toward_poi}
          hint="얼굴 → 엣지 무게중심 순으로 목표점을 정합니다"
          onChange={(v) => update((r) => ({ ...r, pan: { ...r.pan, toward_poi: v } }))}
        />
        <Slider
          label="최대 이동"
          value={rules.pan.max_offset}
          min={0}
          max={0.5}
          step={0.01}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={(v) => update((r) => ({ ...r, pan: { ...r.pan, max_offset: v } }))}
        />
      </Panel>

      <Panel title="종횡비">
        <Select
          label="처리 방식"
          value={rules.aspect.mode}
          options={[
            { value: "blur_fill", label: "blur_fill — 블러 배경" },
            { value: "crop", label: "crop — 잘라내기" },
            { value: "pad", label: "pad — 레터박스" },
          ]}
          onChange={(v) => update((r) => ({ ...r, aspect: { ...r.aspect, mode: v } }))}
        />
        <Slider
          label="블러 강도"
          value={rules.aspect.blur_sigma}
          min={0}
          max={100}
          step={1}
          format={(v) => v.toFixed(0)}
          onChange={(v) => update((r) => ({ ...r, aspect: { ...r.aspect, blur_sigma: v } }))}
        />
        <Slider
          label="적용 임계값"
          value={rules.aspect.deviation_threshold}
          min={0}
          max={0.5}
          step={0.01}
          hint="출력 종횡비와 이만큼 차이나면 위 방식을 적용합니다"
          onChange={(v) =>
            update((r) => ({ ...r, aspect: { ...r.aspect, deviation_threshold: v } }))
          }
        />
      </Panel>

      <Panel title="전환">
        <Slider
          label="길이"
          value={rules.transition.duration_sec}
          min={0}
          max={3}
          step={0.05}
          format={(v) => `${v.toFixed(2)}초`}
          hint="전환마다 총 길이가 이만큼 짧아집니다"
          onChange={(v) =>
            update((r) => ({ ...r, transition: { ...r.transition, duration_sec: v } }))
          }
        />
        <Slider
          label="유사 임계값"
          value={rules.transition.similar_threshold}
          min={0}
          max={1}
          step={0.01}
          hint="히스토그램 거리가 이보다 작으면 유사"
          onChange={(v) =>
            update((r) => ({ ...r, transition: { ...r.transition, similar_threshold: v } }))
          }
        />
        <Slider
          label="상이 임계값"
          value={rules.transition.different_threshold}
          min={0}
          max={1}
          step={0.01}
          hint="이보다 크면 검정을 경유합니다"
          onChange={(v) =>
            update((r) => ({
              ...r,
              transition: { ...r.transition, different_threshold: v },
            }))
          }
        />
        <Slider
          label="장면 전환 간격"
          value={rules.transition.on_scene_gap_min}
          min={0}
          max={240}
          step={5}
          format={(v) => `${v.toFixed(0)}분`}
          hint="EXIF 촬영 간격이 이보다 크면 장면이 바뀐 것으로 봅니다"
          onChange={(v) =>
            update((r) => ({ ...r, transition: { ...r.transition, on_scene_gap_min: v } }))
          }
        />
        <Select
          label="기본 전환"
          value={rules.transition.default}
          options={[
            { value: "fade", label: "fade" },
            { value: "fadeblack", label: "fadeblack" },
            { value: "wipeleft", label: "wipeleft" },
            { value: "none", label: "none — 컷 (concat, 빠름)" },
          ]}
          onChange={(v) =>
            update((r) => ({ ...r, transition: { ...r.transition, default: v } }))
          }
        />
      </Panel>
    </div>
  );
}
