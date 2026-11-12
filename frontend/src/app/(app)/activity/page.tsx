"use client";
import { useEffect, useRef, useState } from "react";
import { EventRow } from "@/components/EventRow";
import { useShell } from "@/components/Shell";
import { Card, Chip, Empty, ErrorNote, PageHeader, Skeleton } from "@/components/ui";
import { api, titleCase } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const FILTERS = [["", "All"], ["discovery", "Search"], ["verify", "Verification"], ["ai", "AI"], ["prepare", "Preparation"], ["form", "Forms"], ["approval", "Approvals"], ["submit", "Submission"], ["email", "Email"]];

export default function ActivityPage() {
  const [type, setType] = useState("");
  const [events, setEvents] = useState<any[] | null>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const [error, setError] = useState("");
  const { openJob } = useShell();
  const lastId = useRef(0);
  const recent = useApi<any[]>("/tasks", 10000);

  useEffect(() => {
    let alive = true;
    lastId.current = 0;
    setEvents(null);
    async function tick(initial: boolean) {
      try {
        const d = await api(`/events?limit=${initial ? 120 : 60}${lastId.current ? `&after=${lastId.current}` : ""}${type ? `&type=${type}` : ""}`);
        if (!alive) return;
        setTasks(d.tasks);
        if (d.events.length) lastId.current = Math.max(lastId.current, ...d.events.map((e: any) => e.id));
        setEvents((prev) => (initial || !prev ? d.events : [...d.events, ...prev].slice(0, 400)));
        setError("");
      } catch (e: any) { if (alive) setError(e.message); }
    }
    tick(true);
    const t = setInterval(() => { if (document.visibilityState === "visible") tick(false); }, 4000);
    return () => { alive = false; clearInterval(t); };
  }, [type]);

  return (
    <div className="animate-in">
      <PageHeader title="Activity" subtitle="Live feed of what the system is actually doing. Updates every few seconds." />
      {error && <div className="mb-4"><ErrorNote>{error}</ErrorNote></div>}
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div>
          <div className="mb-3 flex flex-wrap gap-2">{FILTERS.map(([v, l]) => <Chip key={v} active={type === v} onClick={() => setType(v)}>{l}</Chip>)}</div>
          <Card className="p-2">
            {events === null ? <div className="space-y-2 p-3">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-11" />)}</div>
              : events.length === 0 ? <Empty title="No events for this filter">Events appear as soon as the worker does something.</Empty>
                : <ul aria-live="polite">{events.map((e) => <EventRow key={e.id} e={e} onOpenJob={openJob} />)}</ul>}
          </Card>
        </div>
        <div className="space-y-4">
          <Card className="p-4">
            <h2 className="text-[13px] font-semibold">Running now</h2>
            {tasks.length === 0 ? <p className="mt-2 flex items-center gap-2 text-[13px] text-ink-3"><span className="size-2 rounded-full bg-good" />Worker idle</p>
              : <ul className="mt-2 space-y-2">{tasks.map((t) => <li key={t.id} className="flex items-center gap-2 text-[13px]"><span className={`size-2 rounded-full ${t.status === "running" ? "bg-accent pulse-dot" : "bg-ink-3"}`} /><span className="text-ink-2">{titleCase(t.type)}</span><span className="ml-auto text-xs text-ink-3">{t.status}</span></li>)}</ul>}
          </Card>
          <Card className="p-4">
            <h2 className="text-[13px] font-semibold">Recent background runs</h2>
            <ul className="mt-2 space-y-1.5">
              {(recent.data ?? []).slice(0, 12).map((t) => (
                <li key={t.id} className="flex items-center gap-2 text-[13px]" title={t.error || undefined}>
                  <span className={`size-1.5 rounded-full ${t.status === "done" ? "bg-good" : t.status === "failed" ? "bg-bad" : "bg-accent"}`} />
                  <span className="truncate text-ink-2">{titleCase(t.type)}</span>
                  <span className="ml-auto shrink-0 text-xs text-ink-3">{t.status === "failed" ? "failed" : t.status}</span>
                </li>
              ))}
              {recent.data?.length === 0 && <li className="text-[13px] text-ink-3">None yet.</li>}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
