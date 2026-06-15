import "./globals.css";
import type { ReactNode } from "react";
import Link from "next/link";
import { getHealth } from "./lib/api";
import { Nav } from "./components/Nav";

export const metadata = {
  title: "Bottlewatch",
  description: "AI supply chain bottleneck dashboard",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  let lastScore: string | null = null;
  let dbOk = false;
  try {
    const h = await getHealth();
    dbOk = h.db_ok;
    lastScore = h.last_score_at;
  } catch {
    // API not reachable — show "unknown" rather than crash the page.
  }
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="bg-gray-50 text-gray-900">
        <header className="border-b border-gray-200 bg-white">
          <div className="relative mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <div className="flex items-center gap-4">
              <Link href="/" className="text-lg font-semibold tracking-tight">Bottlewatch</Link>
              <Nav />
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${
                  dbOk
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800"
                }`}
                title={lastScore ?? "no recompute yet"}
                suppressHydrationWarning
              >
                {dbOk ? "DB ok" : "DB unknown"}
              </span>
              <span className="hidden text-gray-500 sm:inline" suppressHydrationWarning>
                {lastScore
                  ? new Date(lastScore).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "no score yet"}
              </span>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
