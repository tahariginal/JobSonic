"use client";
import { ArrowDownUp, Bookmark, BookmarkCheck, ChevronLeft, ChevronRight, ExternalLink, Search, SlidersHorizontal, X } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { useShell } from "@/components/Shell";
import { Badge, Button, Card, Chip, cx, EligibilityBadge, Empty, ErrorNote, Input, PageHeader, Select, Skeleton, Stars, Tabs, useToast, VisaBadge } from "@/components/ui";
import { api, timeAgo, titleCase } from "@/lib/api";
import { useApi, useDebounced } from "@/lib/hooks";

type F = { view: string; q: string; country: string; region: string; visa: string; level: string; family: string; remote: string; min_stars: string; days: string; sort: string; new_only: boolean; page: number; eligibility: string };
const DEFAULTS: F = { view: "matches", q: "", country: "", region: "", visa: "", level: "", family: "", remote: "", min_stars: "", days: "", sort: "fit", new_only: false, page: 1, eligibility: "" };
const VIEW_ELIG: Record<string, string> = { matches: "eligible|needs_review", eligible: "eligible", review: "needs_review", filtered: "rejected", saved: "", all: "" };
const REGION: Record<string, string> = { europe: "Europe", asia: "Asia", middle_east: "Middle East", north_america: "North America", africa: "Africa", oceania: "Oceania", latam: "Latin America", "": "Unspecified" };
const LEVEL: Record<string, string> = { junior: "Junior / entry", intern: "Internship", unknown: "Not stated", mid: "Mid-level", senior: "Senior" };
const VISA: Record<string, string> = { confirmed: "Confirmed", conditional: "Conditional", not_required: "Not needed", unverified: "Unverified", not_supported: "Not supported" };
const FAMILY: Record<string, string> = { applied_ai: "Applied AI", backend: "Backend", fullstack: "Full-stack", mobile: "Mobile", platform: "Platform", automation: "Automation", software: "Software (general)", frontend: "Frontend" };

