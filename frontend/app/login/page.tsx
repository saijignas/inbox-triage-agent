"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { ErrorBox } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") await api.register(email, password);
      await api.login(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 380, margin: "40px auto" }}>
      <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
      {mode === "register" && (
        <p className="muted">The first account created becomes the admin (can load the sample inbox).</p>
      )}
      {error && <ErrorBox message={error} />}
      <form onSubmit={submit}>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">Password (8+ characters)</label>
        <input
          id="password"
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="row spread" style={{ marginTop: 16 }}>
          <button className="primary" disabled={busy} type="submit">
            {busy ? "Working..." : mode === "login" ? "Sign in" : "Register"}
          </button>
          <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Need an account?" : "Have an account?"}
          </button>
        </div>
      </form>
    </div>
  );
}
