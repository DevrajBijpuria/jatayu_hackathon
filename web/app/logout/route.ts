import { auth } from "@/auth";

// Sign-out ends the Keycloak session too, so the next "Sign in" asks for credentials
// (needed to switch between users). The login page then clears the local session.
export async function GET(req: Request) {
  const back = new URL("/login?reason=signedout", req.url).toString();
  const session = (await auth()) as { id_token?: string } | null;
  if (!session?.id_token) return Response.redirect(back);

  const url = new URL(`${process.env.OIDC_ISSUER}/protocol/openid-connect/logout`);
  url.searchParams.set("id_token_hint", session.id_token);
  url.searchParams.set("post_logout_redirect_uri", back);
  return Response.redirect(url.toString());
}
