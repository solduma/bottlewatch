"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { Horizon, SegmentScore } from "../lib/api";
import { RegimeBadge } from "./RegimeBadge";
import { Sparkline } from "./Sparkline";
import { useBatchedScoreHistory } from "./SparklineForSegments";
import { SCORE_HELP, displayName } from "../lib/score_help";

type SortKey = "segment" | "near" | "med" | "long" | "data_completeness";

function pickScore(row: SegmentScore, h: Horizon): number {
  if (row.horizon === h) return row.score ?? -1;
  return -1;
}

export function ScoreboardTable({ rows }: { rows: SegmentScore[] }) {
  // Pivot: one row per segment, columns per horizon.
  const segments = useMemo(() => {
    const bySeg = new Map<string, Record<Horizon, SegmentScore>>();
    for (const r of rows) {
      const m = bySeg.get(r.segment) ?? ({} as Record<Horizon, SegmentScore>);
      m[r.horizon] = r;
      bySeg.set(r.segment, m);
    }
    return Array.from(bySeg.entries())
      .map(([segment, horizons]) => ({
        segment,
        near: horizons.near,
        med: horizons.med,
        long: horizons.long,
        data_completeness:
          horizons.near?.data_completeness ??
          horizons.med?.data_completeness ??
          horizons.long?.data_completeness ??
          0,
      }))
      .sort((a, b) => a.segment.localeCompare(b.segment));
  }, [rows]);

  const [sortKey, setSortKey] = useState<SortKey>("segment");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // Range for the Trend (sparkline) column. 1/3/6/12 months.
  // Default 6mo preserves the original behavior. Changing the
  // value re-keys `useBatchedScoreHistory` (via the `months`
  // argument), which triggers a refetch.
  const [trendMonths, setTrendMonths] = useState<1 | 3 | 6 | 12>(6);

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1;
    return [...segments].sort((a, b) => {
      const av: number | string =
        sortKey === "segment"
          ? a.segment
          : sortKey === "data_completeness"
            ? a.data_completeness
            : pickScore(a[sortKey], sortKey);
      const bv: number | string =
        sortKey === "segment"
          ? b.segment
          : sortKey === "data_completeness"
            ? b.data_completeness
            : pickScore(b[sortKey], sortKey);
      if (typeof av === "string" && typeof bv === "string") {
        return dir * av.localeCompare(bv);
      }
      return dir * ((av as number) - (bv as number));
    });
  }, [segments, sortKey, sortDir]);

  // One batched fetch for all sparklines. `useBatchedScoreHistory`
  // issues a single GET /scores/history?segments=a,b,c call and
  // returns a Map keyed by segment. Per-row lookups below — this
  // replaces the previous N+1 design where each row had its own
  // useEffect + per-row fetch (10 round-trips for 10 rows).
  // The `months` arg is the user-controlled Trend range filter.
  const segmentSlugs = useMemo(() => sorted.map((s) => s.segment), [sorted]);
  const history = useBatchedScoreHistory(segmentSlugs, "near", trendMonths);

  function toggleSort(k: SortKey) {
    if (k === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(k);
      setSortDir(k === "segment" ? "asc" : "desc");
    }
  }

  function arrow(k: SortKey) {
    if (k !== sortKey) return "";
    return sortDir === "asc" ? " ↑" : " ↓";
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-gray-200 bg-white text-left text-xs uppercase tracking-wide text-gray-500">
          <th
            className="cursor-pointer px-3 py-2"
            onClick={() => toggleSort("segment")}
          >
            Segment{arrow("segment")}
          </th>
          {(["near", "med", "long"] as const).map((h) => (
            <th
              key={h}
              className="cursor-pointer px-3 py-2"
              onClick={() => toggleSort(h)}
              title={SCORE_HELP}
            >
              B·{h}{arrow(h)}
              <span
                aria-hidden="true"
                className="ml-1 cursor-help text-gray-400"
                title={SCORE_HELP}
              >
                ?
              </span>
            </th>
          ))}
          <th
            className="cursor-pointer px-3 py-2"
            onClick={() => toggleSort("data_completeness")}
          >
            Data{arrow("data_completeness")}
          </th>
          <th className="px-3 py-2" style={{ width: 120 }}>
            <div className="flex items-center gap-1">
              <span>Trend</span>
              <div
                className="ml-auto inline-flex rounded border border-gray-200 text-[10px]"
                role="group"
                aria-label="Trend range filter"
              >
                {([1, 3, 6, 12] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setTrendMonths(m)}
                    className={`px-1.5 py-0.5 ${
                      trendMonths === m
                        ? "bg-gray-900 text-white"
                        : "text-gray-500 hover:bg-gray-50"
                    }`}
                    aria-label={`${m} months`}
                    aria-pressed={trendMonths === m}
                  >
                    {m < 12 ? `${m}mo` : "1y"}
                  </button>
                ))}
              </div>
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((s) => {
          const display = displayName(s.segment);
          return (
          <tr key={s.segment} className="border-b border-gray-100">
            <td className="px-3 py-2 font-medium">
              <Link
                href={`/segment/${s.segment}`}
                className="text-blue-700 hover:underline"
                title={s.segment}
              >
                <div className="flex flex-col">
                  <span>{display || s.segment}</span>
                  {display && display !== s.segment && (
                    <span className="font-mono text-[10px] text-gray-500">
                      {s.segment}
                    </span>
                  )}
                </div>
              </Link>
            </td>
            {(["near", "med", "long"] as const).map((h) => {
              const cell = s[h];
              if (!cell) return <td key={h} className="px-3 py-2">—</td>;
              return (
                <td key={h} className="px-3 py-2">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-mono">
                      {cell.score === null ? "—" : cell.score.toFixed(1)}
                    </span>
                    <RegimeBadge regime={cell.regime} confidence={cell.regime_confidence} />
                  </div>
                </td>
              );
            })}
            <td className="px-3 py-2 font-mono text-gray-600">
              {(s.data_completeness * 100).toFixed(0)}%
            </td>
            <td className="px-3 py-2" style={{ width: 120 }}>
              {history.kind === "loading" ? (
                <div className="text-xs text-gray-400" style={{ height: 24 }}>…</div>
              ) : history.kind === "error" ? (
                <div className="text-xs text-red-400" style={{ height: 24 }}>err</div>
              ) : (
                <Sparkline
                  data={history.bySegment.get(s.segment) ?? []}
                  height={24}
                />
              )}
            </td>
          </tr>
          );
        })}
      </tbody>
    </table>
  );
}
