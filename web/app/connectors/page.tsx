"use client";

import { useEffect, useRef, useState } from "react";
import { getConnectors, syncConnector, type Connector } from "@/lib/api";
import { useUser } from "@/lib/user-context";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-700",
  error: "bg-red-100 text-red-700",
  pending: "bg-amber-100 text-amber-700",
  default: "bg-slate-100 text-slate-600",
};

const ACCESS_LEVELS = ["all", "compliance", "board"] as const;

function UploadCard({ authHeaders }: { authHeaders: () => { Authorization: string } | { "X-User": string } }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [accessLevel, setAccessLevel] = useState<string>("all");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  async function handleUpload() {
    if (files.length === 0) return;
    setUploading(true);
    setResult(null);
    try {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      const auth = authHeaders();
      const res = await fetch(`/api/tg/ingest?access_level=${accessLevel}`, {
        method: "POST",
        headers: auth,  // no Content-Type — browser sets multipart boundary
        body: form,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        setResult({ ok: false, msg: `${res.status}: ${text}` });
      } else {
        const data = await res.json() as { doc_ids: string[] };
        setResult({ ok: true, msg: `Ingested ${data.doc_ids.length} document(s): ${data.doc_ids.join(", ")}` });
        setFiles([]);
        if (fileRef.current) fileRef.current.value = "";
      }
    } catch (e: unknown) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : "Upload failed" });
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-800">Upload Policy Document</h2>
        <p className="text-xs text-slate-500 mt-0.5">PDF, DOCX, or TXT — ingested immediately into the knowledge base.</p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-slate-600 mb-1">File(s)</label>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="block w-full text-sm text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 cursor-pointer"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Access level</label>
          <select
            value={accessLevel}
            onChange={(e) => setAccessLevel(e.target.value)}
            className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {ACCESS_LEVELS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </div>

        <button
          onClick={handleUpload}
          disabled={uploading || files.length === 0}
          className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors whitespace-nowrap"
        >
          {uploading ? "Uploading…" : `Upload${files.length > 1 ? ` (${files.length})` : ""}`}
        </button>
      </div>

      {files.length > 0 && (
        <ul className="text-xs text-slate-500 space-y-0.5">
          {files.map((f) => (
            <li key={f.name}>📄 {f.name} <span className="text-slate-400">({(f.size / 1024).toFixed(0)} KB)</span></li>
          ))}
        </ul>
      )}

      {result && (
        <p className={`text-sm rounded-lg px-3 py-2 ${result.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
          {result.msg}
        </p>
      )}
    </div>
  );
}

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
      <h1 className="text-2xl font-semibold text-slate-800">Connectors &amp; Ingest</h1>

      <UploadCard authHeaders={authHeaders} />

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
