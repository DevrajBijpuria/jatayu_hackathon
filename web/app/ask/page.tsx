"use client";

import { useState } from "react";
import { ask, type AskResponse } from "@/lib/api";
import { useUser } from "@/lib/user-context";

type Status = "SUPPORTED" | "CONFLICT_RESOLVED" | "RESOLVED_BY_SCOPE" | "UNRESOLVED";

const STATUS_STYLES: Record<Status, string> = {
  SUPPORTED: "bg-emerald-100 text-emerald-800 border-emerald-200",
  CONFLICT_RESOLVED: "bg-blue-100 text-blue-800 border-blue-200",
  RESOLVED_BY_SCOPE: "bg-amber-100 text-amber-800 border-amber-200",
  UNRESOLVED: "bg-red-100 text-red-800 border-red-200",
};

const STATUS_LABELS: Record<Status, string> = {
  SUPPORTED: "Supported",
  CONFLICT_RESOLVED: "Conflict Resolved",
  RESOLVED_BY_SCOPE: "Resolved by Scope",
  UNRESOLVED: "Unresolved — Needs Review",
};

function highlightDecidingText(text: string, deciding: string): React.ReactNode {
  if (!deciding || !text.includes(deciding)) return text;
  const parts = text.split(deciding);
  return (
    <>
      {parts[0]}
      <mark className="highlight">{deciding}</mark>
      {parts.slice(1).join(deciding)}
    </>
  );
}

function detectHindi(text: string): boolean {
  return /[ऀ-ॿ]/.test(text);
}

export default function AskPage() {
  const { authHeaders } = useUser();
  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);

  async function handleAsk() {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await ask(question.trim(), asOf || null, authHeaders());
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  const verdict = result?.verdict;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <h1 className="text-2xl font-semibold text-slate-800">Ask a Compliance Question</h1>

      {/* Question input */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4 shadow-sm">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Question</label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. What is the maximum loan-to-value ratio for retail borrowers?"
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm resize-none h-20 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleAsk();
            }}
          />
        </div>

        <div className="flex items-end gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">As of date</label>
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <button
            onClick={handleAsk}
            disabled={loading || !question.trim()}
            className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? "Checking…" : "Ask TruthGuard"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {verdict && (
        <div className="space-y-4">
          {/* Status + answer */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm space-y-3">
            <div className="flex items-center gap-3">
              <span
                className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                  STATUS_STYLES[verdict.status as Status]
                }`}
              >
                {STATUS_LABELS[verdict.status as Status] ?? verdict.status}
              </span>
            </div>
            <p className="text-slate-800 text-sm leading-relaxed">{verdict.answer_text}</p>
          </div>

          {/* Sources side-by-side */}
          {result!.shown_sources.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-slate-600 mb-2 uppercase tracking-wide">
                Sources
              </h2>
              <div className="grid gap-4 grid-cols-1 md:grid-cols-2">
                {result!.shown_sources.map((src) => {
                  const isHindi = detectHindi(src.source_text);
                  const deciding = verdict.decisions
                    .find((d) => d.winner === src.clause_id || d.losers.includes(src.clause_id))
                    ?.explanation ?? "";
                  return (
                    <div
                      key={src.clause_id}
                      className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono text-slate-500">{src.clause_id}</span>
                        <span className="text-xs text-slate-400">{src.effective_date}</span>
                      </div>
                      {isHindi ? (
                        <div className="space-y-1">
                          <p className="text-sm text-slate-700 leading-relaxed">
                            {src.source_text}
                          </p>
                          <p className="text-xs text-slate-500 italic border-t border-slate-100 pt-1">
                            <span className="font-medium not-italic text-slate-600">Translation: </span>
                            {/* Translation placeholder — real translation from ingest phase */}
                            [see original Hindi above]
                          </p>
                        </div>
                      ) : (
                        <p className="text-sm text-slate-700 leading-relaxed">
                          {highlightDecidingText(src.source_text, deciding)}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Step-by-step trace */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <button
              onClick={() => setTraceOpen(!traceOpen)}
              className="w-full flex items-center justify-between px-5 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors"
            >
              <span>Step-by-step reasoning trace</span>
              <span className="text-slate-400">{traceOpen ? "▲" : "▼"}</span>
            </button>
            {traceOpen && (
              <div className="border-t border-slate-100 px-5 py-4 space-y-3">
                {verdict.decisions.map((d, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="mt-1 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center shrink-0">
                      {i + 1}
                    </div>
                    <div>
                      <span className="text-xs font-semibold text-indigo-700 uppercase tracking-wide">
                        {d.rule}
                      </span>
                      <p className="text-sm text-slate-600 mt-0.5">{d.explanation}</p>
                      {d.winner && (
                        <p className="text-xs text-emerald-600 mt-0.5">
                          Winner: <code className="font-mono">{d.winner}</code>
                        </p>
                      )}
                    </div>
                  </div>
                ))}
                {verdict.decisions.length === 0 && (
                  <p className="text-sm text-slate-400 italic">No decisions recorded.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
