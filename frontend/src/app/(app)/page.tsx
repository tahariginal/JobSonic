"use client";
import { ArrowRight, Award, CalendarCheck, ClipboardCheck, FileText, Globe2, Radar, Send, Sparkles, Star, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { EventRow } from "@/components/EventRow";
import { BarList, ChartCard, ColumnChart, Stat } from "@/components/charts";
import { useShell } from "@/components/Shell";
import { Button, Callout, Card, CardHeader, Empty, ErrorNote, PageHeader, Skeleton, VISA_COLOR } from "@/components/ui";
import { timeAgo } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export default function Overview() {
  const { data, error, reload } = useApi<any>("/overview", 15000);
  const { refreshKey, runSearch, searching, openJob } = useShell();
  const router = useRouter();
  useEffect(() => { reload(); }, [refreshKey, reload]);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <div className="space-y-4"><Skeleton className="h-9 w-56" /><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)}</div><Skeleton className="h-64" /></div>;
  const m = data.metrics;
  const last = data.last_runs?.discovery;
  const trend = fillDays(data.discovery_trend, 30);
  return (
    <div className="animate-in space-y-6">
      <PageHeader title="Overview"
        subtitle={last ? <>Last search {timeAgo(last.at)} · {m.sources} sources · {last.new} new, {last.closed} closed{data.schedule.discovery_enabled ? ` · runs every ${data.schedule.discovery_interval_hours}h` : " · schedule paused"}</> : `No search has completed yet · ${m.sources} sources configured`}
        actions={<Button variant="primary" onClick={runSearch} loading={searching} icon={<Radar className="size-4" />}>{searching ? "Searching…" : "Run job search"}</Button>} />

      {m.awaiting_approval > 0 && (
        <Callout title={`${m.awaiting_approval} application${m.awaiting_approval > 1 ? "s" : ""} waiting for your approval`} action={<Link href="/approvals/"><Button variant="primary" size="sm" icon={<ArrowRight className="size-4" />}>Review</Button></Link>}>
          Filled forms are ready. Nothing is sent until you approve the exact version.
        </Callout>
      )}
      {(data.profile_gaps.length > 0 || !data.has_cv) && (
        <Callout tone="warn" title="Finish your profile before applying" action={<Link href="/profile/"><Button size="sm">Open profile</Button></Link>}>
          Missing: {[...(data.has_cv ? [] : ["a CV"]), ...data.profile_gaps.map((g: string) => g.split(" (")[0].toLowerCase())].join(", ")}. Forms are only filled with data you have entered.
        </Callout>
      )}

      <section aria-label="Key numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Jobs discovered" value={m.jobs_discovered} sub={`${m.active_jobs.toLocaleString()} currently open`} icon={<Globe2 className="size-4" />} onClick={() => router.push("/jobs/")} />
        <Stat label="New verified matches" value={m.new_verified_matches} sub="last 7 days, passed filters" icon={<Sparkles className="size-4" />} onClick={() => router.push("/jobs/?days=7&eligibility=eligible|needs_review&sort=newest")} />
        <Stat label="High-fit opportunities" value={m.high_fit} sub="4★ and above" accent icon={<Star className="size-4" />} onClick={() => router.push("/jobs/?min_stars=4&eligibility=eligible|needs_review")} />
        <Stat label="Awaiting approval" value={m.awaiting_approval} sub="need your review" accent icon={<ClipboardCheck className="size-4" />} onClick={() => router.push("/approvals/")} />
        <Stat label="Applications prepared" value={m.applications_prepared} sub="all time" icon={<FileText className="size-4" />} onClick={() => router.push("/pipeline/")} />
        <Stat label="Submitted" value={m.submitted} sub="approved and sent" icon={<Send className="size-4" />} />
        <Stat label="Interviews" value={m.interviews} sub={`${m.offers} offer${m.offers === 1 ? "" : "s"}`} icon={<CalendarCheck className="size-4" />} />
        <Stat label="Response rate" value={m.response_rate === null ? null : `${Math.round(m.response_rate * 100)}%`} sub={`${m.rejections} rejection${m.rejections === 1 ? "" : "s"}`} icon={m.offers ? <Award className="size-4" /> : <XCircle className="size-4" />} />
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard className="lg:col-span-2" title="Relevant jobs discovered" hint="Per day, last 30 days · engineering roles matching your target titles" data={trend}>
          <ColumnChart data={trend} />
        </ChartCard>
        <ChartCard title="Visa sponsorship" hint="Open jobs that passed the hard filters" data={visaData(data.visa_breakdown)}>
          <BarList data={visaData(data.visa_breakdown)} onSelect={(d) => router.push(`/jobs/?visa=${(d as any).status}&eligibility=eligible|needs_review`)} />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title="Opportunities by country" hint="Open jobs that passed the hard filters" data={data.opportunities_by_country.map((c: any) => ({ label: c.country, value: c.count }))}>
          <BarList data={data.opportunities_by_country.map((c: any) => ({ label: c.country, value: c.count }))} onSelect={(d) => d.label !== "Unknown" && router.push(`/jobs/?country=${encodeURIComponent(d.label)}&eligibility=eligible|needs_review`)} />
        </ChartCard>
        <ChartCard title="Applications by country" hint="Submitted applications" data={data.applications_by_country.map((c: any) => ({ label: c.country, value: c.count }))} emptyText="Appears after your first submitted application.">
          <BarList data={data.applications_by_country.map((c: any) => ({ label: c.country, value: c.count }))} />
        </ChartCard>
        <Card>
          <CardHeader title="Recent activity" hint="Real backend events" action={<Link href="/activity/" className="text-xs font-medium text-ink-3 hover:text-accent">View all</Link>} />
          <div className="px-2 pb-3">
            {data.recent_activity.length === 0 ? <Empty title="No activity yet">Run a job search to get started.</Empty>
              : <ul>{data.recent_activity.slice(0, 7).map((e: any) => <EventRow key={e.id} e={e} compact onOpenJob={openJob} />)}</ul>}
          </div>
        </Card>
      </div>
    </div>
  );
}

function visaData(rows: any[]) {
  const order = ["confirmed", "conditional", "not_required", "unverified", "not_supported"];
  return [...rows].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status)).map((v) => ({ label: v.label, value: v.count, color: VISA_COLOR[v.status], status: v.status }));
}
function fillDays(rows: { date: string; count: number }[], n: number) {
  const map = new Map(rows.map((r) => [r.date, r.count]));
  const out = [];
  const now = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    out.push({ label: d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }), value: map.get(key) ?? 0 });
  }
  return out;
}
