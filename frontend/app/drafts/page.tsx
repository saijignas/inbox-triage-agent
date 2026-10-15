"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { Draft, DraftStatus } from "@/lib/types";
import { useResource } from "@/lib/useResource";
import { Badge, ErrorBox, Loading, fmt } from "@/components/ui";

type Filter = DraftStatus | "all";
const FILTERS: Filter[] = ["pending", "approved", "rejected", "all"];

function DraftCard({ draft, onChanged }: { draft: Draft; onChanged: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(draft.final_body);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pending = draft.status === "pending";

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      setEditing(false);
      await onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
      await onChanged(); // state may have changed under us (409): refresh
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="row spread">
        <div>
          <Link href={`/emails/${draft.email_id}`}>
            <strong>Re: {draft.email_subject}</strong>
          </Link>
          <div className="muted">
            To {draft.email_sender} &middot; tone: {draft.tone} &middot; {fmt(draft.created_at)}
          </div>
        </div>
        <Badge value={draft.status} />
      </div>

      {err && <ErrorBox message={err} />}

      {editing ? (
        <textarea aria-label="Draft text" value={text} onChange={(e) => setText(e.target.value)} />
      ) : (
        <p className="body-text">{draft.final_body}</p>
      )}
      {draft.edited_body !== null && !editing && <p className="muted">Edited by a human before review.</p>}

      {pending ? (
        <div className="row">
          {editing ? (
            <>
              <button className="primary" disabled={busy || !text.trim()} onClick={() => act(() => api.editDraft(draft.id, text))}>
                Save edit
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  setText(draft.final_body);
                  setEditing(false);
                }}
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button className="primary" disabled={busy} onClick={() => act(() => api.approveDraft(draft.id))}>
                Approve
              </button>
              <button className="danger" disabled={busy} onClick={() => act(() => api.rejectDraft(draft.id))}>
                Reject
              </button>
              <button disabled={busy} onClick={() => setEditing(true)}>
                Edit
              </button>
            </>
          )}
        </div>
      ) : (
        <p className="muted">Decision recorded {draft.decided_at ? fmt(draft.decided_at) : ""}. Decided drafts are final.</p>
      )}
    </div>
  );
}

export default function DraftsPage() {
  const [filter, setFilter] = useState<Filter>("pending");
  const load = useCallback(() => api.listDrafts(filter === "all" ? undefined : filter), [filter]);
  const { data, error, loading, reload } = useResource(load);

  return (
    <>
      <h1>Drafts queue</h1>
      <div className="notice info">
        Nothing is ever sent automatically. Approving a draft only records that a human accepted the text; this app has no send
        capability.
      </div>
      <div className="row" style={{ marginBottom: 14 }}>
        {FILTERS.map((f) => (
          <button key={f} className={f === filter ? "primary" : ""} onClick={() => setFilter(f)}>
            {f}
          </button>
        ))}
      </div>

      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && <Loading what="Loading drafts" />}
      {data && data.length === 0 && <div className="card muted">No {filter === "all" ? "" : filter} drafts.</div>}
      {data?.map((d) => (
        <DraftCard key={`${d.id}-${d.status}-${d.edited_body ?? ""}`} draft={d} onChanged={reload} />
      ))}
    </>
  );
}
