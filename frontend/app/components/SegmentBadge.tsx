"use client";

import Link from "next/link";
import type { Regime } from "../lib/api";

const REGIME_COLOR: Record<Regime, string> = {
  PEAKING: "bg-amber-100 text-amber-900 ring-amber-300",
  PEAKED: "bg-red-100 text-red-900 ring-red-300",
  RESOLVING: "bg-emerald-100 text-emerald-900 ring-emerald-300",
  EMERGING: "bg-blue-100 text-blue-900 ring-blue-300",
  STABLE: "bg-gray-100 text-gray-700 ring-gray-300",
  RESOLVING_FROM_LOW: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  NO_DATA: "bg-gray-50 text-gray-500 ring-gray-200",
};

/**
 * Clickable segment badge. Default behavior is a `<button>` that
 * fires `onToggle(segment)` so the parent (e.g. the quadrant) can
 * expand an inline ticker list. Pass `href` to render a
 * navigation link instead — used on `/segment/[slug]` and
 * `/tickers/[ticker]` for the standard drilldown.
 *
 * The split is intentional: the quadrant is a *summary* view
 * where the click should reveal ticker context without leaving
 * the page. The `/segment/[slug]` page is the deep-dive for
 * analysts who want sub-scores, signals, horizons.
 */
export function SegmentBadge({
  segment,
  score,
  regime,
  href,
  onToggle,
  expanded,
}: {
  segment: string;
  score: number | null;
  regime: Regime;
  /** If provided, render the badge as a navigation link. */
  href?: string;
  /** If provided, render the badge as a button that calls back. */
  onToggle?: (segment: string) => void;
  /** Visual state when onToggle is used — adds a ring emphasis. */
  expanded?: boolean;
}) {
  const color = REGIME_COLOR[regime] ?? REGIME_COLOR.NO_DATA;
  const ringWidth = expanded ? "ring-2 ring-offset-1" : "ring-1";
  const content = (
    <>
      <span className="font-mono text-sm">
        {score === null ? "—" : score.toFixed(0)}
      </span>
      <span className="text-[10px] uppercase tracking-wide opacity-80">
        {segment}
      </span>
    </>
  );

  if (href !== undefined) {
    return (
      <Link
        href={href}
        className={`flex flex-col gap-0.5 rounded px-3 py-1.5 text-xs font-medium ring-1 transition hover:ring-2 ${color}`}
      >
        {content}
      </Link>
    );
  }
  if (onToggle !== undefined) {
    return (
      <button
        type="button"
        onClick={() => onToggle(segment)}
        aria-expanded={expanded}
        className={`flex flex-col gap-0.5 rounded px-3 py-1.5 text-xs font-medium ${ringWidth} transition hover:ring-2 ${color}`}
      >
        {content}
      </button>
    );
  }
  // Fallback: plain div (no interaction). Used in tests / stories.
  return (
    <div className={`flex flex-col gap-0.5 rounded px-3 py-1.5 text-xs font-medium ring-1 ${color}`}>
      {content}
    </div>
  );
}
