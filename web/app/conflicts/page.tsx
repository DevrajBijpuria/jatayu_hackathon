"use client";

import { useEffect, useState } from "react";
import { getConflicts, type Conflict } from "@/lib/api";
import { useUser } from "@/lib/user-context";

const KIND_STYLES: Record<string, string> = {
  value_mismatch: "bg-red-100 text-red-700",
  scope_overlap: "bg-amber-100 text-amber-700",
  default: "bg-slate-100 text-slate-600",
};

export default function ConflictsPage() {
  const { authHeaders } = useUser();
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    getConflicts(authHeaders())
      .then(setConflicts)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Failed to load conflicts")
      )
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible = filter
    ? conflicts.filter(
        (c) =>
          c.clause_a.includes(filter) ||
          c.clause_b.includes(filter) ||
          c.kind.includes(filter)
      )
    : conflicts;

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-800">Detected Conflicts</h1>
        <span className="text-sm text-slate-500">{visible.length} conflict{visible.length !== 1 ? "s" : ""}</span>
      </div>

      <input
        type="text"
        placeholder="Filter by clause ID or kind…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full max-w-sm border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && visible.length === 0 && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-6 text-center text-emerald-700 text-sm">
          No conflicts detected — all accessible clauses are consistent.
        </div>
      )}

      {visible.map((c) => (
        <div
          key={c.conflict_id}
          className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-3"
        >
          <div className="flex items-center gap-3 flex-wrap">
            <span
              className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                KIND_STYLES[c.kind] ?? KIND_STYLES.default
              }`}
            >
              {c.kind.replace(/_/g, " ")}
            </span>
            <span className="text-xs text-slate-400">score {c.score?.toFixed(2)}</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              { id: c.clause_a, text: c.source_a },
              { id: c.clause_b, text: c.source_b },
            ].map(({ id, text }) => (
              <div
                key={id}
                className="bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-1"
              >
                <span className="text-xs font-mono text-slate-500">{id}</span>
                <p className="text-sm text-slate-700 leading-relaxed line-clamp-4">{text}</p>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
