"use client";

import { useEffect, useState } from "react";
import { getDocuments, type IngestedDoc } from "@/lib/api";
import { useUser } from "@/lib/user-context";

const ACCESS_BADGE: Record<string, string> = {
  all: "bg-slate-100 text-slate-600",
  compliance: "bg-purple-100 text-purple-700",
  board: "bg-indigo-100 text-indigo-700",
};

const DOC_ICON: Record<string, string> = {
  pdf: "📕",
  docx: "📘",
  doc: "📘",
  txt: "📄",
  default: "📋",
};

function fileIcon(doc: IngestedDoc): string {
  const ext = (doc.doc_type ?? doc.source_path ?? "").toLowerCase().replace(".", "");
  return DOC_ICON[ext] ?? DOC_ICON.default;
}

function fmt(dt: string | null): string {
  if (!dt || dt === "None") return "—";
  try { return new Date(dt).toLocaleDateString(); } catch { return dt; }
}

function fmtTime(dt: string | null): string {
  if (!dt || dt === "None") return "—";
  try { return new Date(dt).toLocaleString(); } catch { return dt; }
}

type ViewMode = "table" | "cards";

export default function DocumentsPage() {
  const { authHeaders, isAdmin } = useUser();
  const [docs, setDocs] = useState<IngestedDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>("table");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    getDocuments(authHeaders())
      .then(setDocs)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!isAdmin) {
    return (
      <div className="max-w-2xl mx-auto mt-12 text-center text-slate-500 text-sm">
        Admin access required.
      </div>
    );
  }

  const visible = filter
    ? docs.filter(
        (d) =>
          d.title.toLowerCase().includes(filter.toLowerCase()) ||
          d.doc_id.toLowerCase().includes(filter.toLowerCase()) ||
          (d.issuer ?? "").toLowerCase().includes(filter.toLowerCase()),
      )
    : docs;

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800">Ingested Documents</h1>
          <p className="text-sm text-slate-500 mt-0.5">{docs.length} document{docs.length !== 1 ? "s" : ""} in knowledge base</p>
        </div>

        {/* View toggle */}
        <div className="flex items-center gap-2 bg-slate-100 rounded-lg p-1">
          <button
            onClick={() => setView("table")}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${view === "table" ? "bg-white shadow-sm text-slate-800" : "text-slate-500 hover:text-slate-700"}`}
          >
            ☰ Table
          </button>
          <button
            onClick={() => setView("cards")}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${view === "cards" ? "bg-white shadow-sm text-slate-800" : "text-slate-500 hover:text-slate-700"}`}
          >
            ⊞ Files
          </button>
        </div>
      </div>

      {/* Filter */}
      <input
        type="text"
        placeholder="Search by title, doc ID, or issuer…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full max-w-sm border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && visible.length === 0 && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-8 text-center text-slate-500 text-sm">
          No documents ingested yet. Upload a policy document from the Connectors page.
        </div>
      )}

      {/* ── TABLE VIEW ── */}
      {view === "table" && visible.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50 text-left">
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide">Document</th>
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide">Type</th>
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide">Access</th>
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide">Issuer</th>
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide">Issued</th>
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide text-center">Clauses</th>
                  <th className="px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide">Ingested</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((doc) => (
                  <tr key={doc.doc_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{fileIcon(doc)}</span>
                        <div>
                          <p className="font-medium text-slate-800 leading-tight">{doc.title}</p>
                          <p className="text-xs text-slate-400 font-mono mt-0.5">{doc.doc_id}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-500 uppercase text-xs font-mono">
                      {doc.doc_type ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${ACCESS_BADGE[doc.access_level] ?? ACCESS_BADGE.all}`}>
                        {doc.access_level}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 text-xs">{doc.issuer ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{fmt(doc.issued_date)}</td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-block bg-indigo-50 text-indigo-700 text-xs font-semibold px-2 py-0.5 rounded-full">
                        {doc.clause_count}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                      {fmtTime(doc.ingested_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── CARDS / FILE VIEW ── */}
      {view === "cards" && visible.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {visible.map((doc) => (
            <div
              key={doc.doc_id}
              className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow space-y-3"
            >
              {/* File icon + type */}
              <div className="flex items-start justify-between">
                <span className="text-3xl">{fileIcon(doc)}</span>
                <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${ACCESS_BADGE[doc.access_level] ?? ACCESS_BADGE.all}`}>
                  {doc.access_level}
                </span>
              </div>

              {/* Title */}
              <div>
                <p className="font-medium text-slate-800 text-sm leading-snug line-clamp-2">{doc.title}</p>
                <p className="text-xs text-slate-400 font-mono mt-1 truncate">{doc.doc_id}</p>
              </div>

              {/* Meta */}
              <div className="border-t border-slate-100 pt-2 space-y-1 text-xs text-slate-500">
                {doc.issuer && <p>🏛 {doc.issuer}</p>}
                {doc.issued_date && doc.issued_date !== "None" && (
                  <p>📅 Issued {fmt(doc.issued_date)}</p>
                )}
                <p>
                  <span className="bg-indigo-50 text-indigo-700 font-semibold px-1.5 py-0.5 rounded">
                    {doc.clause_count}
                  </span>{" "}
                  clause{doc.clause_count !== 1 ? "s" : ""}
                </p>
                <p className="text-slate-400">Added {fmt(doc.ingested_at)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
