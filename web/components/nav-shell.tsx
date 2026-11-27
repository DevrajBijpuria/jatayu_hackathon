"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@/lib/user-context";
import { accessLabel } from "@/lib/access";

const ENABLE_SSO = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

const NAV = [
  { href: "/ask", label: "Ask", icon: "💬" },
  { href: "/conflicts", label: "Conflicts", icon: "⚠️" },
  { href: "/review", label: "Review Queue", icon: "📋", admin: true },
  { href: "/documents", label: "Documents", icon: "🗂️", admin: true },
  { href: "/connectors", label: "Connectors", icon: "🔌", admin: true },
  { href: "/users", label: "Users", icon: "👥", admin: true },
];

function UserHeader() {
  const { xUser, setXUser, me, isAdmin } = useUser();

  if (!ENABLE_SSO) {
    return (
      <label className="flex items-center gap-2 text-xs text-slate-500">
        Demo user
        <select
          value={xUser}
          onChange={(e) => setXUser(e.target.value as "employee" | "admin")}
          className="text-xs border border-slate-300 rounded px-1.5 py-1 text-slate-700"
        >
          <option value="employee">Employee</option>
          <option value="admin">Admin</option>
        </select>
      </label>
    );
  }
  if (!me) return <span className="text-xs text-slate-400">Signing in…</span>;
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm font-medium text-slate-700">{me.name}</span>
      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700">
        {accessLabel(me.access_levels)}
      </span>
      {isAdmin && (
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">Admin</span>
      )}
      {/* Plain link, not <Link>: prefetching /logout would sign the user out. */}
      <a href="/logout" className="text-xs text-slate-500 hover:text-indigo-700 underline">
        Sign out
      </a>
    </div>
  );
}

export default function NavShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { isAdmin } = useUser();

  if (path === "/login") return <>{children}</>;

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-52 bg-indigo-900 text-white flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-indigo-800">
          <span className="font-bold text-lg tracking-tight">TruthGuard</span>
          <p className="text-indigo-300 text-xs mt-0.5">Regulatory Intelligence</p>
        </div>

        <nav className="flex-1 py-4 space-y-1 px-2">
          {NAV.map(({ href, label, icon, admin }) => {
            if (admin && !isAdmin) return null;
            const active = path === href || path.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  active
                    ? "bg-indigo-700 text-white"
                    : "text-indigo-200 hover:bg-indigo-800 hover:text-white"
                }`}
              >
                <span>{icon}</span>
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-12 shrink-0 bg-white border-b border-slate-200 px-6 flex items-center justify-end">
          <UserHeader />
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
