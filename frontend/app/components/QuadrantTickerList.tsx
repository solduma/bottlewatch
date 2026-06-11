"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listTickers } from "../lib/api";
import type { TickerRow } from "../lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ready"; tickers: TickerRow[] }
  | { kind: "error"; message: string };

/**
 * Inline ticker list for a single segment, rendered under a
 * quadrant cell when the user clicks a SegmentBadge. Sorted by
 * `exposure_pct` desc per the methodology §4 conviction basket
 * rule. Each row is a link to `/tickers/[ticker]`.
 *
 * The fetch fires once on mount; the result is cached in
 * component state for the lifetime of the page. Re-mounting
 * (e.g. clicking the same segment again to collapse, then
 * expanding) re-fetches — acceptable for a 10-row response.
 *
 * For a larger universe we'd want to share this fetch with
 * other components; the cost of duplication today is one
 * small GET that returns in <50ms.
 */
export function QuadrantTickerList({ segment }: { segment: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    listTickers(segment)
      .then((rows) => {
        if (cancelled) return;
        // Sort by exposure_pct desc, then by ticker asc for ties.
        const sorted = [...rows].sort((a, b) => {
          const ae = a.exposure_pct ?? 0;
          const be = b.exposure_pct ?? 0;
          if (be !== ae) return be - ae;
          return a.ticker.localeCompare(b.ticker);
        });
        setState({ kind: "ready", tickers: sorted });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [segment]);

  if (state.kind === "loading") {
    return (
      <div className="mt-2 text-[10px] italic text-gray-400">
        Loading tickers…
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div
        className="mt-2 text-[10px] text-red-500"
        title={state.message}
        role="img"
        aria-label="Ticker list unavailable"
      >
        (tickers unavailable)
      </div>
    );
  }
  if (state.tickers.length === 0) {
    return (
      <div className="mt-2 text-[10px] italic text-gray-400">
        (no tickers for this segment)
      </div>
    );
  }

  return (
    <ul
      className="mt-2 space-y-0.5 border-t border-dashed border-gray-200 pt-1.5"
      aria-label={`Tickers for ${segment}`}
    >
      {state.tickers.map((t) => (
        <li key={t.ticker}>
          <Link
            href={`/tickers/${encodeURIComponent(t.ticker)}`}
            className="flex items-center gap-2 rounded px-1.5 py-0.5 text-[11px] hover:bg-gray-100"
          >
            <span className="font-mono font-medium text-blue-700">
              {t.ticker}
            </span>
            <span className="flex-1 truncate text-gray-700">{t.name}</span>
            <span className="font-mono text-gray-500">
              {t.exposure_pct}%
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
