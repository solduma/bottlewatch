"use client";

import { useEffect, useState } from "react";
import { getScoreHistory } from "../lib/api";
import type { Horizon, ScoreHistoryPoint } from "../lib/api";
import { Sparkline } from "./Sparkline";

type State =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "error"; message: string }
  | { kind: "ready"; points: ScoreHistoryPoint[] };

/**
 * Client-side wrapper that fetches a segment's history and renders a
 * Sparkline. Used in /tickers/[ticker] and /scoreboard.
 *
 * The fetch is keyed on (segment, horizon) so two Sparklines for the
 * same segment share one in-flight request. We don't share across
 * component instances yet (no global cache); the backend is fast and
 * the scoreboard has at most ~10 segments.
 */
export function SparklineForSegment({
  segment,
  horizon,
  months = 6,
  height = 32,
}: {
  segment: string;
  horizon: Horizon;
  months?: number;
  height?: number;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    getScoreHistory(segment, horizon, months)
      .then((resp) => {
        if (cancelled) return;
        if (resp.points.length === 0) {
          setState({ kind: "empty" });
        } else {
          setState({ kind: "ready", points: resp.points });
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [segment, horizon, months]);

  if (state.kind === "loading") {
    return (
      <div
        className="h-2 w-24 animate-pulse rounded bg-gray-200"
        style={{ height }}
        aria-label="Loading score history"
      />
    );
  }
  if (state.kind === "empty") {
    return (
      <div
        className="flex items-center text-xs text-gray-400"
        style={{ height }}
        aria-label="No history yet"
      >
        —
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div
        className="flex items-center text-xs text-gray-400"
        style={{ height }}
        role="img"
        aria-label="Score history unavailable"
        title={state.message}
      >
        —
      </div>
    );
  }
  return <Sparkline data={state.points} height={height} />;
}
