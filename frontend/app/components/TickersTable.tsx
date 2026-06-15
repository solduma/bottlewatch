"use client";

import { useMemo, useState } from "react";
import type { TickerRow } from "../lib/api";

type SortKey = "ticker" | "name" | "exposure_pct" | "market_cap" | "currency_hedge";

const LABELS: Record<SortKey, string> = {
  ticker: "Ticker",
  name: "Name",
  exposure_pct: "Exposure %",
  market_cap: "Market Cap",
  currency_hedge: "Currency Hedge",
};

function compareMarketCap(a: TickerRow, b: TickerRow): number {
  if (a.mcap_usd !== null && b.mcap_usd !== null) {
    return a.mcap_usd - b.mcap_usd;
  }
  if (a.mcap_usd !== null) return -1;
  if (b.mcap_usd !== null) return 1;
  return a.market_cap_bucket.localeCompare(b.market_cap_bucket);
}

const COMPARATORS: Record<SortKey, (a: TickerRow, b: TickerRow) => number> = {
  ticker: (a, b) => a.ticker.localeCompare(b.ticker),
  name: (a, b) => a.name.localeCompare(b.name),
  exposure_pct: (a, b) => a.exposure_pct - b.exposure_pct,
  market_cap: compareMarketCap,
  currency_hedge: (a, b) => a.currency_hedge.localeCompare(b.currency_hedge),
};

export function TickersTable({ tickers }: { tickers: TickerRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("ticker");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sorted = useMemo(() => {
    const rows = [...tickers];
    rows.sort(COMPARATORS[sortKey]);
    if (sortDir === "desc") rows.reverse();
    return rows;
  }, [tickers, sortKey, sortDir]);

  function handleHeaderClick(key: SortKey) {
    if (sortKey === key) {
      setSortDir(prev => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <div className="overflow-x-auto rounded border border-gray-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
          <tr>
            {(Object.keys(LABELS) as SortKey[]).map((key) => (
              <th
                key={key}
                className="cursor-pointer px-3 py-2 hover:bg-gray-100"
                onClick={() => handleHeaderClick(key)}
                aria-sort={sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
              >
                <span className="flex items-center gap-1">
                  {LABELS[key]}
                  {sortKey === key && (
                    <span className="text-gray-400">{sortDir === "asc" ? "↑" : "↓"}</span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr key={t.ticker} className="border-t border-gray-100">
              <td className="px-3 py-2 font-mono font-medium">
                <a
                  href={`/tickers/${t.ticker}`}
                  className="text-blue-700 hover:underline"
                >
                  {t.ticker}
                </a>
              </td>
              <td className="px-3 py-2 text-gray-700">{t.name}</td>
              <td className="px-3 py-2 font-mono text-gray-700">{t.exposure_pct}%</td>
              <td className="px-3 py-2 text-gray-700">{t.market_cap_bucket}</td>
              <td className="px-3 py-2 text-gray-700">{t.currency_hedge}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
