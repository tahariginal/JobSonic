"use client";
import { ArrowUpRight, ListChecks, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Stat } from "@/components/charts";
import { useShell } from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { titleCase } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";

const STATUS: Record<string, [string, string]> = {
  draft: ["neutral", "Draft"], prepared: ["neutral", "Prepared"],
  awaiting_approval: ["accent", "Awaiting approval"], approved: ["info", "Approved · queued to send"],
  submitting: ["info", "Submitting"], submitted: ["good", "Submitted"],
  needs_manual: ["warn", "Manual step needed"], failed: ["bad", "Submission failed"],
  submit_uncertain: ["bad", "Outcome unknown"], changes_requested: ["warn", "Changes requested"],
  declined: ["neutral", "Declined by you"],
};
type Application = {
  id: number; company: string; title: string; location: string; status: string; stage: string;
  created_at: string; updated_at: string; submitted_at: string | null; submitted_via: string;
  last_error: string; blocking_issues: number; form_attempted_at: string | null;
  form_outcome: string | null; fields_filled: number; fill_is_current: boolean;
};
type Tracker = {
  items: Application[]; total: number; statuses: Record<string, number>;
  summary: { companies: number; applications: number; awaiting_approval: number; submitted: number };
};
const PAGE_SIZE = 50;
const date = (value: string) => new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

function formProgress(a: Application) {
  if (!a.form_attempted_at) return a.submitted_via === "manual" ? "Completed manually" : "No current form review";
  if (!a.fill_is_current) return "Form changed · refill needed";
  if (a.form_outcome === "filled") return `${a.fields_filled} fields filled`;
  return a.fields_filled ? `${a.fields_filled} fields filled · incomplete` : "Form attempt needs attention";
}

export default function ApplicationTrackerPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  const params = new URLSearchParams({ q: search, status, offset: String(page * PAGE_SIZE), limit: String(PAGE_SIZE) });
  const { data, error, loading, reload } = useApi<Tracker>(`/application-tracker?${params}`, 12000);
  const { refreshKey } = useShell();
  useEffect(() => { reload(); }, [refreshKey, reload]);
  const summary = data?.summary;

  return (
    <>
      <PageHeader title="Application tracker" subtitle="Every company and role you’ve started an application for. Forms are filled from your profile and sent only after your approval."
        actions={<Button onClick={reload} icon={<RefreshCw className="size-4" />} loading={loading}>Refresh</Button>} />

      <div className="mb-6 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Companies" value={summary?.companies ?? null} sub="with applications" />
        <Stat label="Applications" value={summary?.applications ?? null} sub="all time" />
        <Stat label="Awaiting approval" value={summary?.awaiting_approval ?? null} sub="ready for your review" accent />
        <Stat label="Submitted" value={summary?.submitted ?? null} sub="agent or manually recorded" />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <div className="relative min-w-0 flex-1 basis-56">
            <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-ink-3" aria-hidden />
            <Input aria-label="Search companies or roles" placeholder="Search companies or roles…" className="pl-9" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} />
          </div>
          <Select aria-label="Application status" className="w-full sm:w-60" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
            <option value="">All statuses</option>
            {Object.entries(STATUS).map(([key, [, label]]) => <option key={key} value={key}>{label} ({data?.statuses[key] ?? 0})</option>)}
          </Select>
        </div>

        {error && <div className="p-4"><ErrorNote>{error} <button className="underline" onClick={reload}>Try again</button></ErrorNote></div>}
        {!data && !error && <div className="space-y-3 p-4" role="status" aria-label="Loading applications"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}
        {data && data.items.length === 0 && !error && (
          <Empty icon={<ListChecks className="size-5" />} title={data.summary.applications ? "No matching applications" : "No applications yet"}
            action={data.summary.applications ? <Button onClick={() => { setQuery(""); setStatus(""); }}>Clear filters</Button> : <Link className="text-sm font-medium text-accent hover:underline" href="/jobs/">Browse jobs <span aria-hidden>→</span></Link>}>
            {data.summary.applications ? "Try a different company, role, or status." : "Open a job and choose Prepare application. It will appear here so you can follow form filling, approval, and submission."}
          </Empty>
        )}
        {data && data.items.length > 0 && (
          <>
            <div className="hidden grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto] gap-5 border-b border-line bg-raised/40 px-5 py-2.5 text-xs text-ink-3 xl:grid" aria-hidden>
              <span>Company & role</span><span>Application status</span><span>Form progress & dates</span><span className="w-28">Details</span>
            </div>
            <ul aria-label="Tracked applications" aria-busy={loading} className="divide-y divide-line">
              {data.items.map((a) => {
                const [tone, label] = STATUS[a.status] ?? ["neutral", titleCase(a.status)];
                return (
                  <li key={a.id} className="grid min-w-0 gap-4 px-5 py-4 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto] xl:gap-5">
                    <div className="min-w-0">
                      <p className="break-words text-sm font-semibold">{a.company}</p>
                      <p className="mt-1 break-words text-[13px] text-ink-2">{a.title}</p>
                      <p className="mt-1 text-xs text-ink-3">{a.location || "Location not listed"}</p>
                    </div>
                    <div className="min-w-0 space-y-2">
                      <Badge tone={tone}>{label}</Badge>
                      {["interview", "offer", "rejected"].includes(a.stage) && <p className="text-xs text-ink-2">Latest outcome: {titleCase(a.stage)}</p>}
                      {a.last_error ? <p className="break-words text-xs text-warn">{a.last_error}</p> : a.blocking_issues > 0 ? <p className="text-xs text-warn">{a.blocking_issues} item{a.blocking_issues === 1 ? " needs" : "s need"} your input</p> : null}
                      {a.status === "submit_uncertain" && <p className="text-xs text-ink-3">Check the employer site before trying again.</p>}
                    </div>
                    <div className="space-y-1 text-xs text-ink-3">
                      <p className="text-ink-2">{formProgress(a)}</p>
                      {a.form_attempted_at && <p>Last form attempt {date(a.form_attempted_at)}</p>}
                      {a.submitted_at && <p className="text-ink-2">Submitted {date(a.submitted_at)} · {a.submitted_via === "manual" ? "manual" : "agent"}</p>}
                      <p>Started {date(a.created_at)}</p>
                      <p>Updated {date(a.updated_at)}</p>
                    </div>
                    <Link href={`/application/?id=${a.id}`} aria-label={`View application for ${a.title} at ${a.company}`}
                      className="inline-flex h-9 w-fit items-center gap-1.5 self-start rounded-lg border border-line bg-raised px-3 text-[13px] font-medium text-ink-2 hover:border-line-strong hover:text-ink">
                      View details<ArrowUpRight className="size-3.5" aria-hidden />
                    </Link>
                  </li>
                );
              })}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
              <p className="text-xs text-ink-3" role="status">{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total} applications · most recently updated first</p>
              <div className="flex gap-2">
                <Button size="sm" disabled={loading || page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button size="sm" disabled={loading || (page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
