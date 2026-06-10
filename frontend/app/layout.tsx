import "./globals.css";
import type { ReactNode } from "react";
import Link from "next/link";
import { getHealth } from "./lib/api";

export const metadata = {
  title: "Bottlewatch",
  description: "AI supply chain bottleneck dashboard",
};

const NAV_LINKS = [
  { href: "/", label: "Quadrant" },
  { href: "/scoreboard", label: "Scoreboard" },
  { href: "/tickers", label: "Tickers" },
  { href: "/map", label: "Map" },
  { href: "/thesis", label: "Thesis" },
];

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
    <html lang="en">
      <body className="bg-gray-50 text-gray-900">
        <header className="border-b border-gray-200 bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <div className="flex items-center gap-4">
              <a href="/" className="text-lg font-semibold tracking-tight">Bottlewatch</a>
              <nav className="flex gap-1">
                {NAV_LINKS.map(l => (
                  <Link
                    key={l.href}
                    href={l.href}
                    className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100"
                  >
                    {l.label}
                  </Link>
                ))}
              </nav>
            </div>
            <span
              className={`text-xs ${dbOk ? "text-emerald-700" : "text-amber-700"}`}
              title={lastScore ?? "no recompute yet"}
            >
              {dbOk ? "DB ok" : "DB unknown"} · last score:{" "}
              {lastScore ? new Date(lastScore).toLocaleString() : "—"}
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
