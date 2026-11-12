export function Logo({ compact }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="flex size-7 items-center justify-center rounded-lg bg-accent text-accent-ink shadow-[0_0_18px_-4px_rgba(255,214,10,.7)]" aria-hidden>
        <svg viewBox="0 0 24 24" className="size-4" fill="currentColor"><path d="M13.5 2 4 13.5h6.2L9 22l10-12h-6.4z" /></svg>
      </span>
      {!compact && <span className="text-[15px] font-semibold tracking-[0.14em]">SONIC<span className="ml-1.5 font-normal text-ink-3">JOBS</span></span>}
    </span>
  );
}
