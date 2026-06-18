// Regression test for the quadrant ticker popup.
//
// The cell grid is rendered twice (desktop `md:grid` + mobile
// `md:hidden` layouts). The popup used to be rendered inside each
// Cell, so expanding a segment mounted TWO QuadrantTickerList
// instances — each fixed-positioned at the same spot with its own
// document mousedown outside-click listener. Clicking a link in the
// visible popup looked "outside" to the hidden twin, which called
// onClose and tore the popup down before the link could navigate,
// making every segment/ticker link in the popup non-responsive.
//
// The fix lifts the popup to a single render in RegimeQuadrant. This
// test guards that exactly one popup (dialog) mounts on expand.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RegimeQuadrant } from "./RegimeQuadrant";
import type { SegmentScore } from "../lib/api";

const ROWS = [
  {
    segment: "transformers_tnd",
    name: "Transformers",
    score: 72,
    regime: "PEAKING",
    momentum: 1,
    eta_days: null,
  } as unknown as SegmentScore,
];

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify([
        {
          ticker: "HUBB",
          exchange: "NYSE",
          name: "Hubbell",
          segment: "transformers_tnd",
          subsegment: "x",
          exposure_pct: 80,
          market_cap_bucket: "large",
          mcap_usd: 1,
          currency_hedge: "USD",
          notes: "",
          regime: "PEAKED",
          regime_confidence: "high",
        },
      ]),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RegimeQuadrant popup", () => {
  it("mounts exactly one popup when a segment is expanded", async () => {
    render(<RegimeQuadrant rows={ROWS} />);
    // The badge is rendered twice (desktop + mobile layouts); clicking
    // either must yield a single popup, not one per layout.
    const badges = screen.getAllByRole("button", { name: /transformers/i });
    expect(badges.length).toBeGreaterThan(1); // sanity: grid is duplicated
    fireEvent.click(badges[0]);
    await waitFor(() => {
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
    });
  });
});
