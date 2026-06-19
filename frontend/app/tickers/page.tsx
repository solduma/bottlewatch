"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import type { TickerRow } from "../lib/api";
import { listTickers, listSegments } from "../lib/api";
import { regimePill } from "../lib/colors";
import { displayName } from "../lib/score_help";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Skeleton } from "../components/ui/Skeleton";
import { PageHeader } from "../components/ui/PageHeader";

type SectorFilter = "all" | "Materials" | "Hardware" | "Infrastructure" | "Downstream";

interface SearchHit {
  ticker?: string;
  name?: string;
  segment?: string;
  type: "ticker" | "company" | "segment";
}

type Side = "long" | "short" | "all";

export default function TickersPage() {
  const [tickers, setTickers] = useState<TickerRow[]>([]);
  const [allSegments, setAllSegments] = useState<string[]>([]);
  // segment slug → sector, sourced from the segments API (which reads
  // research/00_value_chain.json, the single source of truth).
  const [segmentToSector, setSegmentToSector] = useState<Map<string, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterSide, setFilterSide] = useState<Side>("all");
  const [filterRegime, setFilterRegime] = useState<string>("");
  const [filterSegment, setFilterSegment] = useState<string>("");
  const [filterSector, setFilterSector] = useState<SectorFilter>("all");
  const [sortKey, setSortKey] = useState<keyof TickerRow>("segment");
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [showDropdown, setShowDropdown] = useState<boolean>(false);
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);
  const searchRef = useRef<HTMLDivElement>(null);

  // Hide dropdown when clicking outside the search container.
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!searchRef.current) return;
      if (!searchRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const hits = useMemo(() => {
    if (!searchQuery.trim()) return [] as SearchHit[];
    const q = searchQuery.toLowerCase();
    const tickerHits: SearchHit[] = [];
    const companyHits: SearchHit[] = [];
    const segmentHits: SearchHit[] = [];

    // Ticker hits
    for (const t of tickers) {
      if (t.ticker.toLowerCase().includes(q)) {
        tickerHits.push({ ticker: t.ticker, name: t.name, type: "ticker" });
        continue;
      }
      if (t.name.toLowerCase().includes(q)) {
        companyHits.push({ ticker: t.ticker, name: t.name, type: "company" });
        continue;
      }
    }

    // Segment hits
    for (const s of allSegments) {
      if (displayName(s).toLowerCase().includes(q)) {
        segmentHits.push({ segment: s, type: "segment" });
      }
    }

    // Combine and limit to top 8 hits
    return [...tickerHits, ...companyHits, ...segmentHits].slice(0, 8);
  }, [tickers, allSegments, searchQuery]);

  // Handle enter key in search input to select top hit
  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    switch (e.key) {
      case "Enter":
        if (hits.length > 0 && highlightedIndex >= 0) {
          const hit = hits[highlightedIndex];
          if (hit.type === "ticker") {
            setSearchQuery(hit.ticker!);
          } else if (hit.type === "company") {
            setSearchQuery(hit.name!);
          } else if (hit.type === "segment") {
            setFilterSegment(hit.segment!);
            setSearchQuery("");
          }
          setShowDropdown(false);
          setHighlightedIndex(-1);
        } else if (hits.length > 0) {
          const hit = hits[0];
          if (hit.type === "ticker") {
            setSearchQuery(hit.ticker!);
          } else if (hit.type === "company") {
            setSearchQuery(hit.name!);
          } else if (hit.type === "segment") {
            setFilterSegment(hit.segment!);
            setSearchQuery("");
          }
          setShowDropdown(false);
        }
        break;
      case "ArrowDown":
        e.preventDefault();
        if (hits.length > 0) {
          setHighlightedIndex((prev) => (prev === hits.length - 1 ? 0 : prev + 1));
        }
        break;
      case "ArrowUp":
        e.preventDefault();
        if (hits.length > 0) {
          setHighlightedIndex((prev) => (prev <= 0 ? hits.length - 1 : prev - 1));
        }
        break;
      case "Escape":
        setSearchQuery("");
        setShowDropdown(false);
        setHighlightedIndex(-1);
        break;
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tickerData, segmentData] = await Promise.all([
        listTickers(),
        listSegments(),
      ]);
      setTickers(tickerData);
      const segmentsSet = new Set<string>();
      const sectorMap = new Map<string, string>();
      segmentData.forEach(seg => {
        segmentsSet.add(seg.segment);
        if (seg.sector) sectorMap.set(seg.segment, seg.sector);
      });
      setAllSegments([...segmentsSet].sort());
      setSegmentToSector(sectorMap);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // const segments = [...new Set(tickers.map(t => t.segment))].sort();
  //
  // `segmentToSector` is populated in `load()` from the segments API
  // (which reads research/00_value_chain.json) — no hardcoded map.

  const filtered = tickers
    .filter(t => {
      // Search filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const tickerMatch = t.ticker.toLowerCase().includes(q);
        const nameMatch = t.name.toLowerCase().includes(q);
        const segmentMatch = displayName(t.segment).toLowerCase().includes(q);
        if (!tickerMatch && !nameMatch && !segmentMatch) {
          return false;
        }
      }
      // Sector filter
      if (filterSector !== "all") {
        const sector = segmentToSector.get(t.segment);
        if (!sector) return false;
        if (sector.replace(/Sector$/, "") !== filterSector) {
          return false;
        }
      }
      // Existing filters
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

  if (loading) {
    return (
      <section>
        <div className="mb-4 flex items-center justify-between">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-5 w-32" />
        </div>
        <Skeleton className="mb-4 h-9 w-full max-w-2xl" />
        <div className="rounded border border-gray-200 bg-white p-3">
          <Skeleton className="mb-3 h-8 w-full" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="mb-2 h-10 w-full" />
          ))}
        </div>
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        title="Tickers"
        action={<Link href="/" className="text-sm text-blue-700 hover:underline">← Back to quadrant</Link>}
      />

      <div className="mb-4 flex flex-wrap gap-3">
        {/* Search input */}
        <div ref={searchRef} className="relative flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search tickers, companies, segments…"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setShowDropdown(true);
            }}
            onKeyDown={handleSearchKeyDown}
            onFocus={() => setShowDropdown(true)}
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
            aria-label="Search tickers"
          />
          {showDropdown && hits.length > 0 && (
            <ul
              className="absolute z-10 mt-1 max-h-72 w-full overflow-y-auto rounded border border-gray-200 bg-white shadow-md"
              role="listbox"
            >
              {hits.map((hit, idx) => (
                <li key={`${idx}-${hit.ticker || hit.name || hit.segment}`}>
                  <button
                    className={`block w-full px-3 py-1.5 text-left text-xs ${
                      idx === highlightedIndex
                        ? "bg-blue-100 text-blue-800"
                        : "hover:bg-blue-50"
                    }`}
                    onClick={() => {
                      if (hit.type === "ticker") {
                        setSearchQuery(hit.ticker!);
                      } else if (hit.type === "company") {
                        setSearchQuery(hit.name!);
                      } else if (hit.type === "segment") {
                        setFilterSegment(hit.segment!);
                        setSearchQuery("");
                      }
                      setShowDropdown(false);
                      setHighlightedIndex(-1);
                    }}
                  >
                    {hit.type === "ticker" && (
                      <div className="flex items-center justify-between">
                        <span className="font-mono font-medium">{hit.ticker}</span>
                        <span className="ml-2 shrink-0 text-[10px] text-gray-400">Ticker</span>
                      </div>
                    )}
                    {hit.type === "company" && (
                      <div className="flex items-center justify-between">
                        <span className="font-medium truncate">{hit.name}</span>
                        <span className="ml-2 shrink-0 text-[10px] text-gray-400">
                          {hit.ticker}
                        </span>
                      </div>
                    )}
                    {hit.type === "segment" && (
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{displayName(hit.segment!)}</span>
                        <span className="ml-2 shrink-0 text-[10px] text-gray-400">Segment</span>
                      </div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

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
          value={filterSector}
          onChange={e => setFilterSector(e.target.value as SectorFilter)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="all">All sectors</option>
          <option value="Materials">Materials</option>
          <option value="Hardware">Hardware</option>
          <option value="Infrastructure">Infrastructure</option>
          <option value="Downstream">Downstream</option>
        </select>

        <select
          value={filterSegment}
          onChange={e => setFilterSegment(e.target.value)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="">All segments</option>
          {allSegments.map(s => <option key={s} value={s}>{displayName(s)}</option>)}
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
          {`${filtered.length} of ${tickers.length} tickers`}
        </span>
      </div>

      {error && (
        <div className="mb-4">
          <ErrorState
            title="Failed to load tickers"
            message={error}
            onRetry={load}
          />
        </div>
      )}

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="sticky-first-col w-full text-sm">
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
                  <Link href={`/segment/${t.segment}`} className="hover:underline">{displayName(t.segment)}</Link>
                </td>
                <td className="px-3 py-2 font-mono text-right text-gray-600">
                  {t.exposure_pct === null ? "—" : `${t.exposure_pct.toFixed(0)}%`}
                </td>
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
            {filtered.length === 0 && !error && (
              <tr>
                <td colSpan={7} className="px-3 py-6">
                  <EmptyState
                    title="No tickers match the current filters"
                    description="Try adjusting the search, sector, segment, regime, or side filters."
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
