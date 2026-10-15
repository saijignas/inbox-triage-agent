import type {
  Draft,
  DraftStatus,
  EmailDetail,
  EmailSummary,
  NewEmail,
  TriageStarted,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "triage_token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const tokenStore = {
  get(): string | null {
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string): void {
    window.localStorage.setItem(TOKEN_KEY, token);
  },
  clear(): void {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

/** FastAPI errors are {detail: string} or {detail: [{loc, msg}, ...]} for validation failures. */
function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join("; ") || fallback;
  }
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${BASE}. Is the backend running?`);
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) tokenStore.clear();
    throw new ApiError(res.status, describe(detail, `Request failed (${res.status})`));
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  register: (email: string, password: string) => post<{ id: number; email: string; role: string }>("/auth/register", { email, password }),
  login: async (email: string, password: string): Promise<void> => {
    const { access_token } = await post<{ access_token: string }>("/auth/login", { email, password });
    tokenStore.set(access_token);
  },
  me: () => request<{ id: number; email: string; role: string }>("/auth/me"),

  listEmails: () => request<EmailSummary[]>("/emails"),
  getEmail: (id: number) => request<EmailDetail>(`/emails/${id}`),
  addEmail: (email: NewEmail) => post<EmailSummary>("/emails", email),
  seedInbox: () => post<{ added: number; total: number }>("/emails/seed"),
  triage: (id: number) => post<TriageStarted>(`/emails/${id}/triage`),

  listDrafts: (status?: DraftStatus) =>
    request<Draft[]>(status ? `/drafts?status=${status}` : "/drafts"),
  approveDraft: (id: number) => post<Draft>(`/drafts/${id}/approve`),
  rejectDraft: (id: number) => post<Draft>(`/drafts/${id}/reject`),
  editDraft: (id: number, edited_body: string) =>
    request<Draft>(`/drafts/${id}`, { method: "PATCH", body: JSON.stringify({ edited_body }) }),
};
