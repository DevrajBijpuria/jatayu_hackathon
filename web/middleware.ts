import { NextResponse } from "next/server";
import { auth } from "@/auth";

const ENABLE_SSO = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

export default auth((req) => {
  const { pathname, search, searchParams } = req.nextUrl;
  const onLogin = pathname === "/login";

  // Development mode without login: the header's demo-user switcher applies.
  if (!ENABLE_SSO) {
    return onLogin ? NextResponse.redirect(new URL("/ask", req.url)) : NextResponse.next();
  }

  const session = req.auth as (typeof req.auth & { error?: string }) | null;
  const signedIn = !!session && !session.error;

  if (onLogin) {
    // ?reason=... means the login page must first clear a stale local session.
    return signedIn && !searchParams.has("reason")
      ? NextResponse.redirect(new URL("/ask", req.url))
      : NextResponse.next();
  }
  if (!signedIn) {
    const url = new URL("/login", req.url);
    if (session?.error) url.searchParams.set("reason", "expired");
    if (pathname !== "/") url.searchParams.set("callbackUrl", pathname + search);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
});

export const config = {
  // /api/tg is the backend proxy; the API checks the Bearer token itself.
  matcher: ["/((?!api/auth|api/tg|_next/static|_next/image|favicon.ico).*)"],
};
