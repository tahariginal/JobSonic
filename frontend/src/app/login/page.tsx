"use client";
import { Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { Button, ErrorNote, Input, Label } from "@/components/ui";
import { api } from "@/lib/api";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hydrated, setHydrated] = useState(false); // the form only becomes usable once scripts are running
  useEffect(() => setHydrated(true), []);
  useEffect(() => { api("/auth/me").then(() => { window.location.href = "/"; }).catch(() => {}); }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try { await api("/auth/login", { body: { username, password } }); window.location.href = "/"; }
    catch (err: any) { setError(err.message ?? "Sign-in failed"); setBusy(false); }
  }
  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden px-5">
      <div className="pointer-events-none absolute -top-40 left-1/2 size-[560px] -translate-x-1/2 rounded-full bg-accent/[.07] blur-[120px]" aria-hidden />
      <div className="relative w-full max-w-sm animate-in">
        <div className="mb-8 flex justify-center"><Logo /></div>
        <form onSubmit={submit} className="rounded-2xl border border-line bg-surface p-6 shadow-2xl shadow-black/50">
          <h1 className="text-lg font-semibold tracking-tight">Sign in</h1>
          <p className="mt-1 text-[13px] text-ink-3">Private control center. Single account.</p>
          <div className="mt-5 space-y-4">
            <div><Label htmlFor="u">Username</Label><Input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus /></div>
            <div><Label htmlFor="p">Password</Label><Input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
            {error && <ErrorNote>{error}</ErrorNote>}
            <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!hydrated} className="w-full" icon={<Lock className="size-4" />}>Sign in</Button>
          </div>
        </form>
      </div>
    </main>
  );
}
