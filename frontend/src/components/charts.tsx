"use client";
import { BarChart3, Table2 } from "lucide-react";
import React, { useState } from "react";
import { Card, cx, Empty } from "./ui";

export type Datum = { label: string; value: number; color?: string; hint?: string };

/** Card wrapper: every chart has a table view, so no value is reachable only by hovering. */
export function ChartCard({ title, hint, data, children, unit = "", emptyText, className }: {
  title: string; hint?: string; data: Datum[]; children: React.ReactNode; unit?: string; emptyText?: string; className?: string;
}) {
  const [table, setTable] = useState(false);
  const empty = data.length === 0 || data.every((d) => d.value === 0);
  return (
    <Card className={className} role="region" aria-label={title}>
      <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-2">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold tracking-wide">{title}</h2>
          {hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
        </div>
        {!empty && (
          <button onClick={() => setTable((t) => !t)} aria-pressed={table} aria-label={table ? "Show chart" : "Show as table"} title={table ? "Show chart" : "Show as table"}
            className="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-hover hover:text-ink">
            {table ? <BarChart3 className="size-4" /> : <Table2 className="size-4" />}
          </button>
        )}
      </div>
      <div className="px-5 pb-5">
        {empty ? <Empty title="No data yet">{emptyText ?? "This fills in as real activity happens."}</Empty> : table ? (
          <table className="w-full text-[13px]">
            <tbody>
              {data.map((d) => (
                <tr key={d.label} className="border-b border-line/60 last:border-0">
                  <td className="py-1.5 text-ink-2">{d.label}</td>
                  <td className="py-1.5 text-right font-medium tabular">{d.value.toLocaleString()}{unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : children}
      </div>
    </Card>
  );
}

/** Horizontal bars: label left, thin bar, value at the tip. One hue unless a row carries its own (status) colour. */
export function BarList({ data, color = "var(--color-chart)", max, onSelect }: { data: Datum[]; color?: string; max?: number; onSelect?: (d: Datum) => void }) {
  const top = max ?? Math.max(1, ...data.map((d) => d.value));
  const total = data.reduce((a, d) => a + d.value, 0);
  return (
    <ul className="space-y-2.5">
      {data.map((d) => {
        const pct = total ? Math.round((d.value / total) * 100) : 0;
        const inner = (
          <>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="flex min-w-0 items-center gap-2 text-ink-2">
                {d.color && <span className="size-2 shrink-0 rounded-[3px]" style={{ background: d.color }} aria-hidden />}
                <span className="truncate">{d.label}</span>
              </span>
              <span className="shrink-0 font-medium tabular text-ink">{d.value.toLocaleString()}<span className="ml-1.5 text-xs font-normal text-ink-3">{pct}%</span></span>
            </div>
            <div className="h-2 overflow-hidden rounded-r-[4px] bg-white/[.04]">
              <div className="h-full rounded-r-[4px] transition-[width,filter] duration-500 ease-out group-hover:brightness-125 group-focus-visible:brightness-125"
                style={{ width: `${Math.max(1.5, (d.value / top) * 100)}%`, background: d.color ?? color }} />
            </div>
          </>
        );
        return (
          <li key={d.label}>
            {onSelect ? <button onClick={() => onSelect(d)} title={d.hint ?? `${d.label}: ${d.value}`} className="group block w-full text-left">{inner}</button>
              : <div className="group" title={d.hint ?? `${d.label}: ${d.value.toLocaleString()} (${pct}%)`} tabIndex={0}>{inner}</div>}
          </li>
        );
      })}
    </ul>
  );
}

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

/** Time-series columns with a hover/focus tooltip; thin marks, square baseline, rounded cap, recessive grid. */
export function ColumnChart({ data, height = 180, color = "var(--color-chart)", unit = "" }: { data: Datum[]; height?: number; color?: string; unit?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const top = niceMax(Math.max(1, ...data.map((d) => d.value)));
  const ticks = [0, top / 2, top];
  const plotH = height - 26;
  const stride = Math.max(1, Math.ceil(data.length / 7));
  return (
    <div className="relative" style={{ height }} onMouseLeave={() => setHover(null)}>
      <div className="absolute inset-y-0 left-0 w-8">
        {ticks.map((t) => (
          <span key={t} className="absolute right-1.5 -translate-y-1/2 text-[10px] tabular text-ink-3" style={{ top: plotH - (t / top) * plotH }}>
            {t >= 1000 ? `${(t / 1000).toFixed(t % 1000 ? 1 : 0)}K` : Number.isInteger(t) ? t : t.toFixed(1)}
          </span>
        ))}
      </div>
      <div className="absolute left-8 right-0 top-0" style={{ height: plotH }}>
        {ticks.map((t) => <div key={t} className="absolute inset-x-0 h-px bg-line/70" style={{ top: plotH - (t / top) * plotH }} />)}
        <div className="absolute inset-0 flex items-end">
          {data.map((d, i) => (
            <div key={d.label} className="group relative flex h-full flex-1 items-end justify-center outline-none" tabIndex={0}
              onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
              aria-label={`${d.label}: ${d.value}${unit}`}>
              {hover === i && <div className="absolute inset-y-0 w-full bg-white/[.035]" />}
              <div className="relative w-[62%] max-w-[22px] rounded-t-[4px] transition-[height,filter] duration-500 ease-out"
                style={{ height: d.value ? Math.max(3, (d.value / top) * plotH) : 0, background: color, filter: hover === i ? "brightness(1.3)" : undefined }} />
            </div>
          ))}
        </div>
        {hover !== null && data[hover] && (
          <div className="pointer-events-none absolute z-10 -translate-x-1/2 whitespace-nowrap rounded-lg border border-line-strong bg-raised px-2.5 py-1.5 shadow-xl shadow-black/50"
            style={{ left: `${((hover + 0.5) / data.length) * 100}%`, top: Math.max(0, plotH - (data[hover].value / top) * plotH - 46) }}>
            <div className="text-sm font-semibold tabular leading-4">{data[hover].value.toLocaleString()}{unit}</div>
            <div className="text-[11px] text-ink-3">{data[hover].hint ?? data[hover].label}</div>
          </div>
        )}
      </div>
      <div className="absolute bottom-0 left-8 right-0 flex h-5 items-end">
        {data.map((d, i) => (
          <span key={d.label} className="flex-1 overflow-visible text-center text-[10px] text-ink-3">
            {i % stride === 0 ? <span className="whitespace-nowrap">{d.label}</span> : null}
          </span>
        ))}
      </div>
    </div>
  );
}

/** A headline number. `value === null` renders as "not available yet", never as zero. */
export function Stat({ label, value, sub, accent, onClick, icon }: { label: string; value: number | string | null; sub?: string; accent?: boolean; onClick?: () => void; icon?: React.ReactNode }) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-ink-3">{label}</span>
        {icon && <span className={cx("text-ink-3 transition-colors", onClick && "group-hover:text-accent")}>{icon}</span>}
      </div>
      <div className={cx("mt-2 text-[26px] font-semibold leading-none tracking-tight tabular", accent && value ? "text-accent" : "text-ink", value === null && "text-ink-3")}>
        {value === null ? "—" : typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div className="mt-1.5 min-h-4 text-xs text-ink-3">{value === null ? "Not available yet" : sub}</div>
    </>
  );
  const cls = "group rounded-card border border-line bg-surface p-4 text-left transition-all duration-200";
  return onClick ? <button onClick={onClick} className={cx(cls, "hover:-translate-y-0.5 hover:border-line-strong hover:bg-raised")}>{body}</button> : <div className={cls}>{body}</div>;
}
