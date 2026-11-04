"use client";

import { useEffect, useState } from "react";
import { getReviewQueue, resolveReviewItem, type ReviewItem } from "@/lib/api";
import { useUser } from "@/lib/user-context";

const EDITABLE_FIELDS = [
  { key: "effective_date", label: "Effective date", type: "date" },
  { key: "authority_rank", label: "Authority rank", type: "number" },
  { key: "issuer", label: "Issuer", type: "text" },
  { key: "value_num", label: "Value (numeric)", type: "number" },
  { key: "value_text", label: "Value (text)", type: "text" },
  { key: "value_unit", label: "Unit", type: "text" },
];

function parseMissing(raw: string): string[] {
  try {
    const v = JSON.parse(raw);
    if (Array.isArray(v)) return v.map(String);
  } catch {}
  return raw ? [raw] : [];
}

function ReviewForm({
  item,
  onDone,
  authHeaders,
}: {
  item: ReviewItem;
  onDone: () => void;
  authHeaders: () => { Authorization: string } | { "X-User": string };
}) {
  const missing = parseMissing(item.missing_fields);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      await resolveReviewItem(
        item.item_id,
        Object.fromEntries(
          Object.entries(fields).filter(([, v]) => v !== "")
        ),
        authHeaders(),
      );
      onDone();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const relevantFields = EDITABLE_FIELDS.filter((f) =>
    missing.includes(f.key)
  );

  return (
    <div className="border-t border-slate-100 pt-3 space-y-3">
      <p className="text-xs text-slate-500">
        Missing: <span className="font-mono">{missing.join(", ")}</span>
      </p>
      <div className="grid grid-cols-2 gap-3">
        {(relevantFields.length > 0 ? relevantFields : EDITABLE_FIELDS).map(
          ({ key, label, type }) => (
            <div key={key}>
              <label className="block text-xs font-medium text-slate-600 mb-0.5">
                {label}
              </label>
              <input
                type={type}
                value={fields[key] ?? ""}
                onChange={(e) => setFields((p) => ({ ...p, [key]: e.target.value }))}
                className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          )
        )}
      </div>
      {err && <p className="text-xs text-red-600">{err}</p>}
      <button
        onClick={save}
        disabled={saving}
        className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
      >
        {saving ? "Saving…" : "Save and re-check"}
      </button>
    </div>
  );
}

export default function ReviewPage() {
  const { authHeaders, isAdmin } = useUser();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  function reload() {
    setLoading(true);
    getReviewQueue(authHeaders())
      .then(setItems)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Failed to load")
      )
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);// eslint-disable-line react-hooks/exhaustive-deps

  if (!isAdmin) {
    return (
      <div className="max-w-2xl mx-auto mt-12 text-center text-slate-500 text-sm">
        Admin access required.
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Review Queue</h1>
        <span className="text-sm text-slate-500">{items.length} open item{items.length !== 1 ? "s" : ""}</span>
      </div>

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && items.length === 0 && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-6 text-center text-emerald-700 text-sm">
          Review queue is empty — no unresolved conflicts awaiting admin review.
        </div>
      )}

      {items.map((item) => (
        <div
          key={item.item_id}
          className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <span className="font-mono text-sm text-indigo-700">{item.clause_id}</span>
              <p className="text-sm text-slate-600 mt-0.5">{item.reason}</p>
              <p className="text-xs text-slate-400 mt-1">
                Created {new Date(item.created_at).toLocaleDateString()}
              </p>
            </div>
            <button
              onClick={() =>
                setExpanded(expanded === item.item_id ? null : item.item_id)
              }
              className="shrink-0 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              {expanded === item.item_id ? "Close" : "Fill in"}
            </button>
          </div>

          {expanded === item.item_id && (
            <ReviewForm
              item={item}
              onDone={() => {
                setExpanded(null);
                reload();
              }}
              authHeaders={authHeaders}
            />
          )}
        </div>
      ))}
    </div>
  );
}
