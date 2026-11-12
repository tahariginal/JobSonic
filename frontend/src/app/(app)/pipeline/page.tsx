"use client";
import { GripVertical } from "lucide-react";
import Link from "next/link";
import React, { useEffect, useState } from "react";
import { useShell } from "@/components/Shell";
import { Badge, Button, cx, ErrorNote, Modal, PageHeader, Select, Skeleton, Stars, useToast, VisaBadge } from "@/components/ui";
import { api, titleCase } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const LABEL: Record<string, string> = { discovered: "Discovered", verified: "Verified", shortlisted: "Shortlisted", preparing: "Preparing", awaiting_approval: "Awaiting approval", submitted: "Submitted", interview: "Interview", offer: "Offer", rejected: "Rejected" };
const HINT: Record<string, string> = { discovered: "Found, not yet re-checked", verified: "Confirmed on the official source · top 25 by fit", shortlisted: "You want to apply", preparing: "Materials and form being prepared", awaiting_approval: "Filled form ready for you", submitted: "Sent after your approval", interview: "", offer: "", rejected: "" };
const APP_STATUS: Record<string, [string, string]> = { prepared: ["neutral", "Prepared"], awaiting_approval: ["accent", "Ready to review"], approved: ["info", "Approved · sending"], submitting: ["info", "Submitting"], submitted: ["good", "Sent"], failed: ["bad", "Failed"], needs_manual: ["warn", "Manual step"], submit_uncertain: ["bad", "Check manually"], changes_requested: ["warn", "Changes requested"], draft: ["neutral", "Draft"], declined: ["neutral", "Declined"] };

