"use client";

import { useEffect, useState } from "react";
import {
  createUser,
  getAdminAudit,
  listUsers,
  resetPassword,
  updateUser,
  type AdminAuditEntry,
  type PasswordIssued,
  type TGUser,
} from "@/lib/api";
import { ACCESS_GROUPS, accessGroupInfo } from "@/lib/access";
import { useUser } from "@/lib/user-context";

const ACTION_LABELS: Record<string, string> = {
  create: "Created user",
  access_change: "Changed access level",
  enable: "Enabled account",
  disable: "Disabled account",
  admin_grant: "Made admin",
  admin_revoke: "Removed admin rights",
  password_reset: "Reset password",
};

const groupLabel = (g: unknown) => accessGroupInfo(typeof g === "string" ? g : null)?.label ?? "—";

function auditDetail(e: AdminAuditEntry): string {
  const d = e.detail;
  if (e.action === "access_change") return `${groupLabel(d.from)} → ${groupLabel(d.to)}`;
  if (e.action === "create") return `Access: ${groupLabel(d.access_group)}${d.is_admin ? " · admin" : ""}`;
  if (e.action === "password_reset") return d.method === "email" ? "Set-password email sent" : "Temporary password issued";
  return "";
}

// ── One-time password reveal ──────────────────────────────────────────────────

function PasswordReveal({
  email,
  issued,
  onClose,
}: {
  email: string;
  issued: PasswordIssued;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!issued.temporary_password) return;
    await navigator.clipboard.writeText(issued.temporary_password);
    setCopied(true);
  }

  return (
    <Modal title={issued.email_sent ? "Email sent" : "Temporary password"} onClose={onClose}>
      {issued.email_sent ? (
        <p className="text-sm text-slate-600">
          Keycloak emailed <span className="font-medium">{email}</span> a link to set their password.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            Give this password to <span className="font-medium">{email}</span>.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 font-mono text-base bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 select-all">
              {issued.temporary_password}
            </code>
            <button
              onClick={copy}
              className="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Shown once. The user must change it at first login.
          </p>
        </div>
      )}
      <div className="flex justify-end pt-2">
        <button onClick={onClose} className="px-4 py-1.5 text-sm font-medium text-slate-600 hover:text-slate-800">
          Done
        </button>
      </div>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center px-4" onClick={onClose}>
      <div
        className="w-full max-w-md bg-white rounded-xl shadow-lg border border-slate-200 p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
        {children}
      </div>
    </div>
  );
}

// ── New user dialog ───────────────────────────────────────────────────────────

