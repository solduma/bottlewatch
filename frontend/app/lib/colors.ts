// Regime -> Tailwind class set, single source of truth.
//
// The Mermaid color scheme in `src/bottlewatch/jobs/map_mermaid.py`
// (PEAKING=red, PEAKED=orange, RESOLVING=green, EMERGING=blue,
// STABLE=gray, RESOLVING_FROM_LOW=teal) is the canonical intent.
// Tailwind classes here mirror that palette.
//
// `Regime` is the typed union from lib/api; keep this in sync when
// the backend's regime set grows.

import type { Regime } from "./api";

export interface RegimeClasses {
  /** Background + text + ring pair for a small pill. */
  pill: string;
  /** Three separate fields for the MapNodeSidebar, which composes
   *  larger cards with a colored ring. */
  bg: string;
  text: string;
  ring: string;
}

export const REGIME_CLASSES: Record<Regime, RegimeClasses> = {
  PEAKING: {
    pill: "bg-red-100 text-red-800 ring-red-300",
    bg: "bg-red-100",
    text: "text-red-800",
    ring: "ring-red-300",
  },
  PEAKED: {
    pill: "bg-orange-100 text-orange-800 ring-orange-300",
    bg: "bg-orange-100",
    text: "text-orange-800",
    ring: "ring-orange-300",
  },
  RESOLVING: {
    pill: "bg-emerald-100 text-emerald-800 ring-emerald-300",
    bg: "bg-emerald-100",
    text: "text-emerald-800",
    ring: "ring-emerald-300",
  },
  EMERGING: {
    pill: "bg-blue-100 text-blue-800 ring-blue-300",
    bg: "bg-blue-100",
    text: "text-blue-800",
    ring: "ring-blue-300",
  },
  STABLE: {
    pill: "bg-gray-100 text-gray-700 ring-gray-300",
    bg: "bg-gray-100",
    text: "text-gray-700",
    ring: "ring-gray-300",
  },
  RESOLVING_FROM_LOW: {
    pill: "bg-teal-100 text-teal-800 ring-teal-300",
    bg: "bg-teal-100",
    text: "text-teal-800",
    ring: "ring-teal-300",
  },
  NO_DATA: {
    pill: "bg-gray-50 text-gray-500 ring-gray-200",
    bg: "bg-gray-50",
    text: "text-gray-500",
    ring: "ring-gray-200",
  },
};

// `regimePill` and `regimeCard` accept `string | null | undefined`
// because the API returns `regime: string | null` (not the narrow
// `Regime` union). Unknown strings fall back to the NO_DATA
// styling so a new backend regime that hasn't been wired into
// the frontend yet still renders something legible.

export function regimePill(regime: string | null | undefined): string {
  if (!regime) return REGIME_CLASSES.NO_DATA.pill;
  return (REGIME_CLASSES as Record<string, RegimeClasses>)[regime]?.pill ?? REGIME_CLASSES.NO_DATA.pill;
}

export function regimeCard(regime: string | null | undefined): RegimeClasses {
  if (!regime) return REGIME_CLASSES.NO_DATA;
  return (REGIME_CLASSES as Record<string, RegimeClasses>)[regime] ?? REGIME_CLASSES.NO_DATA;
}
