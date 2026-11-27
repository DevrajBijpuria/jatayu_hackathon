"use client";

export type AuthHeaders =
  | { Authorization: string }
  | { "X-User": string };

async function apiFetch<T>(
  path: string,
  auth: AuthHeaders,
  opts: RequestInit = {},
): Promise<T> {
  const res = await fetch(`/api/tg${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...auth,
      ...(opts.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    // Token rejected (expired, or an admin ended this session): sign in again.
    if (res.status === 401 && process.env.NEXT_PUBLIC_ENABLE_SSO === "true") {
      window.location.href = "/login?reason=expired";
    }
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      detail = JSON.parse(text).detail ?? text;
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface Verdict {
  status: "SUPPORTED" | "CONFLICT_RESOLVED" | "RESOLVED_BY_SCOPE" | "UNRESOLVED";
  answer_text: string;
  applies: string[];
  shown_sources: string[];
  decisions: Array<{
    winner: string | null;
    losers: string[];
    rule: string;
    explanation: string;
  }>;
  review_item_ids: string[];
}

export interface AskResponse {
  verdict: Verdict;
  shown_sources: Array<{
    clause_id: string;
    source_text: string;
    doc_id: string;
    effective_date: string;
  }>;
}

export interface Conflict {
  conflict_id: string;
  clause_a: string;
  clause_b: string;
  kind: string;
  score: number;
  source_a: string;
  source_b: string;
}

export interface ReviewItem {
  item_id: string;
  clause_id: string;
  reason: string;
  missing_fields: string;
  created_at: string;
}

export interface Connector {
  connector: string;
  cursor: string;
  last_run_at: string;
  last_status: string;
}

export interface IngestedDoc {
  doc_id: string;
  title: string;
  doc_type: string | null;
  language: string | null;
  access_level: string;
  ingested_at: string | null;
  issuer: string | null;
  issued_date: string | null;
  origin: string | null;
  source_path: string | null;
  clause_count: number;
}

export const ask = (q: string, as_of: string | null, auth: AuthHeaders) =>
  apiFetch<AskResponse>("/ask", auth, {
    method: "POST",
    body: JSON.stringify({ question: q, as_of }),
  });

export const getConflicts = (auth: AuthHeaders) =>
  apiFetch<Conflict[]>("/conflicts", auth);

export const getDocuments = (auth: AuthHeaders) =>
  apiFetch<IngestedDoc[]>("/documents", auth);

export const getReviewQueue = (auth: AuthHeaders) =>
  apiFetch<ReviewItem[]>("/review", auth);

export const resolveReviewItem = (
  itemId: string,
  body: Record<string, unknown>,
  auth: AuthHeaders,
) =>
  apiFetch<{ status: string }>(`/review/${itemId}`, auth, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getConnectors = (auth: AuthHeaders) =>
  apiFetch<Connector[]>("/connectors", auth);

export const syncConnector = (name: string, auth: AuthHeaders) =>
  apiFetch<{ status: string }>(`/connectors/${name}/sync`, auth, { method: "POST" });

export const deleteDocument = (docId: string, auth: AuthHeaders) =>
  apiFetch<{ status: string; doc_id: string }>(`/documents/${docId}`, auth, { method: "DELETE" });

// ── Users (admin only) ────────────────────────────────────────────────────────

export interface TGUser {
  id: string;
  email: string;
  name: string;
  access_group: string | null;
  is_admin: boolean;
  enabled: boolean;
  created_at: number | null;
}

// temporary_password is present only in the create/reset response, exactly once.
export interface PasswordIssued {
  temporary_password: string | null;
  email_sent: boolean;
}

export interface AdminAuditEntry {
  audit_id: string;
  acted_at: string;
  actor_id: string;
  actor_name: string | null;
  target_id: string;
  target_email: string | null;
  action: string;
  detail: Record<string, unknown>;
  ends_sessions: boolean;
}

export const listUsers = (search: string, auth: AuthHeaders) =>
  apiFetch<TGUser[]>(`/users?search=${encodeURIComponent(search)}`, auth);

export const createUser = (
  body: { name: string; email: string; access_group: string },
  auth: AuthHeaders,
) =>
  apiFetch<PasswordIssued & { user: TGUser }>("/users", auth, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateUser = (
  id: string,
  body: { access_group?: string; is_admin?: boolean; enabled?: boolean },
  auth: AuthHeaders,
) =>
  apiFetch<TGUser>(`/users/${id}`, auth, { method: "PATCH", body: JSON.stringify(body) });

export const resetPassword = (id: string, auth: AuthHeaders) =>
  apiFetch<PasswordIssued>(`/users/${id}/reset-password`, auth, { method: "POST" });

export const getAdminAudit = (auth: AuthHeaders) =>
  apiFetch<AdminAuditEntry[]>("/admin-audit?limit=50", auth);
