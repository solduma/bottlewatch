"use client";

import { useEffect, useState } from "react";
import type { Horizon, ScoreHistoryPoint } from "../lib/api";
import { getScoreHistoryBatched } from "../lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ready"; bySegment: Map<string, ScoreHistoryPoint[]> }
  | { kind: "error"; message: string };

/**
 * Batched fetcher for the scoreboard. Issues ONE call to
 * `getScoreHistoryBatched` for N segments; returns a Map keyed by
 * segment slug. The scoreboard then renders one dumb `<Sparkline>`
 * per row, looking up its points in the map. With N=10 segments
 * this is 1 HTTP call instead of 10 (the previous per-row design
 * was an N+1 problem).
 *
 * Spec: docs/plans/2026-06-06-fixes-and-improvements.md §5.3. The
 * test (SparklineForSegments.test.tsx) asserts the call count and
 * the comma-separated `segments=` URL shape.
 *
 * Re-keying: the effect depends on (segments.join, horizon, months).
 * A different segment list (e.g. a horizon toggle that swaps the
 * visible set) triggers a refetch; a re-render with the same key
 * does not.
 */
export function useBatchedScoreHistory(
  segments: string[],
  horizon: Horizon,
  months = 6,
): State {
  const [state, setState] = useState<State>({ kind: "loading" });
  // The `key` is also passed as a dep so re-renders with the same
  // segments but a different object identity don't refetch.
  const key = `${segments.join(",")}|${horizon}|${months}`;

  useEffect(() => {
    if (segments.length === 0) {
      setState({ kind: "ready", bySegment: new Map() });
      return;
    }
    let cancelled = false;
    setState({ kind: "loading" });
    getScoreHistoryBatched(segments, horizon, months)
      .then((resp) => {
        if (cancelled) return;
        const bySegment = new Map<string, ScoreHistoryPoint[]>();
        for (const entry of resp.series) {
          bySegment.set(entry.segment, entry.points);
        }
        setState({ kind: "ready", bySegment });
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
    // The `key` captures the actual dependency; including the raw
    // args keeps exhaustive-deps happy without redundant fetches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
