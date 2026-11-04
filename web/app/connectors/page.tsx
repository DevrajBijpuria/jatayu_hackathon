"use client";

import { useEffect, useState } from "react";
import { getConnectors, syncConnector, type Connector } from "@/lib/api";
import { useUser } from "@/lib/user-context";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-700",
  error: "bg-red-100 text-red-700",
  pending: "bg-amber-100 text-amber-700",
  default: "bg-slate-100 text-slate-600",
};

export default function ConnectorsPage() {
  const { authHeaders, isAdmin } = useUser();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  useEffect(() => {
    getConnectors(authHeaders())
      .then(setConnectors)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Failed to load")
      )
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSync(name: string) {
    setSyncing(name);
    try {
      await syncConnector(name, authHeaders());
    } finally {
      setSyncing(null);
    }
  }

  if (!isAdmin) {
    return (
      <div className="max-w-2xl mx-auto mt-12 text-center text-slate-500 text-sm">
        Admin access required.
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <h1 className="text-2xl font-semibold text-slate-800">Connectors</h1>

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && connectors.length === 0 && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-6 text-center text-slate-500 text-sm">
          No connectors configured. Enable connectors in config and restart.
        </div>
      )}

      <div className="space-y-3">
        {connectors.map((c) => (
          <div
            key={c.connector}
            className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm flex items-center justify-between gap-4"
          >
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-800">{c.connector}</span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                    STATUS_STYLES[c.last_status] ?? STATUS_STYLES.default
                  }`}
                >
                  {c.last_status ?? "unknown"}
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Last run: {c.last_run_at ? new Date(c.last_run_at).toLocaleString() : "never"}
                {c.cursor ? ` · cursor: ${c.cursor}` : ""}
              </p>
            </div>

            <button
              onClick={() => handleSync(c.connector)}
              disabled={syncing === c.connector}
              className="shrink-0 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {syncing === c.connector ? "Syncing…" : "Sync now"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
