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
  "top-left": "EMERGING (too late)",
  "top-mid": "PEAKING",
  "top-right": "RESOLVING (skip long)",
  "bot-left": "EMERGING — PROACTIVE LONG",
  "bot-mid": "STABLE",
  "bot-right": "RESOLVING-from-low",
};

const CELL_HINTS: Record<CellKey, string> = {
  "top-left": "Trim longs — entry window has closed",
  "top-mid": "Hold or trim (no new longs)",
  "top-right": "SHORT or skip longs",
  "bot-left": "Proactive long before consensus",
  "bot-mid": "Wait for confirmation",
  "bot-right": "Not yet a long; watch for re-emergence",
};

const CELL_PREFIXES: Record<CellKey, string | null> = {
  "top-left": "↗",
  "top-mid": null,
  "top-right": null,
  "bot-left": "↘",
  "bot-mid": null,
  "bot-right": null,
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
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  function handleToggle(segment: string, el: HTMLElement) {
    if (expandedSegment === segment) {
      setExpandedSegment(null);
      setAnchorEl(null);
    } else {
      setExpandedSegment(segment);
      setAnchorEl(el);
    }
  }

  function handleClose() {
    // Return focus to the badge that opened the dialog-like popup.
    anchorEl?.focus();
    setExpandedSegment(null);
    setAnchorEl(null);
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

  const cell = (k: CellKey) => (
    <Cell
      key={k}
      cellKey={k}
      rows={buckets[k]}
      expandedSegment={expandedSegment}
      onToggle={handleToggle}
    />
  );

  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      {/* Desktop grid */}
      <div className="hidden grid-cols-[60px_1fr_1fr_1fr] grid-rows-[auto_1fr_1fr] gap-3 md:grid">
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
        {order.slice(0, 3).map(cell)}

        {/* Row 2: B < 60 */}
        <div className="flex items-center justify-end pr-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          B &lt; 60
        </div>
        {order.slice(3, 6).map(cell)}
      </div>

      {/* Mobile layout: each B threshold row stacks vertically */}
      <div className="space-y-4 md:hidden">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            B ≥ 60
          </div>
          <div className="space-y-2">{order.slice(0, 3).map(cell)}</div>
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            B &lt; 60
          </div>
          <div className="space-y-2">{order.slice(3, 6).map(cell)}</div>
        </div>
      </div>

      {/* Single popup for the whole quadrant. The cell grid is rendered
          twice (desktop + mobile layouts), so rendering the popup inside
          a cell would mount two instances — each fixed-positioned at the
          same spot, and each running an outside-click listener that tears
          the other down on mousedown, killing link clicks. Rendering once
          here against the anchor's rect avoids that. */}
      {expandedSegment && anchorEl && (
        <QuadrantTickerList
          key={expandedSegment}
          segment={expandedSegment}
          anchorEl={anchorEl}
          onClose={handleClose}
        />
      )}
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
  onToggle: (segment: string, el: HTMLElement) => void;
}) {
  const prefix = CELL_PREFIXES[cellKey];
  return (
    <div className="flex h-full min-h-[120px] flex-col gap-2 rounded border border-gray-200 bg-white p-3">
      <div className="flex items-start gap-1.5">
        {prefix && (
          <span className="text-xs text-gray-400" aria-hidden="true">
            {prefix}
          </span>
        )}
        <div className="flex-1">
          <div className="text-xs font-semibold uppercase tracking-wide text-gray-700">
            {CELL_LABELS[cellKey]}
          </div>
          <div className="text-[11px] leading-tight text-gray-500">
            {CELL_HINTS[cellKey]}
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="mt-auto text-[11px] italic text-gray-400">(empty)</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {rows.map((r) => (
            <Fragment key={r.segment}>
              <SegmentBadge
                segment={r.segment}
                name={r.name}
                score={r.score}
                regime={r.regime}
                onToggle={onToggle}
                expanded={expandedSegment === r.segment}
              />
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
