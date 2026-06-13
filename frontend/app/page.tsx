"use client";

import { useEffect, useState, useMemo } from "react";
import type { Horizon, SegmentScore } from "./lib/api";
import { listScoresRegime } from "./lib/api";
import { RegimeQuadrant } from "./components/RegimeQuadrant";
import { HorizonToggle } from "./components/HorizonToggle";
import { displayName } from "./lib/score_help";
import Link from "next/link";

type SectorFilter = "all" | "Materials" | "Hardware" | "Infrastructure" | "Downstream";

export default function ScoreboardPage() {
  const [horizon, setHorizon] = useState<Horizon>("near");
  const [rows, setRows] = useState<SegmentScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sectorFilter, setSectorFilter] = useState<SectorFilter>("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listScoresRegime(horizon)
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [horizon]);

  // Filter rows by sector.
  const filteredRows = useMemo(() => {
    if (sectorFilter === "all") return rows;
    return rows.filter((r) => {
      // Convert "MaterialsSector" → "Materials" for matching.
      return r.sector.replace(/Sector$/, "") === sectorFilter;
    });
  }, [rows, sectorFilter]);

  // Derive 3 lists from the filtered rows.
  const proactiveLongs = useMemo(
    () => filteredRows.filter((r) => r.regime === "EMERGING" && r.score !== null),
    [filteredRows],
  );
  const shorts = useMemo(
    () => filteredRows.filter((r) => r.regime === "RESOLVING" || r.regime === "RESOLVING_FROM_LOW"),
    [filteredRows],
  );
  const watchlist = useMemo(
    () => filteredRows.filter((r) => r.regime === "STABLE" && (r.momentum ?? 0) > 0),
    [filteredRows],
  );

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Regime quadrant</h1>
        <Link
          href="/scoreboard"
          className="text-sm text-blue-700 hover:underline"
        >
          Table view →
        </Link>
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <span className="text-sm text-gray-600">Horizon:</span>
        <HorizonToggle value={horizon} onChange={setHorizon} />
        <span className="text-sm text-gray-600">Sector:</span>
        <select
          value={sectorFilter}
          onChange={(e) => setSectorFilter(e.target.value as SectorFilter)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="all">All</option>
          <option value="Materials">Materials</option>
          <option value="Hardware">Hardware</option>
          <option value="Infrastructure">Infrastructure</option>
          <option value="Downstream">Downstream</option>
        </select>
        <span className="ml-auto text-xs text-gray-500">
          {loading ? "Loading…" : `${filteredRows.length} segments`}
        </span>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          Failed to load scores: {error}
        </div>
      )}

      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <DerivedList
          title="Proactive longs"
          subtitle="EMERGING — low B, rising"
          rows={proactiveLongs}
          colorClass="text-blue-700"
        />
        <DerivedList
          title="Shorts / avoid-long"
          subtitle="RESOLVING — high B, falling"
          rows={shorts}
          colorClass="text-emerald-700"
        />
        <DerivedList
          title="Watchlist"
          subtitle="STABLE with positive B'"
          rows={watchlist}
          colorClass="text-gray-700"
        />
      </div>

      {filteredRows.length > 0 && <RegimeQuadrant rows={filteredRows} />}

      <div className="mt-6 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <strong>Note:</strong> Momentum (B') requires 6mo of nightly recomputes
        to mature. First-run scores have B' = 0, so EMERGING and RESOLVING
        cells will be empty until that history accumulates.
      </div>
    </section>
  );
}

function DerivedList({
  title,
  subtitle,
  rows,
  colorClass,
}: {
  title: string;
  subtitle: string;
  rows: SegmentScore[];
  colorClass: string;
}) {
  return (
    <div className="rounded border border-gray-200 bg-white p-3">
      <h3 className={`text-sm font-semibold ${colorClass}`}>{title}</h3>
      <p className="mb-2 text-[11px] text-gray-500">{subtitle}</p>
      {rows.length === 0 ? (
        <p className="text-xs italic text-gray-400">(none)</p>
      ) : (
        <ul className="space-y-0.5">
          {rows.slice(0, 5).map((r) => {
            const name = displayName(r.name || r.segment);
            return (
              <li key={r.segment} className="text-xs">
                <Link
                  href={`/segment/${r.segment}`}
                  className="text-blue-700 hover:underline"
                  title={r.name ? `${name} (${r.segment})` : r.segment}
                >
                  <div className="flex flex-col">
                    <span>{name || r.segment}</span>
                    {name && name !== r.segment && (
                      <span className="font-mono text-[10px] text-gray-500">
                        {r.segment}
                      </span>
                    )}
                  </div>
                </Link>
                <span className="ml-1 text-gray-500">
                  ({r.score?.toFixed(0)} · B&apos;{r.momentum?.toFixed(1)})
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
