"use client";

import { Fragment, useState } from "react";
import type { Regime, SegmentScore } from "../lib/api";
import { SegmentBadge } from "./SegmentBadge";
import { QuadrantTickerList } from "./QuadrantTickerList";

/**
 * 2x2 regime quadrant per plan §5.
 *
 *       B' ▲
 *          │  EMERGING      PEAKING       RESOLVING
 *  +tight   │  (low B)       (high B)      (high B)
 *          │  ★ PROACTIVE    hold/trim     SHORT or skip
 *          ├─────────────────────────────────────────
 *  stable   │  EMERGING      STABLE        RESOLVING
 *          │  (low B)        (med B)       (low B)
 *  -loose   │  too early     wait          not yet long
 *          └────────────────────────► B
 *
 * The cell positions are determined by the regime label, not by
 * B and B' directly — this matches the plan's mapping and keeps
 * the cell positions stable for the user.
 */
type CellKey = "top-left" | "top-mid" | "top-right" | "bot-left" | "bot-mid" | "bot-right";

const CELL_REGIMES: Record<CellKey, Regime> = {
  "top-left": "EMERGING",       // high B', high B (PEAKING sibling)
  "top-mid": "PEAKING",         // high B', plateauing (peak)
  "top-right": "RESOLVING",     // high B, falling fast
  "bot-left": "EMERGING",       // low B, rising (proactive long)
  "bot-mid": "STABLE",          // low B, stable
  "bot-right": "RESOLVING_FROM_LOW", // low B, falling
};

const CELL_LABELS: Record<CellKey, string> = {
  "top-left": "EMERGING (rising fast)",
  "top-mid": "PEAKING",
  "top-right": "RESOLVING (skip long)",
  "bot-left": "EMERGING ★ PROACTIVE LONG",
  "bot-mid": "STABLE",
  "bot-right": "RESOLVING-from-low",
};

const CELL_HINTS: Record<CellKey, string> = {
  "top-left": "Trim longs — too late",
  "top-mid": "Hold or trim (no new longs)",
  "top-right": "SHORT or skip longs",
  "bot-left": "Proactive long before consensus",
  "bot-mid": "Wait for confirmation",
  "bot-right": "Not yet a long; watch for re-emergence",
};

function cellFor(regime: Regime): CellKey {
  switch (regime) {
    case "EMERGING":
      // Both top-left and bot-left map to EMERGING; the B value disambiguates.
      // The caller decides based on B.
      return "bot-left";
    case "PEAKING":
      return "top-mid";
    case "PEAKED":
      return "top-mid"; // treat PEAKED as the PEAKING cell for the quadrant
    case "RESOLVING":
      return "top-right";
    case "RESOLVING_FROM_LOW":
      return "bot-right";
    case "STABLE":
      return "bot-mid";
    case "NO_DATA":
      return "bot-mid";
  }
}

export function RegimeQuadrant({ rows }: { rows: SegmentScore[] }) {
  // One expanded segment at a time. Clicking a different badge
  // closes the previous one and opens the new one. Clicking the
  // same badge again toggles it closed. This matches the user-
  // selected preview in the 2026-06-11 plan.
  const [expandedSegment, setExpandedSegment] = useState<string | null>(null);

  function handleToggle(segment: string) {
    setExpandedSegment((prev) => (prev === segment ? null : segment));
  }

  // Bucket rows into the 6 cells.
  const buckets: Record<CellKey, SegmentScore[]> = {
    "top-left": [],
    "top-mid": [],
    "top-right": [],
    "bot-left": [],
    "bot-mid": [],
    "bot-right": [],
  };

  for (const r of rows) {
    if (r.score === null) {
      // No score → put in STABLE bucket with NO_DATA badge.
      buckets["bot-mid"].push(r);
      continue;
    }
    let key = cellFor(r.regime);
    // For EMERGING, disambiguate: high B → top-left, low B → bot-left.
    // The regime label "EMERGING" with high B is technically the
    // "trim longs, too late" cell; but in practice EMERGING is
    // defined as low B + rising, so this branch is rare.
    if (r.regime === "EMERGING" && r.score >= 60) {
      key = "top-left";
    }
    buckets[key].push(r);
  }

  // Sort each bucket by score desc.
  for (const k of Object.keys(buckets) as CellKey[]) {
    buckets[k].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  }

  const order: CellKey[] = [
    "top-left", "top-mid", "top-right",
    "bot-left", "bot-mid", "bot-right",
  ];

  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      <div className="grid grid-cols-[60px_1fr_1fr_1fr] gap-2">
        {/* Header row */}
        <div></div>
        <div className="text-center text-xs font-semibold uppercase tracking-wide text-gray-500">
          Tightening →
        </div>
        <div className="text-center text-xs font-semibold uppercase tracking-wide text-gray-500">
          Plateauing
        </div>
        <div className="text-center text-xs font-semibold uppercase tracking-wide text-gray-500">
          Loosening fast →
        </div>

        {/* Row 1: B ≥ 60 */}
        <div className="flex items-center justify-end pr-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          B ≥ 60
        </div>
        {order.slice(0, 3).map((k) => (
          <Cell
            key={k}
            cellKey={k}
            rows={buckets[k]}
            expandedSegment={expandedSegment}
            onToggle={handleToggle}
          />
        ))}

        {/* Row 2: B < 60 */}
        <div className="flex items-center justify-end pr-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          B &lt; 60
        </div>
        {order.slice(3, 6).map((k) => (
          <Cell
            key={k}
            cellKey={k}
            rows={buckets[k]}
            expandedSegment={expandedSegment}
            onToggle={handleToggle}
          />
        ))}
      </div>
    </div>
  );
}

function Cell({
  cellKey,
  rows,
  expandedSegment,
  onToggle,
}: {
  cellKey: CellKey;
  rows: SegmentScore[];
  expandedSegment: string | null;
  onToggle: (segment: string) => void;
}) {
  return (
    <div className="min-h-[100px] rounded border border-dashed border-gray-200 bg-gray-50/50 p-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-600">
        {CELL_LABELS[cellKey]}
      </div>
      <div className="text-[10px] text-gray-500">{CELL_HINTS[cellKey]}</div>
      {rows.length === 0 ? (
        <div className="mt-2 text-[10px] italic text-gray-400">(empty)</div>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap gap-1">
            {rows.map((r) => (
              <Fragment key={r.segment}>
                <SegmentBadge
                  segment={r.segment}
                  score={r.score}
                  regime={r.regime}
                  onToggle={onToggle}
                  expanded={expandedSegment === r.segment}
                />
              </Fragment>
            ))}
          </div>
          {expandedSegment &&
            rows.some((r) => r.segment === expandedSegment) && (
              <QuadrantTickerList
                key={expandedSegment}
                segment={expandedSegment}
              />
            )}
        </>
      )}
    </div>
  );
}
