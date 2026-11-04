"use client";

import { createContext, useContext, useState } from "react";
import { useSession } from "next-auth/react";
import type { AuthHeaders } from "./api";

const ENABLE_SSO = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

interface UserCtx {
  xUser: "employee" | "admin";
  setXUser: (u: "employee" | "admin") => void;
  authHeaders: () => AuthHeaders;
  isAdmin: boolean;
}

const Ctx = createContext<UserCtx | null>(null);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  const [xUser, setXUser] = useState<"employee" | "admin">("employee");

  const authHeaders = (): AuthHeaders => {
    if (ENABLE_SSO) {
      const token = (session as (typeof session & { access_token?: string }) | null)
        ?.access_token;
      return { Authorization: `Bearer ${token ?? ""}` };
    }
    return { "X-User": xUser };
  };

  const isAdmin = ENABLE_SSO
    ? !!(session as any)?.access_token
    : xUser === "admin";

  return (
    <Ctx.Provider value={{ xUser, setXUser, authHeaders, isAdmin }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUser(): UserCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUser must be inside UserProvider");
  return ctx;
}
