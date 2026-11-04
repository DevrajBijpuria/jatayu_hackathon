import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Keycloak({
      clientId: process.env.OIDC_CLIENT_ID!,
      issuer: process.env.OIDC_ISSUER!,
      // Public PKCE client — no clientSecret
    }),
  ],
  callbacks: {
    async jwt({ token, account }) {
      if (account?.access_token) {
        token.access_token = account.access_token;
      }
      return token;
    },
    async session({ session, token }) {
      (session as typeof session & { access_token?: string }).access_token =
        token.access_token as string | undefined;
      return session;
    },
  },
});
