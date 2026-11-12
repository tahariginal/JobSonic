import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="text-5xl font-semibold tracking-tight text-accent">404</p>
      <p className="text-sm text-ink-2">This page does not exist.</p>
      <Link href="/" className="rounded-[10px] border border-line bg-raised px-4 py-2 text-sm font-medium hover:bg-hover">Back to overview</Link>
    </main>
  );
}
