"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { EmailSummary } from "@/lib/types";
import { useResource } from "@/lib/useResource";
import { Badge, ErrorBox, Loading, fmt } from "@/components/ui";

const loadEmails = () => api.listEmails();
const anyInFlight = (emails: EmailSummary[]) =>
  emails.some((e) => e.triage_status === "queued" || e.triage_status === "running");

export default function InboxPage() {
  const load = useCallback(loadEmails, []);
  const { data, error, loading, reload } = useResource(load, anyInFlight);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState(false);

  async function run<T>(fn: () => Promise<T>, ok: (r: T) => string) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      setNotice(ok(await fn()));
      await reload();
    } catch (e) {
      setActionError(
        e instanceof ApiError && e.status === 403
          ? "Only an admin can load the sample inbox (the first registered account is the admin)."
          : e instanceof Error
            ? e.message
            : "Failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="row spread">
        <h1>Inbox</h1>
        <div className="row">
          <button disabled={busy} onClick={() => run(api.seedInbox, (r) => `Added ${r.added} sample emails (${r.total} in the sample set).`)}>
            Load sample inbox
          </button>
          <button className="primary" onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? "Close" : "Paste an email"}
          </button>
        </div>
      </div>

      {showAdd && (
        <form
          className="card"
          onSubmit={async (e) => {
            e.preventDefault();
            await run(() => api.addEmail({ raw_text: raw }), () => "Email added.");
            setRaw("");
            setShowAdd(false);
          }}
        >
          <label htmlFor="raw">Paste the email (optional From:/Subject: header lines, then the body)</label>
          <textarea id="raw" required value={raw} onChange={(e) => setRaw(e.target.value)} placeholder={"From: Ana <ana@example.test>\nSubject: Quick question\n\nCan we meet tomorrow?"} />
          <div style={{ marginTop: 10 }}>
            <button className="primary" disabled={busy || !raw.trim()} type="submit">
              Add to inbox
            </button>
          </div>
        </form>
      )}

      {notice && <div className="notice info">{notice}</div>}
      {actionError && <ErrorBox message={actionError} />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && <Loading what="Loading inbox" />}

      {data && data.length === 0 && (
        <div className="card muted">The inbox is empty. Load the sample inbox or paste an email to start.</div>
      )}

      {data && data.length > 0 && (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>From / Subject</th>
                <th>Received</th>
                <th>Triage</th>
                <th>Category</th>
                <th>Urgency</th>
                <th>Draft</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id}>
                  <td>
                    <Link href={`/emails/${e.id}`}>{e.subject}</Link>
                    <div className="muted">{e.sender}</div>
                  </td>
                  <td className="muted">{fmt(e.received_at)}</td>
                  <td>{e.triage_status ? <Badge value={e.triage_status} /> : <span className="muted">not run</span>}</td>
                  <td>
                    <Badge value={e.category} />
                  </td>
                  <td>
                    <Badge value={e.urgency} />
                  </td>
                  <td>
                    <Badge value={e.draft_status} />
                  </td>
                  <td>
                    {(e.triage_status === null || e.triage_status === "failed") && (
                      <button disabled={busy} onClick={() => run(() => api.triage(e.id), () => `Triage started for "${e.subject}".`)}>
                        {e.triage_status === "failed" ? "Retry" : "Triage"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
