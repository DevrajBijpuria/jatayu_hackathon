import type { Metadata } from "next";
import "./globals.css";
import { SessionProvider } from "next-auth/react";
import { UserProvider } from "@/lib/user-context";
import NavShell from "@/components/nav-shell";

export const metadata: Metadata = {
  title: "TruthGuard",
  description: "Regulatory Document Intelligence — Virtusa Jatayu S6",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50">
        {/* Re-read the session every minute so 5-minute access tokens refresh in time. */}
        <SessionProvider refetchInterval={60}>
          <UserProvider>
            <NavShell>{children}</NavShell>
          </UserProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
