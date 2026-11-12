"use client";
import { Activity, BarChart3, Bell, Briefcase, CheckCheck, ClipboardCheck, KanbanSquare, LayoutDashboard, LogOut, Menu, Radar, Settings, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, setCsrf, timeAgo } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { JobDrawer } from "./JobDrawer";
import { Logo } from "./Logo";
import { Button, cx, Drawer, ToastProvider, useToast } from "./ui";

type ShellCtx = { openJob: (id: number) => void; refreshKey: number; bump: () => void; searching: boolean; runSearch: () => void };
const Ctx = createContext<ShellCtx>({ openJob: () => {}, refreshKey: 0, bump: () => {}, searching: false, runSearch: () => {} });
export const useShell = () => useContext(Ctx);

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/jobs/", label: "Jobs", icon: Briefcase },
  { href: "/pipeline/", label: "Pipeline", icon: KanbanSquare },
  { href: "/approvals/", label: "Approvals", icon: ClipboardCheck, badge: true },
  { href: "/activity/", label: "Activity", icon: Activity },
  { href: "/analytics/", label: "Analytics", icon: BarChart3 },
  { href: "/profile/", label: "Profile", icon: UserRound },
  { href: "/settings/", label: "Settings", icon: Settings },
];
const isActive = (path: string, href: string) => (href === "/" ? path === "/" : path.startsWith(href.replace(/\/$/, "")));

export function Shell({ children }: { children: React.ReactNode }) {
  return <ToastProvider><ShellInner>{children}</ShellInner></ToastProvider>;
}

