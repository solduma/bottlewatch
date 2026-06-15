"use client";

import { useMemo, useRef, useState, useEffect } from "react";
import type { ChainNode } from "./chainLayout";
import { useMapStore, type SectorFilter } from "../lib/store";
import { displayName } from "../lib/score_help";

interface SearchHit {
  node: ChainNode;
  /** Set when the query matched a company ticker or name. */
  matchedCompany?: string;
}

/**
 * Search + sector filter + cohort-heatmap dropdown for the
 * /map page. All state lives in `useMapStore`; this
 * component is pure presentation.
 *
 * Three orthogonal controls:
 *
 * 1. Search bar — type to filter the visible node set by
 *    label, slug, sector, or company (ticker/name).
 *    Autocomplete shows node and company matches with
 *    sector context. Enter selects the top hit.
 *
 * 2. Sector chips — toggle which sectors are visible.
 *    "All" is the default. Edges between visible nodes
 *    are still drawn.
 *
 * 3. Cohort dropdown — pick a single segment; the graph
 *    recolors every node by that segment's regime rather
 *    than each node's own. The "View as: none" option
 *    restores the per-node colorization. This is the v1
 *    "cohort heatmap" — see plan 2026-06-12-value-chain-map.
 */
export function MapSearch({
  nodes,
  onSelect,
}: {
  nodes: ChainNode[] | null;
  onSelect: (id: string) => void;
}) {
  const searchQuery = useMapStore((s) => s.searchQuery);
  const setSearchQuery = useMapStore((s) => s.setSearchQuery);
  const sectorFilter = useMapStore((s) => s.sectorFilter);
  const setSectorFilter = useMapStore((s) => s.setSectorFilter);
  const cohortSegment = useMapStore((s) => s.cohortSegment);
  const setCohortSegment = useMapStore((s) => s.setCohortSegment);
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

  // The 8 segments that have scoring data (i.e. the cohort
  // candidates). Pulled from the loaded nodes by filtering
  // for ones whose regime is non-null.
  const scoringSegments = useMemo(() => {
    if (!nodes) return [] as ChainNode[];
    return nodes.filter((n) => n.regime !== null && n.regime !== undefined);
  }, [nodes]);

  // Top 8 search hits — node matches first, then company
  // matches. Each hit carries the node + optionally which
  // company matched, so the dropdown can show "TSM → Advanced
  // Node Fabs" for company queries.
  const hits = useMemo(() => {
    if (!nodes || !searchQuery.trim()) return [] as SearchHit[];
    const q = searchQuery.toLowerCase();
    const nodeHits: SearchHit[] = [];
    const companyHits: SearchHit[] = [];
    for (const n of nodes) {
      const name = displayName(n.id).toLowerCase();
      if (
        n.id.toLowerCase().includes(q) ||
        (n.label ?? "").toLowerCase().includes(q) ||
        name.includes(q) ||
        n.sector.toLowerCase().includes(q)
      ) {
        nodeHits.push({ node: n });
        continue;
      }
      if (n.companies && n.companies.length > 0) {
        for (const c of n.companies) {
          if (c.toLowerCase().includes(q)) {
            companyHits.push({ node: n, matchedCompany: c });
          }
        }
      }
    }
    return [...nodeHits, ...companyHits].slice(0, 8);
  }, [nodes, searchQuery]);

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    switch (e.key) {
      case "Enter":
        if (hits.length > 0 && highlightedIndex >= 0) {
          onSelect(hits[highlightedIndex].node.id);
          // Set search query to the selected node's display name
          const name = displayName(hits[highlightedIndex].node.id);
          setSearchQuery(name);
          setShowDropdown(false);
          setHighlightedIndex(-1);
        } else if (hits.length > 0) {
          onSelect(hits[0].node.id);
          const name = displayName(hits[0].node.id);
          setSearchQuery(name);
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

  return (
    <div className="rounded border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-3">
        {/* Search input */}
        <div ref={searchRef} className="relative flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search nodes, companies, tickers…"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setShowDropdown(true);
            }}
            onKeyDown={handleSearchKeyDown}
            onFocus={() => setShowDropdown(true)}
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
            aria-label="Search value chain nodes"
          />
          {showDropdown && hits.length > 0 && (
            <ul
              className="absolute z-10 mt-1 max-h-72 w-full overflow-y-auto rounded border border-gray-200 bg-white shadow-md"
              role="listbox"
            >
              {hits.map((hit, idx) => {
                const name = displayName(hit.node.id);
                const sector = (hit.node.sector ?? "").replace(/Sector$/, "");
                const displayLabel = name || hit.node.label || hit.node.id;
                return (
                  <li key={`${hit.node.id}-${hit.matchedCompany ?? ""}`}>
                    <button
                      className={`block w-full px-3 py-1.5 text-left text-xs ${
                        idx === highlightedIndex
                          ? "bg-blue-100 text-blue-800"
                          : "hover:bg-blue-50"
                      }`}
                      onClick={() => {
                        onSelect(hit.node.id);
                        // Set search query to the selected node's display name
                        const name = displayName(hit.node.id);
                        setSearchQuery(name);
                        setShowDropdown(false);
                        setHighlightedIndex(-1);
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium truncate">{displayLabel}</span>
                        <span className="ml-2 shrink-0 text-[10px] text-gray-400">{sector}</span>
                      </div>
                      {hit.matchedCompany && (
                        <div className="mt-0.5 text-[10px] text-blue-600">
                          🏢 {hit.matchedCompany}
                        </div>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Sector chips */}
        <div
          className="inline-flex rounded border border-gray-300"
          role="group"
          aria-label="Filter by sector"
        >
          {(["all", "Materials", "Hardware", "Infrastructure", "Downstream"] as SectorFilter[]).map(
            (s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSectorFilter(s)}
                className={`px-2.5 py-1 text-xs ${
                  sectorFilter === s
                    ? "bg-gray-900 text-white"
                    : "text-gray-700 hover:bg-gray-50"
                }`}
                aria-pressed={sectorFilter === s}
              >
                {s === "all" ? "All" : s}
              </button>
            ),
          )}
        </div>

        {/* Cohort dropdown */}
        <label className="flex items-center gap-2 text-xs text-gray-700">
          <span>View as:</span>
          <select
            value={cohortSegment ?? ""}
            onChange={(e) => setCohortSegment(e.target.value || null)}
            className="rounded border border-gray-300 px-2 py-1 text-xs"
            aria-label="Cohort segment for heatmap"
          >
            <option value="">— none —</option>
            {scoringSegments.map((s) => (
              <option key={s.id} value={s.id}>
                {displayName(s.id)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
