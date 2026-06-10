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

export function SegmentBadge({
  segment,
  score,
  regime,
  href = `/segment/${encodeURIComponent(segment)}`,
}: {
  segment: string;
  score: number | null;
  regime: Regime;
  href?: string;
}) {
  const color = REGIME_COLOR[regime] ?? REGIME_COLOR.NO_DATA;
  return (
    <Link
      href={href}
      className={`flex flex-col gap-0.5 rounded px-3 py-1.5 text-xs font-medium ring-1 transition hover:ring-2 ${color}`}
    >
      <span className="font-mono text-sm">
        {score === null ? "—" : score.toFixed(0)}
      </span>
      <span className="text-[10px] uppercase tracking-wide opacity-80">
        {segment}
      </span>
    </Link>
  );
}
