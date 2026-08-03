import { useStore } from "../../store";
import { Panel, Slider, Toggle } from "../ui";

/**
 * 1단계 규칙 슬라이더.
 *
 * 조작해도 **재측정은 일어나지 않습니다** — 통계는 이미 있고, 파라미터만 다시
 * 계산합니다(200장에 수십 ms). 그래서 클램프 카운터가 즉시 반응합니다.
 */
export function GradePanel() {
  const rules = useStore((s) => s.gradeRules);
  const update = useStore((s) => s.updateGradeRules);
  if (!rules) return null;

  return (
    <div className="space-y-3">
      <Panel title="목표값">
        <Slider
          label="median_L"
          value={rules.target.median_L}
          min={20}
          max={80}
          step={0.5}
          format={(v) => v.toFixed(1)}
          hint="보정 후 도달하려는 중앙 밝기"
          onChange={(v) => update((r) => ({ ...r, target: { ...r.target, median_L: v } }))}
        />
        <Slider
          label="spread_L"
          value={rules.target.spread_L}
          min={20}
          max={90}
          step={0.5}
          format={(v) => v.toFixed(1)}
          hint="p95 - p05. 목표 대비 폭"
          onChange={(v) => update((r) => ({ ...r, target: { ...r.target, spread_L: v } }))}
        />
        <Slider
          label="mean_sat"
          value={rules.target.mean_sat}
          min={0.1}
          max={0.8}
          step={0.01}
          format={(v) => v.toFixed(2)}
          onChange={(v) => update((r) => ({ ...r, target: { ...r.target, mean_sat: v } }))}
        />
      </Panel>

      <Panel title="감마">
        <Toggle
          label="활성화"
          checked={rules.gamma.enabled}
          onChange={(v) => update((r) => ({ ...r, gamma: { ...r.gamma, enabled: v } }))}
        />
        <Slider
          label="최소"
          value={rules.gamma.min}
          min={0.4}
          max={1.0}
          step={0.01}
          onChange={(v) => update((r) => ({ ...r, gamma: { ...r.gamma, min: v } }))}
        />
        <Slider
          label="최대"
          value={rules.gamma.max}
          min={1.0}
          max={2.0}
          step={0.01}
          hint="야간 가드가 걸리면 이 값보다 더 낮게 눌립니다"
          onChange={(v) => update((r) => ({ ...r, gamma: { ...r.gamma, max: v } }))}
        />
      </Panel>

      <Panel title="대비">
        <Slider
          label="최소"
          value={rules.contrast.min}
          min={0.5}
          max={1.0}
          step={0.01}
          onChange={(v) => update((r) => ({ ...r, contrast: { ...r.contrast, min: v } }))}
        />
        <Slider
          label="최대"
          value={rules.contrast.max}
          min={1.0}
          max={2.0}
          step={0.01}
          onChange={(v) => update((r) => ({ ...r, contrast: { ...r.contrast, max: v } }))}
        />
        <Slider
          label="클리핑 임계"
          value={rules.contrast.clip_threshold_pct}
          min={0}
          max={10}
          step={0.1}
          format={(v) => `${v.toFixed(1)}%`}
          hint="이 비율을 넘게 잘리면 대비를 깎습니다"
          onChange={(v) =>
            update((r) => ({ ...r, contrast: { ...r.contrast, clip_threshold_pct: v } }))
          }
        />
        <Slider
          label="클리핑 페널티"
          value={rules.contrast.clip_penalty}
          min={0}
          max={0.3}
          step={0.005}
          format={(v) => v.toFixed(3)}
          onChange={(v) =>
            update((r) => ({ ...r, contrast: { ...r.contrast, clip_penalty: v } }))
          }
        />
      </Panel>

      <Panel title="채도">
        <Slider
          label="최소"
          value={rules.saturation.min}
          min={0.5}
          max={1.0}
          step={0.01}
          onChange={(v) => update((r) => ({ ...r, saturation: { ...r.saturation, min: v } }))}
        />
        <Slider
          label="최대"
          value={rules.saturation.max}
          min={1.0}
          max={2.0}
          step={0.01}
          onChange={(v) => update((r) => ({ ...r, saturation: { ...r.saturation, max: v } }))}
        />
        <Slider
          label="얼굴 상한 (skin_max)"
          value={rules.saturation.skin_max}
          min={1.0}
          max={1.6}
          step={0.01}
          hint="얼굴이 검출되면 이 값으로 상한이 내려갑니다"
          onChange={(v) =>
            update((r) => ({ ...r, saturation: { ...r.saturation, skin_max: v } }))
          }
        />
      </Panel>

      <Panel title="언샤프">
        <Slider
          label="base"
          value={rules.unsharp.base}
          min={0}
          max={3}
          step={0.05}
          hint="unsharp = base − sharpness / divisor"
          onChange={(v) => update((r) => ({ ...r, unsharp: { ...r.unsharp, base: v } }))}
        />
        <Slider
          label="divisor"
          value={rules.unsharp.divisor}
          min={50}
          max={1500}
          step={10}
          format={(v) => v.toFixed(0)}
          onChange={(v) => update((r) => ({ ...r, unsharp: { ...r.unsharp, divisor: v } }))}
        />
        <Slider
          label="최소"
          value={rules.unsharp.min}
          min={0}
          max={1}
          step={0.01}
          onChange={(v) => update((r) => ({ ...r, unsharp: { ...r.unsharp, min: v } }))}
        />
        <Slider
          label="최대"
          value={rules.unsharp.max}
          min={0}
          max={3}
          step={0.05}
          hint="100% 크롭에서 과다 여부를 판단하세요"
          onChange={(v) => update((r) => ({ ...r, unsharp: { ...r.unsharp, max: v } }))}
        />
      </Panel>

      <Panel title="화이트밸런스">
        <Toggle
          label="그레이월드 적용"
          checked={rules.whitebalance.enabled}
          onChange={(v) =>
            update((r) => ({ ...r, whitebalance: { ...r.whitebalance, enabled: v } }))
          }
        />
        <Slider
          label="최대 편차"
          value={rules.whitebalance.max_deviation}
          min={0}
          max={0.5}
          step={0.01}
          hint="노을·단풍처럼 한 색이 덮은 사진에서 폭주를 막습니다"
          onChange={(v) =>
            update((r) => ({ ...r, whitebalance: { ...r.whitebalance, max_deviation: v } }))
          }
        />
      </Panel>

      <Panel title="가드">
        <Toggle
          label="야간 (EXIF 기반)"
          checked={rules.guards.night.enabled}
          hint={`ISO ≥ ${rules.guards.night.iso_min} 또는 셔터 ≥ ${rules.guards.night.shutter_max}초 또는 ${rules.guards.night.hour_range[0]}~${rules.guards.night.hour_range[1]}시`}
          onChange={(v) =>
            update((r) => ({
              ...r,
              guards: { ...r.guards, night: { ...r.guards.night, enabled: v } },
            }))
          }
        />
        <Slider
          label="야간 감마 상한"
          value={rules.guards.night.gamma_max}
          min={1.0}
          max={1.6}
          step={0.01}
          onChange={(v) =>
            update((r) => ({
              ...r,
              guards: { ...r.guards, night: { ...r.guards.night, gamma_max: v } },
            }))
          }
        />
        <Toggle
          label="로우키 (EXIF 없을 때 폴백)"
          checked={rules.guards.lowkey.enabled}
          hint={`median_L < ${rules.guards.lowkey.median_L_below}`}
          onChange={(v) =>
            update((r) => ({
              ...r,
              guards: { ...r.guards, lowkey: { ...r.guards.lowkey, enabled: v } },
            }))
          }
        />
        <Toggle
          label="고대비 (역광·실루엣)"
          checked={rules.guards.highcontrast.enabled}
          hint={`spread_L > ${rules.guards.highcontrast.spread_L_above}`}
          onChange={(v) =>
            update((r) => ({
              ...r,
              guards: {
                ...r.guards,
                highcontrast: { ...r.guards.highcontrast, enabled: v },
              },
            }))
          }
        />
      </Panel>
    </div>
  );
}
