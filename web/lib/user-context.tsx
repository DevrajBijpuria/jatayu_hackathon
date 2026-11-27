"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import type { AuthHeaders } from "./api";

const ENABLE_SSO = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

export interface Me {
  user_id: string;
  name: string | null;
  role: "employee" | "admin";
  access_levels: string[];
}

interface UserCtx {
  xUser: "employee" | "admin";
  setXUser: (u: "employee" | "admin") => void;
  authHeaders: () => AuthHeaders;
  isAdmin: boolean;
  me: Me | null;
}

const Ctx = createContext<UserCtx | null>(null);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const [xUser, setXUser] = useState<"employee" | "admin">("employee");
  const [me, setMe] = useState<Me | null>(null);
  const s = session as (typeof session & { access_token?: string; error?: string }) | null;
  const token = s?.access_token;

  const authHeaders = (): AuthHeaders =>
    ENABLE_SSO ? { Authorization: `Bearer ${token ?? ""}` } : { "X-User": xUser };

  useEffect(() => {
    if (ENABLE_SSO && s?.error) {
      window.location.href = "/login?reason=expired";
      return;
    }
    if (ENABLE_SSO && (status !== "authenticated" || !token)) {
      setMe(null);
      return;
    }
    fetch("/api/tg/me", { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setMe)
      .catch((code) => {
        setMe(null);
        if (ENABLE_SSO && code === 401) window.location.href = "/login?reason=expired";
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, token, xUser, s?.error]);

  // Admin rights come from the API's view of the token (tg-admins), never from the UI.
  const isAdmin = ENABLE_SSO ? me?.role === "admin" : xUser === "admin";

  // Pages call the API as soon as they mount, so hold them until the token exists.
  // Unauthenticated renders only reach /login (middleware redirects everything else).
  if (ENABLE_SSO && (status === "loading" || (status === "authenticated" && !token))) return null;

  return (
    <Ctx.Provider value={{ xUser, setXUser, authHeaders, isAdmin, me }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUser(): UserCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUser must be inside UserProvider");
  return ctx;
}