export default function PipelinePage() {
  const { data, error, reload } = useApi<any>("/pipeline", 12000);
  const { openJob, refreshKey, bump } = useShell();
  const toast = useToast();
  const [drag, setDrag] = useState<{ id: number; from: string } | null>(null);
  const [over, setOver] = useState("");
  const [confirm, setConfirm] = useState<{ card: any; from: string; to: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { reload(); }, [refreshKey, reload]);

  async function move(card: any, from: string, to: string, confirmed = false) {
    if (from === to) return;
    const needs = data.confirm_required.some((p: string[]) => p[0] === from && p[1] === to);
    if (needs && !confirmed) { setConfirm({ card, from, to }); return; }
    setBusy(true);
    try {
      await api(`/jobs/${card.id}/stage`, { body: { to, confirm: confirmed } });
      toast(`${card.company}: moved to ${LABEL[to] ?? titleCase(to)}.`);
      setConfirm(null); await reload(); bump();
    } catch (e: any) { toast(e.message, "error"); setConfirm(null); }
    finally { setBusy(false); }
  }

  if (error) return <ErrorNote>{error}</ErrorNote>;
  return (
    <div className="animate-in">
      <PageHeader title="Pipeline" subtitle="Each column is the real state of the job in the system. Drag a card or use its Move menu; submission only ever happens through approval." />
      {!data ? <div className="flex gap-3 overflow-hidden">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-[420px] w-[280px] shrink-0" />)}</div> : (
        <div className="-mx-4 overflow-x-auto px-4 pb-4 md:-mx-8 md:px-8">
          <div className="flex min-w-max gap-3">
            {data.stages.map((stage: string) => {
              const cards = data.columns[stage];
              const canDrop = drag && drag.from !== stage && (data.columns[drag.from].find((c: any) => c.id === drag.id)?.allowed_moves ?? []).includes(stage);
              return (
                <section key={stage} aria-label={LABEL[stage]}
                  onDragOver={(e) => { if (canDrop) { e.preventDefault(); setOver(stage); } }} onDragLeave={() => setOver((o) => (o === stage ? "" : o))}
                  onDrop={(e) => { e.preventDefault(); setOver(""); if (drag && canDrop) { const card = data.columns[drag.from].find((c: any) => c.id === drag.id); move(card, drag.from, stage); } setDrag(null); }}
                  className={cx("flex w-[286px] shrink-0 flex-col rounded-card border bg-surface/70 transition-colors", over === stage ? "border-accent/60 bg-accent/[.04]" : drag && !canDrop && drag.from !== stage ? "border-line opacity-50" : "border-line")}>
                  <header className="px-3.5 pb-2 pt-3">
                    <div className="flex items-center justify-between">
                      <h2 className="text-[13px] font-semibold">{LABEL[stage]}</h2>
                      <span className={cx("rounded-md px-1.5 py-0.5 text-[11px] font-medium tabular", stage === "awaiting_approval" && data.counts[stage] ? "bg-accent text-accent-ink" : "bg-white/[.06] text-ink-2")}>{data.counts[stage].toLocaleString()}</span>
                    </div>
                    {HINT[stage] && <p className="mt-0.5 text-[11px] text-ink-3">{HINT[stage]}</p>}
                  </header>
                  <ul className="flex max-h-[calc(100dvh-270px)] min-h-[120px] flex-col gap-2 overflow-y-auto px-2 pb-2">
                    {cards.length === 0 && <li className="rounded-xl border border-dashed border-line px-3 py-6 text-center text-xs text-ink-3">Empty</li>}
                    {cards.map((c: any) => {
                      const st = c.application ? APP_STATUS[c.application.status] : null;
                      return (
                        <li key={c.id} draggable={c.allowed_moves.length > 0} onDragStart={(e) => { setDrag({ id: c.id, from: stage }); e.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => { setDrag(null); setOver(""); }}
                          className={cx("group rounded-xl border border-line bg-raised p-3 transition-all hover:border-line-strong", drag?.id === c.id && "opacity-40", !c.is_active && "opacity-60")}>
                          <div className="flex items-start gap-1.5">
                            <GripVertical className="mt-0.5 size-3.5 shrink-0 cursor-grab text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                            <button onClick={() => openJob(c.id)} className="min-w-0 flex-1 text-left">
                              <span className="block truncate text-[11px] font-medium text-accent">{c.company}</span>
                              <span className="mt-0.5 line-clamp-2 text-[13px] font-medium leading-snug">{c.title}</span>
                              <span className="mt-1 block truncate text-[11px] text-ink-3">{c.location || "Location not stated"}</span>
                            </button>
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            <Stars value={c.fit_stars} size={11} /><VisaBadge status={c.visa_status} />
                            {!c.is_active && <Badge tone="bad">Closed</Badge>}{st && <Badge tone={st[0]}>{st[1]}</Badge>}
                          </div>
                          <div className="mt-2.5 flex items-center gap-2">
                            {c.application && <Link href={`/application/?id=${c.application.id}`} className="text-xs font-medium text-ink-2 hover:text-accent">Open application</Link>}
                            {c.allowed_moves.length > 0 && (
                              <Select aria-label={`Move ${c.title}`} value="" onChange={(e) => e.target.value && move(c, stage, e.target.value)} className="ml-auto h-7 w-[112px]! rounded-lg py-0 pl-2 pr-6 text-xs">
                                <option value="">Move to…</option>
                                {c.allowed_moves.map((m: string) => <option key={m} value={m}>{m === "archived" ? "Hide" : LABEL[m] ?? titleCase(m)}</option>)}
                              </Select>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title="Confirm this change"
        footer={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button variant="primary" loading={busy} onClick={() => confirm && move(confirm.card, confirm.from, confirm.to, true)}>Yes, move it</Button></>}>
        {confirm && <>Move <strong className="text-ink">{confirm.card.company} — {confirm.card.title}</strong> from <strong className="text-ink">{LABEL[confirm.from]}</strong> to <strong className="text-ink">{confirm.to === "archived" ? "hidden" : LABEL[confirm.to]}</strong>?{confirm.from === "awaiting_approval" && " Any approval for the current version will be cancelled."}</>}
      </Modal>
    </div>
  );
}
