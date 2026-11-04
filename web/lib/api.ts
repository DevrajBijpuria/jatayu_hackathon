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
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text}`);
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

export const ask = (q: string, as_of: string | null, auth: AuthHeaders) =>
  apiFetch<AskResponse>("/ask", auth, {
    method: "POST",
    body: JSON.stringify({ question: q, as_of }),
  });

export const getConflicts = (auth: AuthHeaders) =>
  apiFetch<Conflict[]>("/conflicts", auth);

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
