"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";
import { useUser } from "@/lib/user-context";

const ENABLE_SSO = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

const NAV = [
  { href: "/ask", label: "Ask", icon: "💬" },
  { href: "/conflicts", label: "Conflicts", icon: "⚠️" },
  { href: "/review", label: "Review Queue", icon: "📋", admin: true },
  { href: "/documents", label: "Documents", icon: "🗂️", admin: true },
  { href: "/connectors", label: "Connectors", icon: "🔌", admin: true },
];

export default function NavShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { data: session } = useSession();
  const { xUser, setXUser, isAdmin } = useUser();

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

        <div className="border-t border-indigo-800 p-3">
          {ENABLE_SSO ? (
            session ? (
              <div className="space-y-1">
                <p className="text-indigo-200 text-xs truncate">{session.user?.name}</p>
                <button
                  onClick={() => signOut()}
                  className="text-xs text-indigo-300 hover:text-white underline"
                >
                  Sign out
                </button>
              </div>
            ) : (
              <button
                onClick={() => signIn("keycloak")}
                className="w-full text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded px-2 py-1.5"
              >
                Sign in
              </button>
            )
          ) : (
            <div className="space-y-1">
              <p className="text-indigo-400 text-xs">Demo user</p>
              <select
                value={xUser}
                onChange={(e) => setXUser(e.target.value as "employee" | "admin")}
                className="w-full text-xs bg-indigo-800 text-indigo-100 border border-indigo-600 rounded px-1.5 py-1"
              >
                <option value="employee">Employee</option>
                <option value="admin">Admin</option>
              </select>
            </div>
          )}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