function ShellInner({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const toast = useToast();
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [more, setMore] = useState(false);
  const bump = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    api("/auth/me").then((d) => { setCsrf(d.csrf_token); setUser(d.username); setReady(true); }).catch(() => { window.location.href = "/login/"; });
  }, []);

  const approvals = useApi<any>(ready ? "/approvals" : null, 20000);
  const live = useApi<any>(ready ? "/events?limit=1" : null, 6000);
  const tasks: any[] = live.data?.tasks ?? [];
  const searching = tasks.some((t) => t.type === "discovery");
  const wasBusy = useRef(false);
  useEffect(() => {
    const busy = tasks.length > 0;
    if (wasBusy.current && !busy) { bump(); approvals.reload(); }
    wasBusy.current = busy;
  }, [tasks.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const runSearch = useCallback(async () => {
    try { await api("/discovery/run", { body: {} }); toast("Job search started."); live.reload(); }
    catch (e: any) { toast(e.message, "error"); }
  }, [toast, live]);

  async function logout() { try { await api("/auth/logout", { method: "POST" }); } finally { window.location.href = "/login/"; } }

  if (!ready) return <div className="flex min-h-dvh items-center justify-center"><div className="pulse-dot"><Logo /></div></div>;
  const awaiting = approvals.data?.awaiting?.length ?? 0;
  const taskLabel: Record<string, string> = { discovery: "Searching jobs", prepare_application: "Preparing application", fill_form: "Filling form", submit_application: "Submitting", verify_open: "Verifying vacancies", ai_evaluate: "AI evaluating", email_sync: "Syncing email", reanalyze: "Re-scoring jobs", telegram_send: "Sending alert" };
  const current = tasks.find((t) => t.status === "running") ?? tasks[0];

  return (
    <Ctx.Provider value={{ openJob: setJobId, refreshKey, bump, searching, runSearch }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[80] focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-ink">Skip to content</a>
      <div className="flex min-h-dvh">
        {/* desktop sidebar */}
        <aside className="sticky top-0 hidden h-dvh w-[232px] shrink-0 flex-col border-r border-line bg-surface/60 md:flex">
          <div className="px-5 py-5"><Link href="/" aria-label="SONIC JOBS home"><Logo /></Link></div>
          <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
            {NAV.map((n) => {
              const active = isActive(path, n.href);
              return (
                <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                  className={cx("group relative flex items-center gap-3 rounded-[10px] px-3 py-2 text-[13.5px] font-medium transition-colors", active ? "bg-hover text-ink" : "text-ink-3 hover:bg-raised hover:text-ink-2")}>
                  {active && <span className="absolute -left-3 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent" />}
                  <n.icon className={cx("size-[17px]", active && "text-accent")} strokeWidth={1.9} aria-hidden />
                  {n.label}
                  {n.badge && awaiting > 0 && <span className="ml-auto rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-[18px] text-accent-ink tabular">{awaiting}</span>}
                </Link>
              );
            })}
          </nav>
          <div className="border-t border-line p-3">
            <div className="flex items-center justify-between rounded-[10px] px-2 py-1.5">
              <span className="truncate text-[13px] text-ink-2">{user}</span>
              <button onClick={logout} aria-label="Sign out" title="Sign out" className="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-hover hover:text-ink"><LogOut className="size-4" /></button>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur-md md:px-8">
            <Link href="/" className="md:hidden" aria-label="SONIC JOBS home"><Logo compact /></Link>
            <div className="flex min-w-0 flex-1 items-center gap-2 text-[13px] text-ink-3" aria-live="polite">
              {current ? (
                <><span className="size-2 shrink-0 rounded-full bg-accent pulse-dot" /><span className="truncate text-ink-2">{taskLabel[current.type] ?? current.type}…</span>{tasks.length > 1 && <span className="hidden sm:inline">+{tasks.length - 1} queued</span>}</>
              ) : (<><span className="size-2 shrink-0 rounded-full bg-good" /><span className="truncate">Idle · automation ready</span></>)}
            </div>
            <Button size="sm" variant="secondary" onClick={runSearch} loading={searching} icon={<Radar className="size-4" />}><span className="hidden sm:inline">{searching ? "Searching" : "Run search"}</span></Button>
            <Notifications onOpenJob={setJobId} onNavigate={(href) => router.push(href)} />
          </header>
          <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 pb-28 pt-6 md:px-8 md:pb-12 md:pt-8">{children}</main>
        </div>
      </div>

      {/* mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden" aria-label="Main">
        {[NAV[0], NAV[1], NAV[3], NAV[2]].map((n) => {
          const active = isActive(path, n.href);
          return (
            <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined} className={cx("relative flex h-[58px] flex-col items-center justify-center gap-1 text-[10.5px] font-medium", active ? "text-accent" : "text-ink-3")}>
              <n.icon className="size-5" strokeWidth={1.9} aria-hidden />{n.label}
              {n.badge && awaiting > 0 && <span className="absolute right-[26%] top-1.5 rounded-full bg-accent px-1.5 text-[10px] font-bold leading-4 text-accent-ink">{awaiting}</span>}
            </Link>
          );
        })}
        <button onClick={() => setMore(true)} className={cx("flex h-[58px] flex-col items-center justify-center gap-1 text-[10.5px] font-medium", NAV.slice(4).some((n) => isActive(path, n.href)) ? "text-accent" : "text-ink-3")}>
          <Menu className="size-5" strokeWidth={1.9} aria-hidden />More
        </button>
      </nav>
      <Drawer open={more} onClose={() => setMore(false)} title="More">
        <div className="space-y-1 p-3">
          {NAV.slice(4).map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setMore(false)} className="flex items-center gap-3 rounded-xl px-3 py-3.5 text-[15px] text-ink-2 hover:bg-hover"><n.icon className="size-5 text-ink-3" aria-hidden />{n.label}</Link>
          ))}
          <button onClick={logout} className="flex w-full items-center gap-3 rounded-xl px-3 py-3.5 text-[15px] text-ink-2 hover:bg-hover"><LogOut className="size-5 text-ink-3" aria-hidden />Sign out ({user})</button>
        </div>
      </Drawer>
      <JobDrawer id={jobId} onClose={() => setJobId(null)} />
    </Ctx.Provider>
  );
}

function Notifications({ onOpenJob, onNavigate }: { onOpenJob: (id: number) => void; onNavigate: (href: string) => void }) {
  const [open, setOpen] = useState(false);
  const { data, reload } = useApi<any>("/notifications", 15000);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const unread = data?.unread ?? 0;
  async function markAll() { await api("/notifications/read", { body: {} }); reload(); }
  async function go(n: any) {
    setOpen(false);
    if (!n.read) { api("/notifications/read", { body: { ids: [n.id] } }).then(reload); }
    if (n.application_id) onNavigate(`/application/?id=${n.application_id}`);
    else if (n.job_id) onOpenJob(n.job_id);
  }
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} aria-expanded={open}
        className="relative rounded-[10px] border border-line bg-raised p-2 text-ink-2 transition-colors hover:border-line-strong hover:text-ink">
        <Bell className="size-4" />
        {unread > 0 && <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-accent px-1 text-center text-[10px] font-bold leading-4 text-accent-ink">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-50 w-[min(380px,calc(100vw-24px))] animate-in overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-2xl shadow-black/70">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="text-sm font-semibold">Notifications</span>
            {unread > 0 && <button onClick={markAll} className="inline-flex items-center gap-1 text-xs text-ink-3 hover:text-accent"><CheckCheck className="size-3.5" />Mark all read</button>}
          </div>
          <ul className="max-h-[60vh] overflow-y-auto">
            {(data?.items ?? []).length === 0 && <li className="px-4 py-10 text-center text-[13px] text-ink-3">Nothing yet. Alerts for strong matches, approvals and replies appear here.</li>}
            {(data?.items ?? []).map((n: any) => (
              <li key={n.id}>
                <button onClick={() => go(n)} className="flex w-full gap-3 border-b border-line/60 px-4 py-3 text-left transition-colors hover:bg-hover">
                  <span className={cx("mt-1.5 size-2 shrink-0 rounded-full", n.read ? "bg-transparent" : "bg-accent")} />
                  <span className="min-w-0 flex-1">
                    <span className={cx("block truncate text-[13px]", n.read ? "text-ink-2" : "font-medium text-ink")}>{n.title}</span>
                    {n.body && <span className="mt-0.5 line-clamp-2 text-xs text-ink-3">{n.body}</span>}
                    <span className="mt-1 block text-[11px] text-ink-3">{timeAgo(n.created_at)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
