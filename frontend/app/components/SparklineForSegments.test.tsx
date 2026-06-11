// Test for the batched sparkline hook. Spec from docs/plans/
// 2026-06-06-fixes-and-improvements.md §5.3: a hook that takes an
// array of segments, issues ONE batched `getScoreHistoryBatched`
// call, and returns a Map<segment, points> for the caller to look
// up. The previous N+1 design made one HTTP call per row (10
// calls for the scoreboard); this hook collapses it to 1.
//
// We mock `globalThis.fetch` rather than `getScoreHistoryBatched`
// because that's the actual HTTP seam — if a future refactor
// rewires the batched fetcher through a different code path, this
// test still catches a regression in the call count.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { useBatchedScoreHistory } from "./SparklineForSegments";

const SERIES_PAYLOAD = {
  horizon: "near",
  months: 6,
  series: [
    {
      segment: "hbm_memory",
      points: [
        { computed_at: "2025-12-01T00:00:00", b: 70, momentum: 5, regime: "PEAKING" },
        { computed_at: "2026-01-01T00:00:00", b: 75, momentum: 5, regime: "PEAKING" },
        { computed_at: "2026-02-01T00:00:00", b: 80, momentum: 5, regime: "PEAKING" },
      ],
    },
    {
      segment: "transformers_tnd",
      points: [
        { computed_at: "2025-12-01T00:00:00", b: 60, momentum: 0, regime: "STABLE" },
        { computed_at: "2026-01-01T00:00:00", b: 65, momentum: 5, regime: "STABLE" },
      ],
    },
    { segment: "unknown_segment", points: [] },
  ],
};

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(SERIES_PAYLOAD), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useBatchedScoreHistory", () => {
  it("issues exactly one HTTP call for N segments", async () => {
    renderHook(() =>
      useBatchedScoreHistory(
        ["hbm_memory", "transformers_tnd", "unknown_segment"],
        "near",
        6,
      ),
    );

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });

    const called = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const url = String(called[0]);
    expect(url).toContain("/api/v1/scores/history");
    expect(url).toContain("segments=");
    // Comma-separated slugs, in order.
    expect(url).toContain("hbm_memory%2Ctransformers_tnd%2Cunknown_segment");
    expect(url).toContain("horizon=near");
  });

  it("returns a Map keyed by segment slug with the per-segment points", async () => {
    const { result } = renderHook(() =>
      useBatchedScoreHistory(
        ["hbm_memory", "transformers_tnd", "unknown_segment"],
        "near",
        6,
      ),
    );

    await waitFor(() => {
      expect(result.current.kind).toBe("ready");
    });
    if (result.current.kind !== "ready") throw new Error("not ready");

    const bySegment = result.current.bySegment;
    expect(bySegment.get("hbm_memory")).toHaveLength(3);
    expect(bySegment.get("transformers_tnd")).toHaveLength(2);
    expect(bySegment.get("unknown_segment")).toEqual([]);
  });

  it("does not refetch when the same args are passed on a re-render", async () => {
    const { rerender } = renderHook(
      ({ segs }: { segs: string[] }) => useBatchedScoreHistory(segs, "near", 6),
      { initialProps: { segs: ["hbm_memory", "transformers_tnd"] } },
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));

    // Re-render with a new array literal (same contents) — the
    // key is built from `.join(",")`, so a re-render with the
    // same slugs must NOT issue a second fetch.
    rerender({ segs: ["hbm_memory", "transformers_tnd"] });
    // Let any pending microtasks flush.
    await new Promise((r) => setTimeout(r, 50));
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("handles an empty segment list (no fetch, returns empty ready state)", async () => {
    const { result } = renderHook(() => useBatchedScoreHistory([], "near", 6));
    await waitFor(() => expect(result.current.kind).toBe("ready"));
    expect(globalThis.fetch).not.toHaveBeenCalled();
    if (result.current.kind !== "ready") throw new Error("not ready");
    expect(result.current.bySegment.size).toBe(0);
  });

  it("refetches when the months argument changes", async () => {
    const { rerender } = renderHook(
      ({ months }: { months: number }) =>
        useBatchedScoreHistory(["hbm_memory"], "near", months),
      { initialProps: { months: 6 } },
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    const firstUrl = String((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(firstUrl).toContain("months=6");

    // User switches to 1-year view → re-keyed, refetched.
    rerender({ months: 12 });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    const secondUrl = String((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1][0]);
    expect(secondUrl).toContain("months=12");
  });
});
