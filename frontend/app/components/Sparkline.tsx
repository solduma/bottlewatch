"use client";

import { useMemo } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import type { ScoreHistoryPoint } from "../lib/api";

// Regime-aligned line color. Matches the badge palette but as a single
// solid stroke for the sparkline (badges use background + text colors;
// we only need a stroke).
const REGIME_STROKE: Record<string, string> = {
  PEAKING: "#f59e0b", // amber-500
  PEAKED: "#ef4444", // red-500
  RESOLVING: "#10b981", // emerald-500
  EMERGING: "#3b82f6", // blue-500
  STABLE: "#6b7280", // gray-500
  RESOLVING_FROM_LOW: "#34d399", // emerald-400
  NO_DATA: "#9ca3af", // gray-400
};

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

  // Y-axis domain with small padding so the line doesn't touch the
  // chart edges. Recharts' "auto" handles min/max.
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
          <YAxis hide domain={["auto", "auto"]} />
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
