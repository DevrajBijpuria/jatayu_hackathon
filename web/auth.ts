import NextAuth from "next-auth";
import type { JWT } from "next-auth/jwt";
import Keycloak from "next-auth/providers/keycloak";

const ISSUER = process.env.OIDC_ISSUER!;
const CLIENT_ID = process.env.OIDC_CLIENT_ID!;

// Access tokens live ~5 minutes; refresh shortly before expiry. Refresh fails once an
// admin ends the user's Keycloak sessions or disables them, which forces a new sign-in.
async function refresh(token: JWT): Promise<JWT> {
  try {
    const res = await fetch(`${ISSUER}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: CLIENT_ID,
        refresh_token: token.refresh_token as string,
      }),
    });
    const t = await res.json();
    if (!res.ok) throw new Error(t.error ?? "refresh failed");
    return {
      ...token,
      access_token: t.access_token,
      refresh_token: t.refresh_token ?? token.refresh_token,
      id_token: t.id_token ?? token.id_token,
      expires_at: Math.floor(Date.now() / 1000) + t.expires_in,
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshTokenError" };
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Keycloak({
      clientId: CLIENT_ID,
      issuer: ISSUER,
      // Public PKCE client: no client secret; passwords are typed only into Keycloak.
      client: { token_endpoint_auth_method: "none" },
    }),
  ],
  pages: { signIn: "/login" },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        return {
          ...token,
          access_token: account.access_token,
          refresh_token: account.refresh_token,
          id_token: account.id_token,
          expires_at: account.expires_at,
          error: undefined,
        };
      }
      if (token.error) return token;
      if (Date.now() < ((token.expires_at as number) - 30) * 1000) return token;
      return refresh(token);
    },
    async session({ session, token }) {
      return {
        ...session,
        access_token: token.access_token as string | undefined,
        id_token: token.id_token as string | undefined,
        error: token.error as string | undefined,
      };
    },
  },
});
