import type { ReactNode } from "react";

/** 규칙 슬라이더. 값은 항상 yaml에서 오고, 여기서 하드코딩하지 않습니다. */
export function Slider({
  label,
  value,
  min,
  max,
  step = 0.01,
  onChange,
  hint,
  format = (v: number) => v.toFixed(2),
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  hint?: string;
  format?: (v: number) => string;
}) {
  return (
    <label className="block py-1.5">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-slate-300">{label}</span>
        <span className="font-mono tabular-nums text-slate-400">{format(value)}</span>
      </div>
      <input
        type="range"
        className="mt-1 w-full accent-sky-400"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint && <p className="mt-0.5 text-[11px] leading-tight text-slate-500">{hint}</p>}
    </label>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 py-1.5 text-xs">
      <input
        type="checkbox"
        className="mt-0.5 accent-sky-400"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="text-slate-300">{label}</span>
        {hint && <p className="text-[11px] leading-tight text-slate-500">{hint}</p>}
      </span>
    </label>
  );
}

export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <label className="block py-1.5 text-xs">
      <span className="text-slate-300">{label}</span>
      <select
        className="mt-1 w-full rounded border border-ink-600 bg-ink-800 px-2 py-1 text-slate-200"
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** 클램프 배지. 규칙이 감당하지 못한 사진을 눈에 띄게 만드는 것이 이 앱의 요점입니다. */
export function ClampBadge({ items, title }: { items: string[]; title?: string }) {
  if (!items.length) return null;
  return (
    <span
      title={title ?? `클램프: ${items.join(", ")}`}
      className="rounded bg-clamp/20 px-1.5 py-0.5 text-[10px] font-medium text-clamp ring-1 ring-clamp/40"
    >
      {items.join(" · ")}
    </span>
  );
}

export function GuardBadge({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-300 ring-1 ring-sky-500/30">
      {items.join(" · ")}
    </span>
  );
}

export function Panel({
  title,
  children,
  right,
}: {
  title: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-ink-600 bg-ink-800/60">
      <header className="flex items-center justify-between border-b border-ink-600 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {title}
        </h2>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "ghost" | "danger";
  disabled?: boolean;
  title?: string;
}) {
  const styles = {
    default: "bg-ink-700 hover:bg-ink-600 text-slate-200 border-ink-600",
    primary: "bg-sky-600 hover:bg-sky-500 text-white border-sky-500",
    ghost: "bg-transparent hover:bg-ink-700 text-slate-400 border-transparent",
    danger: "bg-red-900/60 hover:bg-red-800 text-red-200 border-red-800",
  }[variant];
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`rounded border px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  );
}

export function Stat({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-ink-700 py-1 text-xs last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="font-mono tabular-nums text-slate-300">
        {value}
        {unit && <span className="ml-0.5 text-slate-500">{unit}</span>}
      </span>
    </div>
  );
}

/** 클램프 히트율 요약. 부록의 판정 기준을 그대로 보여줍니다. */
export function ClampSummary({
  rate,
  counts,
  stage,
}: {
  rate: number;
  counts: Record<string, number>;
  stage: 1 | 2;
}) {
  const pct = rate * 100;
  const verdict =
    stage === 1
      ? pct > 30
        ? { text: "사진 성격이 너무 다양합니다 — grade.yaml 분리를 검토하세요", tone: "text-red-400" }
        : pct > 10
          ? { text: "클램프 범위나 target 조정으로 해결 가능", tone: "text-clamp" }
          : { text: "규칙이 잘 맞습니다", tone: "text-emerald-400" }
      : counts.max_zoom
        ? { text: "max_zoom 히트 — 출력을 낮추거나 zoom.amount를 줄이세요", tone: "text-clamp" }
        : counts.aspect
          ? { text: "종횡비 편차 — blur_fill을 기본으로 두세요", tone: "text-clamp" }
          : { text: "모션 규칙이 잘 맞습니다", tone: "text-emerald-400" };

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xl tabular-nums text-slate-200">{pct.toFixed(0)}%</span>
        <span className="text-xs text-slate-500">클램프 히트율</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-ink-700">
        <div
          className={`h-full transition-all ${pct > 30 ? "bg-red-500" : pct > 10 ? "bg-clamp" : "bg-emerald-500"}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <p className={`text-[11px] ${verdict.tone}`}>{verdict.text}</p>
      {Object.keys(counts).length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
          {Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => (
              <span
                key={k}
                className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-[10px] text-slate-400"
              >
                {k} {v}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
