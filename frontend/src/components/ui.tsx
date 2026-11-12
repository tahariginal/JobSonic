"use client";
import { Check, Loader2, Star, X } from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");

/* ---------- Button ---------- */
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" | "lg"; loading?: boolean; icon?: React.ReactNode };
export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }: BtnProps) {
  const v = {
    primary: "bg-accent text-accent-ink hover:brightness-110 active:brightness-95 font-semibold shadow-[0_0_0_1px_rgba(255,214,10,.3),0_6px_20px_-8px_rgba(255,214,10,.55)]",
    secondary: "bg-raised text-ink border border-line hover:bg-hover hover:border-line-strong",
    ghost: "text-ink-2 hover:text-ink hover:bg-hover",
    danger: "bg-bad/10 text-bad border border-bad/30 hover:bg-bad/20",
  }[variant];
  const s = { sm: "h-8 px-2.5 text-[13px] gap-1.5 rounded-lg", md: "h-9 px-3.5 text-sm gap-2 rounded-[10px]", lg: "h-12 px-5 text-[15px] gap-2 rounded-xl" }[size];
  return (
    <button {...rest} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center whitespace-nowrap font-medium transition-all duration-150 active:scale-[.98] disabled:opacity-45 disabled:pointer-events-none", v, s, className)}>
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

/* ---------- Card ---------- */
export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cx("rounded-card border border-line bg-surface", className)}>{children}</div>;
}
export function CardHeader({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
      </div>
      {action}
    </div>
  );
}

/* ---------- Badges ---------- */
const TONES: Record<string, string> = {
  good: "bg-good/12 text-[#4fd1a5] border-good/25", warn: "bg-warn/12 text-[#f08a5d] border-warn/25", bad: "bg-bad/12 text-[#f19191] border-bad/25",
  info: "bg-info/12 text-[#7fb2f0] border-info/25", unknown: "bg-unknown/12 text-[#b3abf2] border-unknown/25",
  accent: "bg-accent/12 text-accent border-accent/30", neutral: "bg-white/[.04] text-ink-2 border-line",
};
export function Badge({ tone = "neutral", children, className, title }: { tone?: keyof typeof TONES | string; children: React.ReactNode; className?: string; title?: string }) {
  return <span title={title} className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap", TONES[tone] ?? TONES.neutral, className)}>{children}</span>;
}
export const VISA_TONE: Record<string, string> = { confirmed: "good", conditional: "warn", unverified: "unknown", not_supported: "bad", not_required: "info" };
export const VISA_COLOR: Record<string, string> = { confirmed: "var(--color-good)", conditional: "var(--color-warn)", not_required: "var(--color-info)", not_supported: "var(--color-bad)", unverified: "var(--color-unknown)" };
export function VisaBadge({ status, label }: { status: string; label?: string }) {
  const text = label ?? { confirmed: "Confirmed", conditional: "Conditional", unverified: "Unverified", not_supported: "Not supported", not_required: "Not needed" }[status] ?? status;
  return <Badge tone={VISA_TONE[status]} title={`Visa sponsorship: ${text}`}><span className="size-1.5 rounded-full" style={{ background: VISA_COLOR[status] }} />{text}</Badge>;
}
export function EligibilityBadge({ value }: { value: string }) {
  const m: Record<string, [string, string]> = { eligible: ["good", "Eligible"], needs_review: ["warn", "Needs review"], rejected: ["bad", "Filtered out"], unevaluated: ["neutral", "Unevaluated"] };
  const [tone, label] = m[value] ?? ["neutral", value];
  return <Badge tone={tone}>{label}</Badge>;
}
export function Stars({ value, size = 13 }: { value: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-[2px]" role="img" aria-label={`Fit ${value} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => <Star key={i} width={size} height={size} strokeWidth={1.6} className={i <= value ? "fill-accent text-accent" : "text-line-strong"} aria-hidden />)}
    </span>
  );
}

