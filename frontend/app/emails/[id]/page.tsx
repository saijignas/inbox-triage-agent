"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { EmailDetail } from "@/lib/types";
import { useResource } from "@/lib/useResource";
import { Badge, ErrorBox, Loading, fmt } from "@/components/ui";

const inFlight = (e: EmailDetail) => e.triage?.status === "queued" || e.triage?.status === "running";

export default function EmailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const load = useCallback(() => api.getEmail(id), [id]);
  const { data: email, error, loading, reload } = useResource(load, inFlight);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function startTriage() {
    setBusy(true);
    setActionError(null);
    try {
      await api.triage(id);
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to start triage");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading what="Loading email" />;
  if (error && !email) return <ErrorBox message={error} onRetry={reload} />;
  if (!email) return null;
  const t = email.triage;

  return (
    <>
      <p>
        <Link href="/">&larr; Inbox</Link>
      </p>
      <h1>{email.subject}</h1>
      <div className="card">
        <div className="muted">
          From {email.sender} &middot; {fmt(email.received_at)}
        </div>
        <p className="body-text">{email.body}</p>
      </div>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {actionError && <ErrorBox message={actionError} />}

      <div className="card">
        <div className="row spread">
          <h2>Triage result</h2>
          {(!t || t.status === "failed") && (
            <button className="primary" disabled={busy} onClick={startTriage}>
              {t ? "Retry triage" : "Run triage"}
            </button>
          )}
        </div>
        {!t && <p className="muted">This email has not been triaged yet.</p>}
        {t && (
          <>
            <div className="row">
              <Badge value={t.status} />
              <Badge value={t.category} />
              <Badge value={t.urgency} />
              <span className="muted">
                reply needed: {t.needs_reply === null ? "-" : t.needs_reply ? "yes" : "no"} &middot; provider: {t.provider ?? "-"} &middot; attempts: {t.attempts}
              </span>
            </div>
            {(t.status === "queued" || t.status === "running") && <Loading what="Agent is working" />}
            {t.summary && <p>{t.summary}</p>}
            {t.status === "failed" && (
              <div className="notice error">
                Triage failed ({t.error_code}): {t.error_message}. Nothing was drafted. You can retry.
              </div>
            )}
          </>
        )}
      </div>

      {email.tasks.length > 0 && (
        <div className="card">
          <h2>Action items</h2>
          <ul>
            {email.tasks.map((task) => (
              <li key={task.id}>
                {task.description} <Badge value={task.priority} />
                {task.due_hint && <span className="muted"> due: {task.due_hint}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {email.draft && (
        <div className="card">
          <div className="row spread">
            <h2>Draft reply</h2>
            <Badge value={email.draft.status} />
          </div>
          <p className="body-text">{email.draft.final_body}</p>
          <Link href="/drafts">Review in the drafts queue &rarr;</Link>
        </div>
      )}

      {t && t.trace.length > 0 && (
        <div className="card" style={{ overflowX: "auto" }}>
          <h2>Agent trace</h2>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Tool</th>
                <th>Arguments</th>
                <th>Result / error</th>
                <th>ms</th>
              </tr>
            </thead>
            <tbody>
              {t.trace.map((s, i) => (
                <tr key={`${s.step}-${i}`}>
                  <td>{s.step}</td>
                  <td>{s.tool}</td>
                  <td>
                    <pre>{JSON.stringify(s.args, null, 1)}</pre>
                  </td>
                  <td>
                    {s.error ? (
                      <span style={{ color: "var(--bad)" }}>{s.error}</span>
                    ) : (
                      <pre>{typeof s.result === "string" ? s.result : JSON.stringify(s.result, null, 1)}</pre>
                    )}
                  </td>
                  <td>{Math.round(s.latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
