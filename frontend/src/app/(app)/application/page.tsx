"use client";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Copy, ExternalLink, FileText, Lock, MousePointerClick, PenLine, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";
import { EventRow } from "@/components/EventRow";
import { Evidence, Reasons } from "@/components/JobDrawer";
import { useShell } from "@/components/Shell";
import { Badge, Button, Callout, Card, cx, Empty, ErrorNote, Input, Modal, Select, Skeleton, Stars, Tabs, Textarea, useToast, VisaBadge } from "@/components/ui";
import { api, fmtDate, titleCase } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const SRC: Record<string, [string, string]> = { profile: ["good", "From your profile"], standard: ["good", "Your standard answer"], generated: ["info", "Generated — check it"], manual: ["accent", "Edited by you"], skipped: ["neutral", "Left unanswered"], "": ["warn", "Needs your input"] };
const STATUS: Record<string, [string, string]> = { draft: ["neutral", "Draft"], prepared: ["neutral", "Prepared"], awaiting_approval: ["accent", "Awaiting your approval"], approved: ["info", "Approved — queued to send"], submitting: ["info", "Submitting now"], submitted: ["good", "Submitted"], failed: ["bad", "Submission failed — nothing sent"], needs_manual: ["warn", "Manual step needed"], submit_uncertain: ["bad", "Outcome unknown — check manually"], changes_requested: ["warn", "Changes requested"], declined: ["neutral", "Declined by you"] };
const LOCKED = ["submitted", "submitting", "submit_uncertain"];

