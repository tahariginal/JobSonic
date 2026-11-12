"use client";
import { AlertTriangle, Bot, CheckCircle2, ClipboardCheck, FileText, Mail, MousePointerClick, Radar, Send, ShieldCheck, UserRound, XCircle } from "lucide-react";
import Link from "next/link";
import React from "react";
import { fmtDate, timeAgo } from "@/lib/api";
import { cx } from "./ui";

const ICONS: [RegExp, React.ElementType][] = [
  [/^discovery/, Radar], [/^verify|^job\./, ShieldCheck], [/^ai/, Bot], [/^prepare/, FileText], [/^form/, MousePointerClick],
  [/^approval/, ClipboardCheck], [/^submit\.(succeeded|manual)/, CheckCircle2], [/^submit\.(failed|uncertain|blocked)/, XCircle], [/^submit/, Send],
  [/^email/, Mail], [/^profile|^pipeline/, UserRound],
];
export function EventRow({ e, compact, onOpenJob }: { e: any; compact?: boolean; onOpenJob?: (id: number) => void }) {
  const Icon = e.level === "error" ? XCircle : e.level === "warn" ? AlertTriangle : ICONS.find(([r]) => r.test(e.type))?.[1] ?? Radar;
  const tone = e.level === "error" ? "text-bad border-bad/30 bg-bad/10" : e.level === "warn" ? "text-warn border-warn/30 bg-warn/10" : /succeeded|approved|filled|completed/.test(e.type) ? "text-good border-good/30 bg-good/10" : "text-ink-3 border-line bg-raised";
  const body = (
    <>
      <span className={cx("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg border", tone)}><Icon className="size-3.5" aria-hidden /></span>
      <span className="min-w-0 flex-1">
        <span className={cx("text-[13px] leading-snug text-ink-2", compact ? "line-clamp-2" : "block")}>{e.message}</span>
        <span className="mt-0.5 block text-[11px] text-ink-3" title={fmtDate(e.created_at)}>{timeAgo(e.created_at)}{!compact && <span className="ml-2 font-mono">{e.type}</span>}</span>
      </span>
    </>
  );
  const cls = "flex w-full gap-3 rounded-xl px-3 py-2.5 text-left transition-colors";
  if (e.application_id) return <li><Link href={`/application/?id=${e.application_id}`} className={cx(cls, "hover:bg-hover")}>{body}</Link></li>;
  if (e.job_id && onOpenJob) return <li><button onClick={() => onOpenJob(e.job_id)} className={cx(cls, "hover:bg-hover")}>{body}</button></li>;
  return <li><div className={cls}>{body}</div></li>;
}
