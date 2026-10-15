// Mirrors backend/app/schemas.py. Keep in sync by hand (no codegen yet).

export type TriageStatus = "queued" | "running" | "completed" | "failed";
export type DraftStatus = "pending" | "approved" | "rejected";

export interface TraceStep {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  result: unknown;
  error: string | null;
  latency_ms: number;
}

export interface Triage {
  status: TriageStatus;
  category: string | null;
  urgency: string | null;
  needs_reply: boolean | null;
  summary: string | null;
  error_code: string | null;
  error_message: string | null;
  provider: string | null;
  attempts: number;
  trace: TraceStep[];
  updated_at: string;
}

export interface Task {
  id: number;
  description: string;
  due_hint: string | null;
  priority: string;
}

export interface Draft {
  id: number;
  email_id: number;
  body: string;
  edited_body: string | null;
  final_body: string;
  tone: string;
  status: DraftStatus;
  created_at: string;
  decided_at: string | null;
  email_subject: string | null;
  email_sender: string | null;
}

export interface EmailSummary {
  id: number;
  sender: string;
  subject: string;
  received_at: string;
  triage_status: TriageStatus | null;
  category: string | null;
  urgency: string | null;
  draft_status: DraftStatus | null;
}

export interface EmailDetail {
  id: number;
  sender: string;
  subject: string;
  body: string;
  received_at: string;
  triage: Triage | null;
  tasks: Task[];
  draft: Draft | null;
}

export interface TriageStarted {
  email_id: number;
  status: TriageStatus;
  started: boolean;
}

export interface NewEmail {
  raw_text?: string;
  sender?: string;
  subject?: string;
  body?: string;
}