export default function JobsPage() {
  const [f, setF] = useState<F>(DEFAULTS);
  const [hydrated, setHydrated] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const { openJob, refreshKey } = useShell();
  const toast = useToast();
  const q = useDebounced(f.q, 300);

  useEffect(() => { // initial state from the URL (deep links from the overview)
    const sp = new URLSearchParams(window.location.search);
    const next: any = { ...DEFAULTS };
    sp.forEach((v, k) => { if (k in next) next[k] = k === "page" ? Number(v) || 1 : k === "new_only" ? v === "true" : v; });
    if (sp.get("eligibility")) next.view = Object.entries(VIEW_ELIG).find(([, e]) => e === sp.get("eligibility"))?.[0] ?? "matches";
    setF(next); setHydrated(true);
  }, []);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    const elig = VIEW_ELIG[f.view];
    if (elig) p.set("eligibility", elig);
    if (f.view === "saved") p.set("saved", "true");
    if (q) p.set("q", q);
    for (const k of ["country", "region", "visa", "level", "family", "remote", "min_stars", "days"] as const) if (f[k]) p.set(k, f[k]);
    if (f.new_only) p.set("new_only", "true");
    p.set("sort", f.sort); p.set("page", String(f.page)); p.set("page_size", "40");
    return p.toString();
  }, [f, q]);
  useEffect(() => { if (hydrated) window.history.replaceState(null, "", `?${query.replace(/&?page_size=40/, "")}`); }, [query, hydrated]);

  const { data, error, loading, reload, setData } = useApi<any>(hydrated ? `/jobs?${query}` : null);
  const facets = useApi<any>("/jobs/facets");
  useEffect(() => { if (hydrated) { reload(); facets.reload(); } }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch: Partial<F>) => setF((x) => ({ ...x, page: 1, ...patch }));
  const activeFilters = (["country", "region", "visa", "level", "family", "remote", "min_stars", "days"] as const).filter((k) => f[k]).length + (f.new_only ? 1 : 0);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const showReasons = f.view === "filtered" || f.view === "review" || f.view === "all";

  async function toggleSave(j: any, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      const r = await api(`/jobs/${j.id}`, { method: "PATCH", body: { saved: !j.saved } });
      setData((d: any) => ({ ...d, items: d.items.map((x: any) => (x.id === j.id ? { ...x, saved: r.saved } : x)) }));
    } catch (err: any) { toast(err.message, "error"); }
  }
  const opt = (name: string, labels?: Record<string, string>) => (facets.data?.[name] ?? []).filter((x: any) => x.value !== "" || labels?.[""]).map((x: any) => <option key={String(x.value)} value={x.value}>{labels?.[x.value] ?? x.value} ({x.count})</option>);

  return (
    <div className="animate-in">
      <PageHeader title="Jobs" subtitle={data ? `${data.total.toLocaleString()} job${data.total === 1 ? "" : "s"} in this view · every listing links to the employer's official posting` : "Loading…"} />
      <Tabs value={f.view} onChange={(v) => set({ view: v })} items={[
        { id: "matches", label: "Matches" }, { id: "eligible", label: "Eligible" }, { id: "review", label: "Needs review" },
        { id: "saved", label: "Saved" }, { id: "filtered", label: "Filtered out" }, { id: "all", label: "All" }]} />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <Input value={f.q} onChange={(e) => set({ q: e.target.value })} placeholder="Search company, role, location…" aria-label="Search jobs" className="pl-9" />
          {f.q && <button onClick={() => set({ q: "" })} aria-label="Clear search" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-3 hover:text-ink"><X className="size-3.5" /></button>}
        </div>
        <Button onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters} icon={<SlidersHorizontal className="size-4" />}>Filters{activeFilters > 0 && <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-ink">{activeFilters}</span>}</Button>
        <div className="flex items-center gap-2">
          <ArrowDownUp className="size-4 text-ink-3" aria-hidden />
          <Select aria-label="Sort" value={f.sort} onChange={(e) => set({ sort: e.target.value })} className="w-40">
            <option value="fit">Best fit</option><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="salary">Salary</option><option value="company">Company A–Z</option><option value="title">Role A–Z</option>
          </Select>
        </div>
      </div>

      {showFilters && (
        <Card className="mt-3 animate-in p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Fld label="Country"><Select value={f.country} onChange={(e) => set({ country: e.target.value })}><option value="">Any country</option>{opt("country")}</Select></Fld>
            <Fld label="Region"><Select value={f.region} onChange={(e) => set({ region: e.target.value })}><option value="">Any region</option>{opt("region", REGION)}</Select></Fld>
            <Fld label="Visa sponsorship"><Select value={f.visa} onChange={(e) => set({ visa: e.target.value })}><option value="">Any status</option><option value="confirmed|conditional|not_required">Confirmed, conditional or not needed</option>{opt("visa_status", VISA)}</Select></Fld>
            <Fld label="Experience level"><Select value={f.level} onChange={(e) => set({ level: e.target.value })}><option value="">Any level</option><option value="junior|unknown">Junior or not stated</option>{opt("experience_level", LEVEL)}</Select></Fld>
            <Fld label="Minimum fit"><Select value={f.min_stars} onChange={(e) => set({ min_stars: e.target.value })}><option value="">Any rating</option>{[5, 4, 3, 2].map((s) => <option key={s} value={s}>{"★".repeat(s)}{s < 5 ? " and up" : ""}</option>)}</Select></Fld>
            <Fld label="Role type"><Select value={f.family} onChange={(e) => set({ family: e.target.value })}><option value="">Any role</option>{opt("role_family", FAMILY)}</Select></Fld>
            <Fld label="Work mode"><Select value={f.remote} onChange={(e) => set({ remote: e.target.value })}><option value="">Any mode</option>{opt("remote_mode", { remote: "Remote", hybrid: "Hybrid", onsite: "On-site", unknown: "Not stated" })}</Select></Fld>
            <Fld label="Discovered"><Select value={f.days} onChange={(e) => set({ days: e.target.value })}><option value="">Any time</option><option value="1">Last 24 hours</option><option value="3">Last 3 days</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option></Select></Fld>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Chip active={f.new_only} onClick={() => set({ new_only: !f.new_only })}>New &amp; unseen only</Chip>
            {activeFilters > 0 && <Button size="sm" variant="ghost" onClick={() => setF((x) => ({ ...DEFAULTS, view: x.view, q: x.q, sort: x.sort }))}>Clear filters</Button>}
          </div>
        </Card>
      )}

      {error && <div className="mt-4"><ErrorNote>{error}</ErrorNote></div>}

      {/* desktop table */}
      <Card className="mt-4 hidden overflow-hidden lg:block">
        <table className="w-full table-fixed text-left text-[13px]">
          <thead>
            <tr className="border-b border-line text-[11px] uppercase tracking-[0.08em] text-ink-3">
              <th className="w-[13%] px-4 py-3 font-medium">Company</th><th className="w-[19%] px-3 py-3 font-medium">Role</th><th className="px-3 py-3 font-medium">What you'll do</th>
              <th className="w-[92px] px-3 py-3 font-medium">Fit</th><th className="w-[11%] px-3 py-3 font-medium">Salary</th><th className="w-[14%] px-3 py-3 font-medium">Location / Mode</th>
              <th className="w-[118px] px-3 py-3 font-medium">Visa</th><th className="w-[92px] px-3 py-3 text-right font-medium">Apply</th>
            </tr>
          </thead>
          <tbody>
            {loading && !data && Array.from({ length: 8 }).map((_, i) => <tr key={i} className="border-b border-line/60"><td colSpan={8} className="px-4 py-3"><Skeleton className="h-9" /></td></tr>)}
            {data?.items.map((j: any) => (
              <tr key={j.id} tabIndex={0} onClick={() => openJob(j.id)} onKeyDown={(e) => { if (e.key === "Enter") openJob(j.id); }}
                className={cx("group cursor-pointer border-b border-line/60 align-top transition-colors last:border-0 hover:bg-raised focus-visible:bg-raised", !j.is_active && "opacity-55")}>
                <td className="px-4 py-3"><span className="font-medium text-ink">{j.company}</span><span className="mt-0.5 block text-[11px] text-ink-3">{timeAgo(j.discovered_at)}</span></td>
                <td className="px-3 py-3">
                  <span className="line-clamp-2 font-medium text-ink group-hover:text-accent">{j.title}</span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {j.is_new && <Badge tone="accent">New</Badge>}{j.is_updated && <Badge tone="info">Updated</Badge>}{!j.is_active && <Badge tone="bad">Closed</Badge>}
                    {f.view !== "eligible" && f.view !== "filtered" && j.eligibility !== "eligible" && <EligibilityBadge value={j.eligibility} />}
                    {j.stage !== "verified" && j.stage !== "discovered" && <Badge>{titleCase(j.stage)}</Badge>}
                  </span>
                </td>
                <td className="px-3 py-3 text-ink-2">
                  <span className="line-clamp-2">{j.summary || <span className="text-ink-3">Not extracted</span>}</span>
                  {showReasons && (j.rejection_reasons.length > 0 || j.review_reasons.length > 0) && (
                    <span className={cx("mt-1 line-clamp-2 text-xs", j.rejection_reasons.length ? "text-[#f19191]" : "text-[#f08a5d]")}>{(j.rejection_reasons.length ? j.rejection_reasons : j.review_reasons).join(" ")}</span>
                  )}
                </td>
                <td className="px-3 py-3" title={j.fit_reason}><Stars value={j.fit_stars} /></td>
                <td className="px-3 py-3 text-ink-2">{j.salary_text || <span className="text-ink-3">Not stated</span>}</td>
                <td className="px-3 py-3"><span className="line-clamp-2 text-ink-2">{j.location || "—"}</span><span className="text-[11px] text-ink-3">{j.remote_mode === "unknown" ? "Mode not stated" : titleCase(j.remote_mode)}</span></td>
                <td className="px-3 py-3"><VisaBadge status={j.visa_status} label={j.visa_label} /></td>
                <td className="px-3 py-3">
                  <span className="flex items-center justify-end gap-1">
                    <button onClick={(e) => toggleSave(j, e)} aria-label={j.saved ? "Remove from saved" : "Save job"} aria-pressed={j.saved} className="rounded-lg p-1.5 text-ink-3 hover:bg-hover hover:text-ink">{j.saved ? <BookmarkCheck className="size-4 text-accent" /> : <Bookmark className="size-4" />}</button>
                    <a href={j.apply_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} aria-label={`Open official posting for ${j.title}`} className="rounded-lg p-1.5 text-ink-3 hover:bg-hover hover:text-accent"><ExternalLink className="size-4" /></a>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.items.length === 0 && <NoJobs view={f.view} filtered={activeFilters > 0 || !!q} />}
      </Card>

      {/* mobile / tablet cards */}
      <div className="mt-4 space-y-2.5 lg:hidden">
        {loading && !data && Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-32" />)}
        {data?.items.map((j: any) => (
          <button key={j.id} onClick={() => openJob(j.id)} className={cx("block w-full rounded-card border border-line bg-surface p-4 text-left transition-colors active:bg-raised", !j.is_active && "opacity-55")}>
            <span className="flex items-start justify-between gap-3">
              <span className="min-w-0"><span className="block text-xs font-medium text-accent">{j.company}</span><span className="mt-0.5 block text-[15px] font-medium leading-snug">{j.title}</span></span>
              <Stars value={j.fit_stars} />
            </span>
            <span className="mt-1.5 line-clamp-2 text-[13px] text-ink-2">{j.summary}</span>
            {showReasons && j.rejection_reasons.length > 0 && <span className="mt-1 block text-xs text-[#f19191]">{j.rejection_reasons[0]}</span>}
            <span className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <VisaBadge status={j.visa_status} label={j.visa_label} />
              {j.is_new && <Badge tone="accent">New</Badge>}{j.eligibility !== "eligible" && <EligibilityBadge value={j.eligibility} />}
              <span className="text-xs text-ink-3">{j.location || "Location not stated"}{j.salary_text && ` · ${j.salary_text}`}</span>
            </span>
          </button>
        ))}
        {data?.items.length === 0 && <Card><NoJobs view={f.view} filtered={activeFilters > 0 || !!q} /></Card>}
      </div>

      {data && data.total > data.page_size && (
        <div className="mt-4 flex items-center justify-between text-[13px] text-ink-3">
          <span className="tabular">{(data.page - 1) * data.page_size + 1}–{Math.min(data.total, data.page * data.page_size)} of {data.total.toLocaleString()}</span>
          <span className="flex items-center gap-2">
            <Button size="sm" disabled={f.page <= 1} onClick={() => { setF((x) => ({ ...x, page: x.page - 1 })); window.scrollTo({ top: 0 }); }} icon={<ChevronLeft className="size-4" />}>Previous</Button>
            <span className="tabular">Page {f.page} / {pages}</span>
            <Button size="sm" disabled={f.page >= pages} onClick={() => { setF((x) => ({ ...x, page: x.page + 1 })); window.scrollTo({ top: 0 }); }}>Next<ChevronRight className="size-4" /></Button>
          </span>
        </div>
      )}
    </div>
  );
}

function Fld({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-xs font-medium text-ink-3">{label}</span>{children}</label>;
}
function NoJobs({ view, filtered }: { view: string; filtered: boolean }) {
  return <Empty icon={<Search className="size-5" />} title={filtered ? "No jobs match these filters" : view === "saved" ? "No saved jobs yet" : "Nothing here yet"}>
    {filtered ? "Try removing a filter or switching to the “All” tab." : view === "saved" ? "Use the bookmark on any job to keep it here." : "Run a job search from the top bar. Results appear here as sources are checked."}
  </Empty>;
}
