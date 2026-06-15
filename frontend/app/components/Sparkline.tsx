"use client";

import { useMemo } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Regime, ScoreHistoryPoint } from "../lib/api";
import { REGIME_CLASSES } from "../lib/colors";

// Regime-aligned stroke colors derived from the canonical Tailwind
// palette in lib/colors.ts. Badges render bg/text classes; sparklines
// need a single solid hex color, so we map each canonical color family
// to a 500-level stroke. NO_DATA uses a lighter gray so it doesn't
// compete with real regimes.
const HEX_FOR_COLOR: Record<string, string> = {
  red: "#ef4444", // red-500
  orange: "#f97316", // orange-500
  emerald: "#10b981", // emerald-500
  blue: "#3b82f6", // blue-500
  gray: "#6b7280", // gray-500
  teal: "#14b8a6", // teal-500
};
const NO_DATA_STROKE = "#9ca3af"; // gray-400

const REGIME_STROKE: Record<string, string> = Object.fromEntries(
  (Object.keys(REGIME_CLASSES) as Regime[]).map((regime) => {
    const family = REGIME_CLASSES[regime].text.split("-")[1];
    return [regime, regime === "NO_DATA" ? NO_DATA_STROKE : (HEX_FOR_COLOR[family] ?? NO_DATA_STROKE)];
  }),
);

/**
 * Tiny time-series plot of B (the score, 0-100) over the trailing N
 * months for one (segment, horizon). Used in two places:
 *  - /tickers/[ticker]: one per segment card
 *  - /scoreboard: a new "Trend" column
 *
 * Recharts requires browser (uses ResizeObserver for ResponsiveContainer),
 * so this is a client component. The parent handles the fetch + loading
 * state and passes the points down.
 */
export function Sparkline({
  data,
  width,
  height = 32,
  color,
}: {
  data: ScoreHistoryPoint[];
  width?: number;
  height?: number;
  color?: string;
}) {
  // Recharts' AreaChart needs a `value` key. Map once.
  const series = useMemo(
    () =>
      data
        .filter((p) => p.b !== null)
        .map((p) => ({
          date: p.computed_at,
          value: p.b as number,
        })),
    [data],
  );

  const stroke = color ?? REGIME_STROKE[series.length ? data[data.length - 1].regime : ""] ?? REGIME_STROKE.NO_DATA;

  if (series.length === 0) {
    return (
      <div
        className="flex items-center text-xs text-gray-400"
        style={{ width: width ?? "100%", height }}
        role="img"
        aria-label="No score history yet"
      >
        —
      </div>
    );
  }
  if (series.length === 1) {
    // Recharts needs >= 2 points to draw a line. Render the value
    // as a tick mark instead.
    return (
      <div
        className="flex items-center font-mono text-xs text-gray-600"
        style={{ width: width ?? "100%", height }}
        role="img"
        aria-label={`Score ${series[0].value.toFixed(1)} (only one data point)`}
      >
        {series[0].value.toFixed(1)}
      </div>
    );
  }

  // Y-axis: explicit [0, 100] domain so the line never reaches
  // 2000+ (which would happen if Recharts auto-parsed our date
  // strings as numbers and used them as the y-scale). The axis
  // is hidden — only the area shape is visible — so the
  // explicit domain is just defensive against Recharts quirks.
  // X-axis: hidden (date labels at this size would be unreadable
  // and add no information beyond what the aria-label provides).
  const ariaLabel = `Score trend from ${series[0].value.toFixed(1)} to ${series[series.length - 1].value.toFixed(1)} over ${series.length} months`;

  return (
    <div style={{ width: width ?? "100%", height }} role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <defs>
            <linearGradient id={`spark-fill-${stroke}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.25} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis hide dataKey="date" type="category" />
          <YAxis hide type="number" domain={[0, 100]} />
          <Tooltip
            contentStyle={{ fontSize: 11, padding: "4px 6px" }}
            formatter={(value) => [Number(value).toFixed(1), "B"]}
            labelFormatter={(label) => new Date(String(label)).toLocaleDateString()}
            separator=" "
            cursor={{ stroke: "#d1d5db", strokeWidth: 1 }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.5}
            fill={`url(#spark-fill-${stroke})`}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
