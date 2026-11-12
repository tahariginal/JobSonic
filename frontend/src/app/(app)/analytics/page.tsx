"use client";
import { useEffect } from "react";
import { BarList, ChartCard, ColumnChart, Stat } from "@/components/charts";
import { useShell } from "@/components/Shell";
import { Badge, Card, CardHeader, ErrorNote, PageHeader, Skeleton, VISA_COLOR } from "@/components/ui";
import { titleCase } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const wk = (iso: string) => new Date(iso + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

export default function AnalyticsPage() {
  const { data: d, error, reload } = useApi<any>("/analytics", 30000);
  const { refreshKey } = useShell();
  useEffect(() => { reload(); }, [refreshKey, reload]);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!d) return <div className="space-y-4"><Skeleton className="h-9 w-48" /><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)}</div><Skeleton className="h-72" /></div>;
  const apps = d.applications_over_time.map((x: any) => ({ label: wk(x.week), value: x.count, hint: `Week of ${wk(x.week)}` }));
  const rej = d.rejection_trend.map((x: any) => ({ label: wk(x.week), value: x.count, hint: `Week of ${wk(x.week)}` }));
  const order = ["confirmed", "conditional", "not_required", "unverified", "not_supported"];
  const visa = [...d.visa_distribution].sort((a: any, b: any) => order.indexOf(a.status) - order.indexOf(b.status)).map((v: any) => ({ label: v.label, value: v.count, color: VISA_COLOR[v.status] }));
  const fit = [5, 4, 3, 2, 1].map((s) => ({ label: `${"★".repeat(s)}${"☆".repeat(5 - s)}`, value: d.fit_distribution.find((x: any) => x.stars === s)?.count ?? 0 }));
  const ai = d.ai;
  const cfg = ai.config;
  return (
    <div className="animate-in space-y-6">
      <PageHeader title="Analytics" subtitle="Computed from real records only. A dash means there is not enough data yet, not zero." />
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Summary">
        <Stat label="Applications submitted" value={d.submitted} sub="all time" />
        <Stat label="Interview conversion" value={d.interview_conversion === null ? null : `${Math.round(d.interview_conversion * 100)}%`} sub={`${d.interviews_reached} reached interview`} />
        <Stat label="Average fit" value={d.average_fit === null ? null : `${d.average_fit.toFixed(1)} ★`} sub="open jobs that passed filters" />
        <Stat label="AI calls this month" value={ai.usage.month.calls} sub={ai.available ? `of ${cfg.monthly_call_budget} budgeted` : "AI is off"} />
      </section>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Applications over time" hint="Submitted per week" data={apps} emptyText="Appears after your first submitted application."><ColumnChart data={apps} /></ChartCard>
        <ChartCard title="Rejection trend" hint="Rejections recorded per week" data={rej} emptyText="No rejections recorded."><ColumnChart data={rej} color="var(--color-bad)" /></ChartCard>
        <ChartCard title="Countries with the most opportunities" hint="Open jobs that passed the hard filters" data={d.countries.map((c: any) => ({ label: c.country, value: c.count }))}><BarList data={d.countries.map((c: any) => ({ label: c.country, value: c.count }))} /></ChartCard>
        <div className="space-y-4">
          <ChartCard title="Visa sponsorship distribution" hint="Based on quoted evidence in each official posting" data={visa}><BarList data={visa} /></ChartCard>
          <ChartCard title="Fit rating distribution" hint="Open jobs that passed the hard filters" data={fit}><BarList data={fit} /></ChartCard>
        </div>
        <ChartCard title="Why jobs are filtered out" hint="Hard-rule rejections among open jobs (a job can have several)" data={d.filter_reasons.map((r: any) => ({ label: r.label, value: r.count }))}><BarList data={d.filter_reasons.map((r: any) => ({ label: r.label, value: r.count }))} color="var(--color-unknown)" /></ChartCard>
        <Card>
          <CardHeader title="AI usage and estimated cost" hint="Every model call is logged, budgeted and cached" action={<Badge tone={ai.available ? "good" : "neutral"}>{ai.available ? "On" : "Off"}</Badge>} />
          <div className="px-5 pb-5">
            {!ai.available && <p className="mb-3 rounded-xl border border-line bg-raised/60 p-3 text-[13px] text-ink-2">{ai.reason} Discovery, filtering, visa evidence and fit scoring run without AI.</p>}
            <table className="w-full text-[13px]">
              <thead><tr className="text-left text-[11px] uppercase tracking-[0.08em] text-ink-3"><th className="pb-2 font-medium">Period</th><th className="pb-2 text-right font-medium">Calls</th><th className="pb-2 text-right font-medium">Budget</th><th className="pb-2 text-right font-medium">Est. cost</th></tr></thead>
              <tbody className="tabular">
                <tr className="border-t border-line/60"><td className="py-2 text-ink-2">Today</td><td className="py-2 text-right">{ai.usage.today.calls}</td><td className="py-2 text-right text-ink-3">{cfg.daily_call_budget}</td><td className="py-2 text-right">${ai.usage.today.est_cost_usd.toFixed(3)}</td></tr>
                <tr className="border-t border-line/60"><td className="py-2 text-ink-2">This month</td><td className="py-2 text-right">{ai.usage.month.calls}</td><td className="py-2 text-right text-ink-3">{cfg.monthly_call_budget}</td><td className="py-2 text-right">${ai.usage.month.est_cost_usd.toFixed(3)}</td></tr>
                <tr className="border-t border-line/60"><td className="py-2 text-ink-2">All time</td><td className="py-2 text-right">{ai.usage.all_time.calls}</td><td className="py-2 text-right text-ink-3">—</td><td className="py-2 text-right">${ai.usage.all_time.est_cost_usd.toFixed(3)}</td></tr>
              </tbody>
            </table>
            <p className="mt-3 text-xs leading-relaxed text-ink-3">Cost is the API-equivalent estimate reported by the Claude CLI. With a subscription login it is drawn from your plan's usage allowance, not billed per call. {ai.usage.cache_hits} repeat request{ai.usage.cache_hits === 1 ? "" : "s"} served from cache at no cost.</p>
            {ai.by_purpose.length > 0 && <ul className="mt-3 space-y-1 text-[13px]">{ai.by_purpose.map((p: any) => <li key={p.purpose} className="flex justify-between"><span className="text-ink-2">{titleCase(p.purpose)}</span><span className="tabular text-ink-3">{p.calls} calls · ${p.est_cost_usd.toFixed(3)}</span></li>)}</ul>}
          </div>
        </Card>
      </div>
    </div>
  );
}
