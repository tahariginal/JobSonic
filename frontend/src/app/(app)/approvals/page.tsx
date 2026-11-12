"use client";
import { AlertTriangle, ArrowRight, ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { useShell } from "@/components/Shell";
import { Badge, Card, Empty, ErrorNote, PageHeader, Skeleton, Stars, VisaBadge } from "@/components/ui";
import { timeAgo } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const ATTENTION: Record<string, [string, string, string]> = {
  needs_manual: ["warn", "Manual step needed", "The site asked for something automation must not do (CAPTCHA, login). Continue manually."],
  failed: ["bad", "Submission failed", "Nothing was sent. Review and approve again."],
  submit_uncertain: ["bad", "Check manually", "Submit was pressed but no confirmation was detected. It will not be retried."],
  changes_requested: ["warn", "Changes requested", "You asked for changes. Edit and prepare the form again."],
  prepared: ["neutral", "Prepared", "Materials are ready. Fill the form to queue it for approval."],
};

export default function ApprovalsPage() {
  const { data, error, reload } = useApi<any>("/approvals", 10000);
  const { refreshKey } = useShell();
  useEffect(() => { reload(); }, [refreshKey, reload]);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  return (
    <div className="animate-in mx-auto max-w-3xl">
      <PageHeader title="Approval inbox" subtitle="Review exactly what will be sent. An approval covers one job and one version; any later change needs a new approval." />
      {!data ? <div className="space-y-3"><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : (
        <>
          <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">Waiting for you <span className="rounded-md bg-accent px-1.5 py-0.5 text-[11px] font-semibold text-accent-ink tabular">{data.awaiting.length}</span></h2>
          {data.awaiting.length === 0 ? (
            <Card><Empty icon={<ClipboardCheck className="size-5" />} title="Nothing to approve">When a form has been filled for a shortlisted job, it appears here for your review.</Empty></Card>
          ) : (
            <ul className="space-y-2.5">{data.awaiting.map((a: any) => <Item key={a.id} a={a} primary />)}</ul>
          )}
          {data.attention.length > 0 && (
            <>
              <h2 className="mb-2 mt-8 flex items-center gap-2 text-[13px] font-semibold"><AlertTriangle className="size-4 text-warn" />In progress or needs attention <span className="rounded-md bg-white/[.06] px-1.5 py-0.5 text-[11px] font-medium tabular text-ink-2">{data.attention.length}</span></h2>
              <ul className="space-y-2.5">{data.attention.map((a: any) => <Item key={a.id} a={a} />)}</ul>
            </>
          )}
        </>
      )}
    </div>
  );
}

function Item({ a, primary }: { a: any; primary?: boolean }) {
  const att = ATTENTION[a.status];
  return (
    <li>
      <Link href={`/application/?id=${a.id}`} className={`group flex items-center gap-4 rounded-card border bg-surface p-4 transition-all hover:-translate-y-0.5 hover:bg-raised ${primary ? "border-accent/35 hover:border-accent/60" : "border-line hover:border-line-strong"}`}>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-accent">{a.company}</p>
          <p className="mt-0.5 text-[15px] font-medium leading-snug">{a.title}</p>
          <p className="mt-1 truncate text-xs text-ink-3">{a.location || "Location not stated"} · version {a.revision} · updated {timeAgo(a.updated_at)}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Stars value={a.fit_stars} size={12} /><VisaBadge status={a.visa_status} />
            {primary ? <Badge tone="accent">Ready to review</Badge> : att && <Badge tone={att[0]}>{att[1]}</Badge>}
            {a.blocking_issues > 0 && <Badge tone="warn">{a.blocking_issues} item{a.blocking_issues > 1 ? "s" : ""} need input</Badge>}
            {!a.is_active && <Badge tone="bad">Vacancy closed</Badge>}
          </div>
          {!primary && att && <p className="mt-2 text-xs text-ink-3">{a.blocking_issues > 0 && a.status === "prepared" ? "Some required answers are missing. Open it to fill them in." : att[2]}</p>}
        </div>
        <ArrowRight className="size-5 shrink-0 text-ink-3 transition-all group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden />
      </Link>
    </li>
  );
}