export default function ApplicationPage() {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { setId(new URLSearchParams(window.location.search).get("id") ?? ""); }, []);
  const { data: a, error, reload, setData } = useApi<any>(id ? `/applications/${id}` : null, 5000);
  const { bump, openJob } = useShell();
  const toast = useToast();
  const [tab, setTab] = useState<"review" | "form" | "job" | "history" | "emails">("review");
  const [edits, setEdits] = useState<Record<string, any>>({});
  const [letter, setLetter] = useState<string | null>(null);
  const [cvId, setCvId] = useState<number | null>(null);
  const [busy, setBusy] = useState("");
  const [dialog, setDialog] = useState<"" | "approve" | "reject" | "changes" | "manual" | "notsent">("");
  const [comment, setComment] = useState("");
  const [zoom, setZoom] = useState<number | null>(null);
  const docs = useApi<any[]>("/documents");
  const dirty = Object.keys(edits).length > 0 || letter !== null || cvId !== null;
  const cvs = useMemo(() => (docs.data ?? []).filter((d) => d.kind === "cv"), [docs.data]);

  async function run(name: string, fn: () => Promise<any>, ok?: string) {
    setBusy(name);
    try { const r = await fn(); if (r && r.id) setData(r); else await reload(); if (ok) toast(ok); bump(); setDialog(""); setComment(""); return true; }
    catch (e: any) { toast(e.message, "error"); await reload(); return false; }
    finally { setBusy(""); }
  }
  async function save() {
    const ok = await run("save", () => api(`/applications/${a.id}`, { method: "PUT", body: { cover_letter: letter ?? undefined, cv_document_id: cvId ?? undefined, answers: Object.entries(edits).map(([key, value]) => ({ key, value })) } }), "Saved as a new version.");
    if (ok) { setEdits({}); setLetter(null); setCvId(null); }
  }

  if (id === "") return <Empty title="No application selected" action={<Link href="/approvals/"><Button>Go to approvals</Button></Link>} />;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!a) return <div className="space-y-3"><Skeleton className="h-8 w-72" /><Skeleton className="h-24" /><Skeleton className="h-96" /></div>;

  const locked = LOCKED.includes(a.status) || a.status === "approved";
  const [tone, label] = STATUS[a.status] ?? ["neutral", a.status];
  const working = ["approved", "submitting"].includes(a.status);
  const blocking = a.issues.filter((i: any) => i.blocking);
  const fr = a.fill_report;
  const filledKeys = new Set((fr?.filled ?? []).map((f: any) => f.key));
  const latestShot = a.screenshots[0];
  const copyAll = () => { navigator.clipboard.writeText(a.answers.filter((x: any) => typeof x.value === "string" && x.value).map((x: any) => `${x.label}\n${x.value}`).join("\n\n")).then(() => toast("Answers copied.")); };

  return (
    <div className="animate-in mx-auto max-w-4xl">
      <Link href="/approvals/" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink"><ArrowLeft className="size-4" />Approvals</Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-accent">{a.company}</p>
          <h1 className="mt-0.5 text-[22px] font-semibold leading-tight tracking-tight">{a.title}</h1>
          <p className="mt-1.5 text-[13px] text-ink-3">{a.location || "Location not stated"} · version {a.revision} · <span className="font-mono text-xs">{a.content_hash.slice(0, 10)}</span></p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Badge tone={tone} className="px-2 py-1 text-xs">{working && <span className="size-1.5 rounded-full bg-info pulse-dot" />}{label}</Badge>
            <Stars value={a.fit_stars} /><VisaBadge status={a.visa_status} label={a.job.visa_label} />{!a.is_active && <Badge tone="bad">Vacancy closed</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => openJob(a.job_id)}>Job details</Button>
          <a href={a.apply_url} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-2.5 text-[13px] font-medium hover:border-line-strong hover:bg-hover">Official form<ExternalLink className="size-3.5 text-ink-3" /></a>
        </div>
      </div>

      {/* state panel */}
      <div className="mt-5 space-y-3">
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div><p className="text-[13px] font-medium">Application mode</p><p className="text-xs text-ink-3">Automatic applications use your saved settings. Manual applications wait for your review.</p></div>
          <Select aria-label="Application mode" className="w-44" value={a.automation_mode ?? "manual"} disabled={LOCKED.includes(a.status) || a.status === "declined" || !!busy || dirty}
            onChange={(e) => run("mode", () => api(`/applications/${a.id}/mode`, { method: "PUT", body: { mode: e.target.value } }), "Application mode saved.")}>
            <option value="automatic">Automatic</option><option value="manual">Manual</option>
          </Select>
        </Card>
        {a.status === "submitted" && (
          <Callout tone="info" title={`Submitted ${fmtDate(a.submitted_at)} ${a.submitted_via === "manual" ? "(marked manually by you)" : a.automation_mode === "automatic" ? "by the automatic application cycle" : "by the agent after your approval"}`}>
            {a.confirmation?.confirmation_text && <>Confirmation shown by the site: “{a.confirmation.confirmation_text}”. </>}
            {a.confirmation?.email ? <>Confirmation email received: “{a.confirmation.email.subject}”.</> : "No confirmation email matched yet."}
          </Callout>
        )}
        {a.status === "submit_uncertain" && (
          <Callout tone="bad" title="The outcome of this submission is unknown" action={<div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => setDialog("manual")}>It was sent</Button><Button size="sm" onClick={() => setDialog("notsent")}>It was not sent</Button></div>}>
            {a.last_error} It will never be retried automatically. Check your inbox or the employer's site, then record what happened.
          </Callout>
        )}
        {a.status === "needs_manual" && (
          <Callout tone="warn" title="This form needs you" action={<div className="flex flex-wrap gap-2"><Button size="sm" icon={<Copy className="size-3.5" />} onClick={copyAll}>Copy answers</Button><Button size="sm" onClick={() => setDialog("manual")}>Mark as submitted</Button></div>}>
            {a.last_error} Open the official form, paste the prepared answers, complete the human check yourself, then mark it as submitted here.
          </Callout>
        )}
        {a.status === "failed" && <Callout tone="bad" title="Submission failed before anything was sent">{a.last_error} The approval was cancelled. Fill the form again and re-approve.</Callout>}
        {a.status === "prepared" && a.last_error && <Callout tone="warn" title="The last form attempt did not complete">{a.last_error}</Callout>}
        {blocking.length > 0 && !locked && (
          <Callout tone="warn" title={`${blocking.length} item${blocking.length > 1 ? "s" : ""} need your input before this can proceed`}>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">{blocking.map((i: any, k: number) => <li key={k}>{i.text}{i.code === "profile_gap" || i.code === "no_cv" ? <> <Link href="/profile/" className="text-accent hover:underline">Open profile</Link></> : null}</li>)}</ul>
          </Callout>
        )}
        {["prepared", "changes_requested", "failed", "needs_manual"].includes(a.status) && blocking.length === 0 && !dirty && (
          <Callout title="Ready to fill the official form" action={<Button variant="primary" loading={busy === "fill"} icon={<MousePointerClick className="size-4" />} onClick={() => run("fill", () => api(`/applications/${a.id}/fill`, { method: "POST" }), "Opening the form in the background…")}>{a.automation_mode === "automatic" ? "Continue automatically" : "Fill form for review"}</Button>}>
            {a.automation_mode === "automatic" ? "The agent fills the form using these answers and follows your automatic submission setting." : "The agent opens the employer's form, enters these answers, takes a screenshot and stops for your review."}
          </Callout>
        )}
      </div>

      <div className="mt-6"><Tabs value={tab} onChange={setTab} items={[{ id: "review", label: "What will be sent" }, { id: "form", label: "Form screenshots", count: a.screenshots.length }, { id: "job", label: "Job & evidence" }, { id: "history", label: "History" }, { id: "emails", label: "Emails", count: a.emails.length }]} /></div>

      {tab === "review" && (
        <div className="mt-4 space-y-4">
          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl border border-line bg-raised text-ink-3"><FileText className="size-5" /></span>
                <div><p className="text-xs text-ink-3">CV to upload</p>{a.cv ? <p className="text-sm font-medium">{a.cv.label} <span className="font-normal text-ink-3">· {a.cv.filename}</span></p> : <p className="text-sm font-medium text-warn">No CV selected</p>}</div>
              </div>
              <div className="flex items-center gap-2">
                {a.cv && <a href={`/api/documents/${a.cv.id}/download`} className="text-xs font-medium text-ink-3 hover:text-accent">Download</a>}
                {!locked && cvs.length > 0 && <Select aria-label="Replace CV" className="h-8 w-48 text-[13px]" value={cvId ?? a.cv?.id ?? ""} onChange={(e) => setCvId(Number(e.target.value) === a.cv?.id ? null : Number(e.target.value))}>{!a.cv && <option value="">Choose a CV…</option>}{cvs.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}</Select>}
              </div>
            </div>
          </Card>

          <Card className="p-5">
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="text-[13px] font-semibold">Cover letter</h2>
              <Badge tone={a.materials_source === "ai" ? "info" : a.materials_source === "edited" ? "accent" : "neutral"}>{{ ai: "Written by AI from your profile", template: "Built from your profile (no AI)", edited: "Edited by you" }[a.materials_source as string] ?? a.materials_source}</Badge>
            </div>
            <Textarea rows={11} disabled={locked} value={letter ?? a.cover_letter} onChange={(e) => setLetter(e.target.value === a.cover_letter ? null : e.target.value)} aria-label="Cover letter" className="font-sans text-[13.5px]" />
            <p className="mt-1.5 text-xs text-ink-3">Used wherever the form has a cover-letter text field. {(letter ?? a.cover_letter).trim().split(/\s+/).filter(Boolean).length} words.</p>
          </Card>

          <Card>
            <div className="flex items-center justify-between gap-3 px-5 pt-4"><h2 className="text-[13px] font-semibold">Form answers</h2><Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={copyAll}>Copy all</Button></div>
            <ul className="mt-2 divide-y divide-line/70">
              {a.answers.map((x: any) => {
                const val = x.key in edits ? edits[x.key] : x.value;
                const missing = x.required && (val === null || val === "" || val === undefined) && x.source !== "skipped" && x.type !== "info";
                const [st, sl] = SRC[x.key in edits ? "manual" : x.source] ?? SRC[""];
                const editable = !locked && !["file", "info"].includes(x.type);
                const setV = (v: any) => setEdits((e) => { const n = { ...e }; if (v === x.value || (v === "" && x.value === null)) delete n[x.key]; else n[x.key] = v; return n; });
                return (
                  <li key={x.key} className={cx("px-5 py-3.5", missing && "bg-warn/[.05]")}>
                    <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-[13px] font-medium text-ink">{x.label || x.key}{x.required && <span className="ml-0.5 text-accent" title="Required">*</span>}</span>
                      <Badge tone={missing ? "warn" : st}>{missing ? "Needs your input" : sl}</Badge>
                      {x.discovered && <Badge>Found on live form</Badge>}
                      {fr && a.fill_is_current && x.type !== "info" && (filledKeys.has(x.key) ? <Badge tone="good"><Check className="size-3" />Entered in form</Badge> : val ? <Badge tone="warn" title="This field was not found on the live form, so it will not be sent.">Not placed</Badge> : null)}
                    </div>
                    {x.type === "file" ? <p className="text-[13px] text-ink-2">{x.value?.filename ?? <span className="text-ink-3">No file</span>}</p>
                      : x.type === "info" ? <p className="text-[13px] text-ink-3">Not answered.</p>
                        : !editable ? <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink-2">{val === true ? "Yes (ticked)" : Array.isArray(val) ? val.join(", ") : val || <span className="text-ink-3">—</span>}</p>
                          : x.type === "checkbox" ? <label className="flex items-center gap-2.5 text-[13.5px] text-ink-2"><input type="checkbox" className="size-4 accent-[#ffd60a]" checked={val === true} onChange={(e) => setV(e.target.checked ? true : null)} />I have read this and agree (will be ticked in the form)</label>
                            : x.options?.length > 0 ? <Select aria-label={x.label} value={val ?? ""} onChange={(e) => setV(e.target.value || null)} className="max-w-md"><option value="">Not answered</option>{x.options.map((o: string) => <option key={o} value={o}>{o}</option>)}</Select>
                              : x.type === "textarea" || (typeof val === "string" && val.length > 80) ? <Textarea rows={Math.min(9, Math.max(3, Math.ceil(String(val ?? "").length / 90)))} aria-label={x.label} value={val ?? ""} onChange={(e) => setV(e.target.value)} />
                                : <Input aria-label={x.label} value={val ?? ""} onChange={(e) => setV(e.target.value)} className="max-w-md" />}
                    {x.note && <p className="mt-1.5 text-xs text-ink-3">{x.note}</p>}
                  </li>
                );
              })}
            </ul>
          </Card>
        </div>
      )}

      {tab === "form" && (
        <div className="mt-4 space-y-4">
          {fr && (
            <Card className="p-5">
              <h2 className="text-[13px] font-semibold">Last form run</h2>
              <p className="mt-1 text-[13px] text-ink-2">{fr.mode === "fill" ? "Filled for review" : "Submission"} · {fmtDate(fr.finished_at)} · {fr.filled?.length ?? 0} field{fr.filled?.length === 1 ? "" : "s"} entered{!a.fill_is_current && <span className="text-warn"> · made for an older version</span>}</p>
              {fr.error && <p className="mt-2 text-[13px] text-[#f19191]">{fr.error}</p>}
              {fr.blockers?.recaptcha_present && !fr.blockers?.captcha && <p className="mt-2 text-xs text-ink-3">This site uses background bot protection. If it challenges the submission, the agent stops and hands over to you; it does not attempt to get around it.</p>}
              {fr.unfilled?.length > 0 && <div className="mt-3"><p className="text-xs font-medium text-ink-3">Not placed in the form</p><ul className="mt-1 list-disc pl-4 text-[13px] text-ink-2">{fr.unfilled.map((u: any, i: number) => <li key={i}>{u.label || u.key}: {u.reason}</li>)}</ul></div>}
              {fr.final_url && <p className="mt-2 truncate text-xs text-ink-3">Page: {fr.final_url}</p>}
            </Card>
          )}
          {a.screenshots.length === 0 ? <Card><Empty icon={<MousePointerClick className="size-5" />} title="No screenshots yet">A full-page screenshot is saved every time the agent fills or submits the form.</Empty></Card> : (
            <div className="grid gap-3 sm:grid-cols-2">
              {a.screenshots.map((s: any) => (
                <button key={s.id} onClick={() => setZoom(s.id)} className="group overflow-hidden rounded-card border border-line bg-surface text-left transition-colors hover:border-line-strong">
                  <div className="h-56 overflow-hidden bg-white"><img src={`/api/screenshots/${s.id}`} alt={`Form screenshot, ${s.kind}`} loading="lazy" className="w-full object-cover object-top transition-transform duration-300 group-hover:scale-[1.02]" /></div>
                  <div className="flex items-center justify-between px-3.5 py-2.5 text-xs"><span className="font-medium text-ink-2">{{ filled: "Filled for review", pre_submit: "Just before submit", confirmation: "Confirmation page", error: "Problem" }[s.kind as string] ?? s.kind} · v{s.revision}</span><span className="text-ink-3">{fmtDate(s.created_at)}</span></div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "job" && (
        <div className="mt-4 space-y-4">
          <Card className="p-5"><h2 className="mb-2 text-[13px] font-semibold">Why you fit</h2><p className="text-[13.5px] leading-relaxed text-ink-2">{a.fit_reason}</p>{a.fit_pitch && <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{a.fit_pitch}</p>}</Card>
          <Card className="p-5"><h2 className="mb-3 text-[13px] font-semibold">Visa evidence</h2><Evidence items={a.job.visa_evidence} /></Card>
          <Card className="p-5"><h2 className="mb-3 text-[13px] font-semibold">Eligibility</h2><Reasons items={a.job.eligibility_reasons} /></Card>
          <Card className="p-5"><h2 className="mb-2 text-[13px] font-semibold">Job description</h2><p className="mb-2 text-xs text-ink-3">Last verified {fmtDate(a.job.last_verified_at)} · <a className="hover:text-accent" href={a.job.canonical_url} target="_blank" rel="noopener noreferrer">{a.job.canonical_url}</a></p><pre className="max-h-[520px] overflow-y-auto whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-ink-2">{a.job.description}</pre></Card>
        </div>
      )}

      {tab === "history" && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Card className="p-5">
            <h2 className="mb-3 text-[13px] font-semibold">Approval history</h2>
            {a.approvals.length === 0 ? <p className="text-[13px] text-ink-3">No decisions yet.</p> : <ul className="space-y-2.5">{a.approvals.map((e: any, i: number) => (
              <li key={i} className="flex gap-2.5 text-[13px]"><span className={cx("mt-1.5 size-2 shrink-0 rounded-full", { approve: "bg-good", reject: "bg-bad", request_changes: "bg-warn", invalidated: "bg-ink-3" }[e.action as string])} />
                <span><span className="font-medium">{{ approve: "Approved", reject: "Declined", request_changes: "Changes requested", invalidated: "Approval cancelled" }[e.action as string]}</span> <span className="text-ink-3">· v{e.revision} · <span className="font-mono text-xs">{e.hash}</span> · {fmtDate(e.created_at)}</span>{e.comment && <span className="block text-ink-2">{e.comment}</span>}</span></li>))}</ul>}
            <h2 className="mb-3 mt-6 text-[13px] font-semibold">Versions of the material</h2>
            <ul className="space-y-1.5">{a.versions.map((v: any, i: number) => <li key={i} className="flex justify-between gap-3 text-[13px]"><span className="text-ink-2">v{v.revision} · {v.reason}</span><span className="shrink-0 text-xs text-ink-3">{fmtDate(v.created_at)}</span></li>)}</ul>
          </Card>
          <Card className="p-2"><h2 className="px-3 pb-1 pt-3 text-[13px] font-semibold">Timeline</h2><ul>{a.timeline.map((e: any) => <EventRow key={e.id} e={{ ...e, application_id: null }} />)}</ul></Card>
        </div>
      )}

      {tab === "emails" && (
        <Card className="mt-4">
          {a.emails.length === 0 ? <Empty title="No recruiter emails matched yet">Connect Gmail (read-only) in Settings to track confirmations, interview invitations and replies for this application.</Empty> : (
            <ul className="divide-y divide-line/70">{a.emails.map((m: any) => (
              <li key={m.id} className="px-5 py-3.5">
                <div className="flex flex-wrap items-center gap-2"><Badge tone={{ interview: "accent", offer: "good", rejection: "bad", confirmation: "info", documents: "warn" }[m.category as string] ?? "neutral"}>{titleCase(m.category)}</Badge><span className="text-xs text-ink-3">{Math.round(m.confidence * 100)}% sure · matched {Math.round(m.match_confidence * 100)}% ({m.match_reason}) · {fmtDate(m.received_at)}</span></div>
                <p className="mt-1.5 text-[13.5px] font-medium">{m.subject}</p><p className="text-xs text-ink-3">{m.from}</p><p className="mt-1 text-[13px] text-ink-2">{m.snippet}</p>
              </li>))}</ul>
          )}
        </Card>
      )}

      {/* sticky action bar */}
      {(dirty || a.status === "awaiting_approval") && (
        <div className="sticky bottom-[70px] z-20 mt-6 md:bottom-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line-strong bg-raised/95 p-3 shadow-2xl shadow-black/60 backdrop-blur">
            {dirty ? (
              <><p className="flex items-center gap-2 px-1 text-[13px] text-ink-2"><PenLine className="size-4 text-accent" />Unsaved changes. Saving creates a new version{a.approved_revision || a.status === "awaiting_approval" ? " and the form must be filled and approved again" : ""}.</p>
                <div className="flex gap-2"><Button onClick={() => { setEdits({}); setLetter(null); setCvId(null); }}>Discard</Button><Button variant="primary" loading={busy === "save"} onClick={save}>Save changes</Button></div></>
            ) : (
              <><p className="flex items-center gap-2 px-1 text-[13px] text-ink-2"><Lock className="size-4 text-accent" />Version {a.revision} is filled in the official form and waiting for you.</p>
                <div className="flex flex-1 flex-wrap justify-end gap-2">
                  <Button variant="danger" icon={<X className="size-4" />} onClick={() => setDialog("reject")}>Reject</Button>
                  <Button onClick={() => setDialog("changes")}>Request changes</Button>
                  <Button variant="primary" size="lg" className="max-sm:w-full" icon={<CheckCircle2 className="size-5" />} onClick={() => setDialog("approve")}>Approve &amp; submit</Button>
                </div></>
            )}
          </div>
        </div>
      )}

      <Modal open={dialog === "approve"} onClose={() => setDialog("")} title="Approve and submit this application?"
        footer={<><Button onClick={() => setDialog("")}>Cancel</Button><Button variant="primary" loading={busy === "approve"} icon={<CheckCircle2 className="size-4" />} onClick={() => run("approve", () => api(`/applications/${a.id}/approve`, { body: { revision: a.revision, content_hash: a.content_hash, comment } }), "Approved. Submitting now…")}>Approve &amp; submit</Button></>}>
        <p>You are approving <strong className="text-ink">version {a.revision}</strong> for <strong className="text-ink">{a.company} — {a.title}</strong>. The agent will open the official form, enter exactly these answers, upload <strong className="text-ink">{a.cv?.filename}</strong> and press submit <strong className="text-ink">once</strong>.</p>
        <p className="mt-2 flex gap-2 rounded-lg border border-line bg-raised p-2.5 text-xs"><ShieldAlert className="size-4 shrink-0 text-accent" />This sends a real application under your name. It cannot be undone. If anything changes before sending, the approval is cancelled.</p>
        {latestShot && <img src={`/api/screenshots/${latestShot.id}`} alt="Filled form preview" className="mt-3 max-h-40 w-full rounded-lg border border-line object-cover object-top" />}
      </Modal>
      <Modal open={dialog === "reject" || dialog === "changes" || dialog === "manual" || dialog === "notsent"} onClose={() => setDialog("")}
        title={{ reject: "Reject this application?", changes: "Request changes", manual: "Mark as submitted", notsent: "Confirm nothing was sent" }[dialog as string] ?? ""}
        footer={<><Button onClick={() => setDialog("")}>Cancel</Button>
          {dialog === "reject" && <Button variant="danger" loading={busy === "reject"} onClick={() => run("reject", () => api(`/applications/${a.id}/reject`, { body: { comment } }), "Application declined.")}>Reject</Button>}
          {dialog === "changes" && <Button variant="primary" loading={busy === "changes"} onClick={() => run("changes", () => api(`/applications/${a.id}/request-changes`, { body: { comment } }), "Sent back for changes.")}>Request changes</Button>}
          {dialog === "manual" && <Button variant="primary" loading={busy === "manual"} onClick={() => run("manual", () => api(`/applications/${a.id}/mark-submitted`, { body: { comment } }), "Marked as submitted.")}>I submitted it</Button>}
          {dialog === "notsent" && <Button variant="primary" loading={busy === "notsent"} onClick={() => run("notsent", () => api(`/applications/${a.id}/mark-not-sent`, { body: { comment } }), "Cleared. A new approval is required.")}>Nothing was sent</Button>}</>}>
        <p>{{ reject: "The job is removed from your pipeline and nothing is sent.", changes: "The application goes back to Preparing. Edit the answers, then fill the form again.", manual: "Use this only after you completed and sent the form yourself on the employer's site.", notsent: "Use this only after checking that the employer did not receive the application. You will need to approve it again." }[dialog as string]}</p>
        <Textarea rows={3} className="mt-3" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Optional note for your records" aria-label="Note" />
      </Modal>
      {zoom !== null && (
        <div className="fixed inset-0 z-[70] overflow-auto bg-black/90 p-4" onClick={() => setZoom(null)} role="dialog" aria-label="Screenshot">
          <button className="fixed right-4 top-4 rounded-full border border-line bg-raised p-2 text-ink" aria-label="Close screenshot" autoFocus onKeyDown={(e) => e.key === "Escape" && setZoom(null)}><X className="size-5" /></button>
          <img src={`/api/screenshots/${zoom}`} alt="Form screenshot, full size" className="mx-auto max-w-full rounded-lg" />
        </div>
      )}
    </div>
  );
}
