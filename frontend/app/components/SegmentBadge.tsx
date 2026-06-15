"use client";

import Link from "next/link";
import type { Regime } from "../lib/api";
import { regimePill } from "../lib/colors";

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
  name,
  score,
  regime,
  href,
  onToggle,
  expanded,
}: {
  segment: string;
  /** Human-readable title (e.g. "Transformers & Switchgear (T&D)"). */
  name?: string;
  score: number | null;
  regime: Regime;
  /** If provided, render the badge as a navigation link. */
  href?: string;
  /** If provided, render the badge as a button that calls back. */
  onToggle?: (segment: string, el: HTMLElement) => void;
  /** Visual state when onToggle is used — adds a ring emphasis. */
  expanded?: boolean;
}) {
  const color = regimePill(regime);
  const ringWidth = expanded ? "ring-2 ring-offset-1" : "ring-1";
  const display = name && name !== segment ? name : segment;
  const content = (
    <>
      <span className="font-mono text-xs leading-none">
        {score === null ? "—" : score.toFixed(0)}
      </span>
      <span className="truncate text-[10px] uppercase tracking-wide leading-none opacity-90">
        {display}
      </span>
    </>
  );

  if (href !== undefined) {
    return (
      <Link
        href={href}
        title={name ? `${name} (${segment})` : segment}
        className={`flex flex-col rounded px-2 py-1 text-xs font-medium transition hover:ring-2 ${color}`}
      >
        {content}
      </Link>
    );
  }
  if (onToggle !== undefined) {
    return (
      <button
        type="button"
        onClick={(e) => onToggle(segment, e.currentTarget)}
        aria-expanded={expanded}
        title={name ? `${name} (${segment})` : segment}
        className={`flex flex-col rounded px-2 py-1 text-xs font-medium ${ringWidth} transition hover:ring-2 ${color}`}
      >
        {content}
      </button>
    );
  }
  // Fallback: plain div (no interaction). Used in tests / stories.
  return (
    <div
      title={name ? `${name} (${segment})` : segment}
      className={`flex flex-col rounded px-2 py-1 text-xs font-medium ${color}`}
    >
      {content}
    </div>
  );
}
