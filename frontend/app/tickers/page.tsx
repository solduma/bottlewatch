"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import type { TickerRow, Regime, Horizon } from "../lib/api";
import { listTickers } from "../lib/api";
import { regimePill } from "../lib/colors";

type Side = "long" | "short" | "all";

export default function TickersPage() {
  const [tickers, setTickers] = useState<TickerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterSide, setFilterSide] = useState<Side>("all");
  const [filterRegime, setFilterRegime] = useState<string>("");
  const [filterSegment, setFilterSegment] = useState<string>("");
  const [sortKey, setSortKey] = useState<keyof TickerRow>("segment");
  const [sortDir, setSortDir] = useState<1 | -1>(1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listTickers();
      setTickers(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const segments = [...new Set(tickers.map(t => t.segment))].sort();

  const filtered = tickers
    .filter(t => {
      if (filterSegment && t.segment !== filterSegment) return false;
      if (filterSide === "long" && t.regime === "RESOLVING") return false;
      if (filterSide === "short" && t.regime !== "RESOLVING") return false;
      if (filterRegime && t.regime !== filterRegime) return false;
      return true;
    })
    .sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return -sortDir;
      if (av > bv) return sortDir;
      return 0;
    });

  function toggleSort(key: keyof TickerRow) {
    if (sortKey === key) {
      setSortDir(d => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      setSortDir(1);
    }
  }

  const SIDE_OPTIONS: { label: string; value: Side }[] = [
    { label: "All", value: "all" },
    { label: "Long", value: "long" },
    { label: "Short", value: "short" },
  ];

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Tickers</h1>
        <Link href="/" className="text-sm text-blue-700 hover:underline">← Back to quadrant</Link>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="flex gap-1 rounded border border-gray-200 bg-white p-1 text-sm">
          {SIDE_OPTIONS.map(o => (
            <button
              key={o.value}
              onClick={() => setFilterSide(o.value)}
              className={`rounded px-2 py-1 transition-colors ${
                filterSide === o.value ? "bg-blue-100 text-blue-800 font-medium" : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>

        <select
          value={filterSegment}
          onChange={e => setFilterSegment(e.target.value)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="">All segments</option>
          {segments.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        <select
          value={filterRegime}
          onChange={e => setFilterRegime(e.target.value)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="">All regimes</option>
          {["PEAKING","PEAKED","RESOLVING","EMERGING","STABLE","RESOLVING_FROM_LOW","NO_DATA"].map(r => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <span className="ml-auto text-xs text-gray-500">
          {loading ? "Loading…" : `${filtered.length} of ${tickers.length} tickers`}
        </span>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>
      )}

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              {[
                { key: "ticker", label: "Ticker" },
                { key: "name", label: "Name" },
                { key: "segment", label: "Segment" },
                { key: "exposure_pct", label: "Exposure" },
                { key: "market_cap_bucket", label: "Mcap" },
                { key: "currency_hedge", label: "FX Hedge" },
                { key: "regime", label: "Regime" },
              ].map(col => (
                <th
                  key={col.key}
                  className="cursor-pointer px-3 py-2 select-none"
                  onClick={() => toggleSort(col.key as keyof TickerRow)}
                >
                  {col.label}
                  {sortKey === col.key && (sortDir === 1 ? " ↑" : " ↓")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(t => (
              <tr key={`${t.ticker}-${t.segment}`} className="border-t border-gray-100 hover:bg-gray-50">
                <td className="px-3 py-2">
                  <Link href={`/tickers/${t.ticker}`} className="font-mono font-medium text-blue-700 hover:underline">
                    {t.ticker}
                  </Link>
                </td>
                <td className="px-3 py-2 text-gray-700">{t.name}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-600">
                  <Link href={`/segment/${t.segment}`} className="hover:underline">{t.segment}</Link>
                </td>
                <td className="px-3 py-2 font-mono text-right text-gray-600">{t.exposure_pct.toFixed(0)}%</td>
                <td className="px-3 py-2 text-xs text-gray-500">{t.market_cap_bucket}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{t.currency_hedge || "—"}</td>
                <td className="px-3 py-2">
                  {t.regime && (
                    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${regimePill(t.regime)}`}>
                      {t.regime}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-sm text-gray-400 italic">
                  No tickers match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
