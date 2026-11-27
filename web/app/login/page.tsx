"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";

const NOTICES: Record<string, string> = {
  signedout: "You have signed out.",
  expired: "Your session has ended. Please sign in again.",
};

function safePath(p: string | null): string {
  return p && p.startsWith("/") && !p.startsWith("//") ? p : "/ask";
}

function LoginCard() {
  const params = useSearchParams();
  const { status } = useSession();
  const reason = params.get("reason");
  const notice = params.get("error") ? "Sign-in did not complete. Please try again." : NOTICES[reason ?? ""];

  // Arriving here after sign-out or an ended session: drop the local session cookie too.
  useEffect(() => {
    if (reason && status === "authenticated") signOut({ redirect: false });
  }, [reason, status]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <div className="bg-indigo-900 text-white rounded-t-xl px-6 py-6">
          <p className="font-bold text-2xl tracking-tight">TruthGuard</p>
          <p className="text-indigo-300 text-sm mt-0.5">Regulatory Intelligence</p>
        </div>
        <div className="bg-white border border-t-0 border-slate-200 rounded-b-xl shadow-sm px-6 py-6 space-y-5">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">Sign in</h1>
            <p className="text-sm text-slate-500 mt-1">
              Answers from your organisation&apos;s policies, with every source shown. You see only the
              documents your access level allows.
            </p>
          </div>
          {notice && (
            <p className="text-sm bg-indigo-50 border border-indigo-100 text-indigo-800 rounded-lg px-3 py-2">
              {notice}
            </p>
          )}
          <button
            onClick={() => signIn("keycloak", { callbackUrl: safePath(params.get("callbackUrl")) })}
            disabled={status === "loading"}
            className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Sign in
          </button>
          <p className="text-xs text-slate-400">
            You enter your password on the TruthGuard sign-in page run by your organisation&apos;s identity
            provider. TruthGuard itself never sees it. New accounts are created by an administrator.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginCard />
    </Suspense>
  );
}