function NewUserDialog({
  onCancel,
  onCreated,
  authHeaders,
}: {
  onCancel: () => void;
  onCreated: (u: TGUser, issued: PasswordIssued) => void;
  authHeaders: ReturnType<typeof useUser>["authHeaders"];
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [group, setGroup] = useState<string>("tg-employees");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const res = await createUser({ name, email, access_group: group }, authHeaders());
      onCreated(res.user, res);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Could not create the user");
    } finally {
      setSaving(false);
    }
  }

  const input =
    "w-full border border-slate-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500";

  return (
    <Modal title="New user" onClose={onCancel}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-0.5">Full name</label>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-0.5">Email (used to sign in)</label>
          <input className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <fieldset className="space-y-2">
          <legend className="block text-xs font-medium text-slate-600 mb-1">Access level</legend>
          {ACCESS_GROUPS.map((a) => (
            <label
              key={a.group}
              className={`flex items-start gap-2 border rounded-lg px-3 py-2 cursor-pointer ${
                group === a.group ? "border-indigo-400 bg-indigo-50" : "border-slate-200"
              }`}
            >
              <input
                type="radio"
                name="access"
                className="mt-1"
                checked={group === a.group}
                onChange={() => setGroup(a.group)}
              />
              <span>
                <span className="block text-sm font-medium text-slate-800">{a.label}</span>
                <span className="block text-xs text-slate-500">Can see: {a.canSee}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {err && <p className="text-xs text-red-600">{err}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="px-4 py-1.5 text-sm font-medium text-slate-600">
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
          >
            {saving ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function UsersPage() {
  const { authHeaders, isAdmin, me } = useUser();
  const [users, setUsers] = useState<TGUser[]>([]);
  const [audit, setAudit] = useState<AdminAuditEntry[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [revealed, setRevealed] = useState<{ email: string; issued: PasswordIssued } | null>(null);

  function reload(q = search) {
    Promise.all([listUsers(q, authHeaders()), getAdminAudit(authHeaders())])
      .then(([u, a]) => {
        setUsers(u);
        setAudit(a);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Failed to load users"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!isAdmin) return;
    const t = setTimeout(() => reload(search), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, isAdmin]);

  async function change(u: TGUser, body: Parameters<typeof updateUser>[1], confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(u.id);
    setError(null);
    try {
      await updateUser(u.id, body, authHeaders());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Change failed");
    } finally {
      setBusy(null);
      reload();
    }
  }

  async function reset(u: TGUser) {
    if (!window.confirm(`Reset the password for ${u.email}? Their current password stops working.`)) return;
    setBusy(u.id);
    setError(null);
    try {
      setRevealed({ email: u.email, issued: await resetPassword(u.id, authHeaders()) });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setBusy(null);
      reload();
    }
  }

  function onAccessChange(u: TGUser, group: string) {
    const from = accessGroupInfo(u.access_group);
    const to = accessGroupInfo(group);
    const reduced = ACCESS_GROUPS.findIndex((a) => a.group === group) <
      ACCESS_GROUPS.findIndex((a) => a.group === u.access_group);
    change(
      u,
      { access_group: group },
      reduced ? `Change ${u.email} from ${from?.label} to ${to?.label}? They will be signed out everywhere.` : undefined,
    );
  }

  if (!isAdmin) {
    return <div className="max-w-2xl mx-auto mt-12 text-center text-slate-500 text-sm">Admin access required.</div>;
  }

  const th = "px-4 py-3 font-semibold text-slate-600 text-xs uppercase tracking-wide";

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800">Users</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Decide who can sign in and which documents each person can see.
          </p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg"
        >
          New user
        </button>
      </div>

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name or email"
        className="w-full max-w-sm border border-slate-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />

      {error && (
        <p className="text-sm bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2">{error}</p>
      )}
      {loading && <p className="text-sm text-slate-400">Loading…</p>}

      {!loading && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50 text-left">
                  <th className={th}>Person</th>
                  <th className={th}>Access level</th>
                  <th className={th}>Admin</th>
                  <th className={th}>Status</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {users.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-400">No users found.</td>
                  </tr>
                )}
                {users.map((u) => {
                  const self = u.id === me?.user_id;
                  const info = accessGroupInfo(u.access_group);
                  return (
                    <tr key={u.id} className={`hover:bg-slate-50 ${u.enabled ? "" : "opacity-60"}`}>
                      <td className="px-4 py-3">
                        <p className="font-medium text-slate-800">
                          {u.name} {self && <span className="text-xs text-slate-400 font-normal">(you)</span>}
                        </p>
                        <p className="text-xs text-slate-400">{u.email}</p>
                      </td>
                      <td className="px-4 py-3">
                        <select
                          value={u.access_group ?? ""}
                          disabled={busy === u.id}
                          onChange={(e) => onAccessChange(u, e.target.value)}
                          className="text-sm border border-slate-300 rounded px-2 py-1"
                        >
                          {!u.access_group && <option value="">No access level</option>}
                          {ACCESS_GROUPS.map((a) => (
                            <option key={a.group} value={a.group}>{a.label}</option>
                          ))}
                        </select>
                        <p className="text-xs text-slate-400 mt-1">
                          {info ? `Can see: ${info.canSee}` : "Can see: no documents"}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <label
                          className="inline-flex items-center gap-2 text-xs text-slate-600"
                          title={self ? "You cannot remove your own admin rights" : undefined}
                        >
                          <input
                            type="checkbox"
                            checked={u.is_admin}
                            disabled={busy === u.id || (self && u.is_admin)}
                            onChange={(e) =>
                              change(
                                u,
                                { is_admin: e.target.checked },
                                e.target.checked ? undefined : `Remove admin rights from ${u.email}?`,
                              )
                            }
                          />
                          Admin
                        </label>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          disabled={busy === u.id || self}
                          title={self ? "You cannot disable your own account" : undefined}
                          onClick={() =>
                            change(
                              u,
                              { enabled: !u.enabled },
                              u.enabled ? `Disable ${u.email}? They will be signed out everywhere.` : undefined,
                            )
                          }
                          className={`text-xs font-semibold px-2 py-0.5 rounded-full disabled:cursor-not-allowed ${
                            u.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"
                          }`}
                        >
                          {u.enabled ? "Enabled" : "Disabled"}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => reset(u)}
                          disabled={busy === u.id}
                          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium disabled:opacity-40"
                        >
                          Reset password
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Admin activity</h2>
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-left">
                <th className={th}>When</th>
                <th className={th}>Who</th>
                <th className={th}>Action</th>
                <th className={th}>User</th>
                <th className={th}>Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {audit.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-4 text-center text-slate-400 text-xs">No admin actions yet.</td>
                </tr>
              )}
              {audit.map((e) => (
                <tr key={e.audit_id}>
                  <td className="px-4 py-2 text-xs text-slate-400 whitespace-nowrap">
                    {new Date(e.acted_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-600">{e.actor_name ?? e.actor_id}</td>
                  <td className="px-4 py-2 text-xs font-medium text-slate-700">{ACTION_LABELS[e.action] ?? e.action}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{e.target_email}</td>
                  <td className="px-4 py-2 text-xs text-slate-500">
                    {auditDetail(e)}
                    {e.ends_sessions && <span className="ml-2 text-amber-700">· sessions ended</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {creating && (
        <NewUserDialog
          authHeaders={authHeaders}
          onCancel={() => setCreating(false)}
          onCreated={(u, issued) => {
            setCreating(false);
            setRevealed({ email: u.email, issued });
            reload();
          }}
        />
      )}
      {revealed && <PasswordReveal email={revealed.email} issued={revealed.issued} onClose={() => setRevealed(null)} />}
    </div>
  );
}