/* ---------- Form controls ---------- */
const field = "w-full rounded-[10px] border border-line bg-raised px-3 text-sm text-ink placeholder:text-ink-3 transition-colors hover:border-line-strong focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20";
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} {...p} className={cx(field, "h-9", className)} />;
});
export function Textarea({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...p} className={cx(field, "py-2 leading-relaxed", className)} />;
}
export function Select({ className, children, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...p} className={cx(field, "h-9 appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%237c7c87%22 stroke-width=%222.5%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-[right_0.7rem_center] bg-no-repeat pr-8", className)}>{children}</select>;
}
export function Label({ children, hint, htmlFor }: { children: React.ReactNode; hint?: string; htmlFor?: string }) {
  return <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-ink-2">{children}{hint && <span className="ml-1.5 font-normal text-ink-3">{hint}</span>}</label>;
}
export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={cx("relative h-6 w-11 shrink-0 rounded-full border transition-colors duration-200 disabled:opacity-40", checked ? "border-accent bg-accent" : "border-line-strong bg-raised")}>
      <span className={cx("absolute top-[3px] size-4 rounded-full transition-all duration-200", checked ? "left-[22px] bg-accent-ink" : "left-[3px] bg-ink-3")} />
    </button>
  );
}
export function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick}
      className={cx("inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-all", active ? "border-accent/50 bg-accent/12 text-accent" : "border-line bg-raised text-ink-2 hover:border-line-strong hover:text-ink")}>
      {active && <Check className="size-3.5" aria-hidden />}{children}
    </button>
  );
}

/* ---------- Feedback ---------- */
export function Skeleton({ className }: { className?: string }) { return <div className={cx("skeleton", className)} aria-hidden />; }
export function Empty({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-3 flex size-11 items-center justify-center rounded-xl border border-line bg-raised text-ink-3">{icon}</div>}
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <p className="mt-1 max-w-sm text-[13px] leading-relaxed text-ink-3">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
export function ErrorNote({ children }: { children: React.ReactNode }) {
  return <div role="alert" className="rounded-[10px] border border-bad/30 bg-bad/10 px-3.5 py-2.5 text-[13px] text-[#f3a3a3]">{children}</div>;
}
export function Callout({ tone = "accent", title, children, action }: { tone?: "accent" | "warn" | "bad" | "info"; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  const t = { accent: "border-accent/30 bg-accent/[.06]", warn: "border-warn/30 bg-warn/[.07]", bad: "border-bad/30 bg-bad/[.07]", info: "border-info/30 bg-info/[.07]" }[tone];
  return (
    <div className={cx("flex flex-wrap items-center justify-between gap-3 rounded-card border px-4 py-3", t)}>
      <div className="min-w-0"><p className="text-sm font-medium text-ink">{title}</p>{children && <div className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{children}</div>}</div>
      {action}
    </div>
  );
}

/* ---------- Toasts ---------- */
type Toast = { id: number; text: string; tone: "ok" | "error" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "error") => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[70] flex flex-col items-center gap-2 px-4 md:bottom-6" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cx("pointer-events-auto flex max-w-md animate-up items-start gap-2.5 rounded-xl border px-4 py-2.5 text-[13px] shadow-2xl shadow-black/60 backdrop-blur",
            t.tone === "error" ? "border-bad/40 bg-[#2a1414]/95 text-[#f6b4b4]" : "border-line-strong bg-raised/95 text-ink")}>
            <span className={cx("mt-1 size-2 shrink-0 rounded-full", t.tone === "error" ? "bg-bad" : "bg-accent")} />{t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- Overlay (drawer on desktop, sheet on mobile) & modal ---------- */
function useOverlay(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab" && ref.current) {
        const f = ref.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])');
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    setTimeout(() => ref.current?.focus(), 20);
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; prev?.focus?.(); };
  }, [open, onClose]);
  return ref;
}
export function Drawer({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  const ref = useOverlay(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 animate-in bg-black/65 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className={cx("absolute inset-x-0 bottom-0 top-10 flex animate-up flex-col rounded-t-2xl border border-line bg-surface shadow-2xl outline-none md:inset-y-0 md:left-auto md:right-0 md:top-0 md:animate-slide md:rounded-none md:border-y-0 md:border-r-0", wide ? "md:w-[min(820px,92vw)]" : "md:w-[min(640px,92vw)]")}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 className="truncate text-sm font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-ink-3 transition-colors hover:bg-hover hover:text-ink"><X className="size-4" /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </div>
    </div>
  );
}
export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode }) {
  const ref = useOverlay(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div className="absolute inset-0 animate-in bg-black/70 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className="relative w-full max-w-md animate-up rounded-t-2xl border border-line bg-surface p-5 shadow-2xl outline-none sm:rounded-2xl">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        <div className="mt-2 text-[13px] leading-relaxed text-ink-2">{children}</div>
        {footer && <div className="mt-5 flex flex-wrap justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight md:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: string; count?: number }[] }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line">
      {items.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("relative whitespace-nowrap px-3 py-2.5 text-[13px] font-medium transition-colors", value === t.id ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
          {t.label}{t.count !== undefined && <span className="ml-1.5 rounded bg-white/[.06] px-1.5 py-px text-[11px] tabular text-ink-2">{t.count}</span>}
          {value === t.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
        </button>
      ))}
    </div>
  );
}
