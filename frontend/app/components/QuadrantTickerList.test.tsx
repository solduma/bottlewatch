// Test for the inline ticker list rendered under a quadrant
// cell. Spec from docs/plans/2026-06-11-trend-filter-quadrant-click.md:
// clicking a SegmentBadge in the quadrant expands the list of
// tickers for that segment, sorted by exposure_pct desc, each
// linking to /tickers/[ticker].
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QuadrantTickerList } from "./QuadrantTickerList";

const TICKERS_PAYLOAD = [
  {
    ticker: "HUBB",
    exchange: "NYSE",
    name: "Hubbell Incorporated",
    segment: "transformers_tnd",
    subsegment: "transformers_tnd",
    exposure_pct: 80,
    market_cap_bucket: "large",
    mcap_usd: 25000000000,
    currency_hedge: "USD",
    notes: "",
    regime: "PEAKED",
    regime_confidence: "high",
  },
  {
    ticker: "ETN",
    exchange: "NYSE",
    name: "Eaton Corporation",
    segment: "transformers_tnd",
    subsegment: "transformers_tnd",
    exposure_pct: 75,
    market_cap_bucket: "mega",
    mcap_usd: 180000000000,
    currency_hedge: "USD",
    notes: "",
    regime: "PEAKED",
    regime_confidence: "high",
  },
  {
    ticker: "SU",
    exchange: "NYSE",
    name: "Schneider Electric",
    segment: "transformers_tnd",
    subsegment: "electrical_distribution",
    exposure_pct: 55,
    market_cap_bucket: "large",
    mcap_usd: 200000000000,
    currency_hedge: "manual FX 6M",
    notes: "",
    regime: "PEAKED",
    regime_confidence: "high",
  },
];

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(TICKERS_PAYLOAD), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("QuadrantTickerList", () => {
  it("fetches tickers for the segment on mount", async () => {
    render(<QuadrantTickerList segment="transformers_tnd" />);
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });
    const url = String((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url).toContain("/api/v1/tickers");
    expect(url).toContain("segment=transformers_tnd");
  });

  it("renders rows sorted by exposure_pct desc", async () => {
    render(<QuadrantTickerList segment="transformers_tnd" />);
    // Wait for the list to render.
    await screen.findByText("Hubbell Incorporated");
    // Tickers should appear in the order 80, 75, 55.
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("HUBB");
    expect(items[0]).toHaveTextContent("80%");
    expect(items[1]).toHaveTextContent("ETN");
    expect(items[2]).toHaveTextContent("SU");
  });

  it("links each row to /tickers/[ticker]", async () => {
    render(<QuadrantTickerList segment="transformers_tnd" />);
    const firstLink = await screen.findByRole("link", { name: /HUBB/ });
    expect(firstLink.getAttribute("href")).toBe("/tickers/HUBB");
  });

  it("renders a loading state before the fetch resolves", () => {
    // Override the default mock to never resolve.
    vi.mocked(globalThis.fetch).mockImplementation(
      () => new Promise(() => {}) as ReturnType<typeof fetch>,
    );
    render(<QuadrantTickerList segment="transformers_tnd" />);
    expect(screen.getByText(/Loading tickers/i)).toBeTruthy();
  });

  it("renders an error state when the fetch fails", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response("internal error", { status: 500 }),
    );
    render(<QuadrantTickerList segment="transformers_tnd" />);
    await waitFor(() => {
      expect(screen.getByText(/tickers unavailable/i)).toBeTruthy();
    });
  });

  it("renders an empty message when the segment has no tickers", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<QuadrantTickerList segment="unknown_segment" />);
    await waitFor(() => {
      expect(screen.getByText(/no tickers for this segment/i)).toBeTruthy();
    });
  });

  it("renders the popup as a dialog with an aria-label", async () => {
    const button = document.createElement("button");
    document.body.appendChild(button);
    render(
      <QuadrantTickerList
        segment="transformers_tnd"
        anchorEl={button}
        onClose={() => {}}
      />,
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-label", "Tickers for transformers_tnd");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    document.body.removeChild(button);
  });

  it("links to the segment page from the popup header", async () => {
    const button = document.createElement("button");
    document.body.appendChild(button);
    render(
      <QuadrantTickerList
        segment="transformers_tnd"
        anchorEl={button}
        onClose={() => {}}
      />,
    );
    const link = await screen.findByRole("link", { name: /view segment/i });
    expect(link.getAttribute("href")).toBe("/segment/transformers_tnd");
    document.body.removeChild(button);
  });

  it("calls onClose when Escape is pressed", async () => {
    const button = document.createElement("button");
    document.body.appendChild(button);
    const onClose = vi.fn();
    render(
      <QuadrantTickerList
        segment="transformers_tnd"
        anchorEl={button}
        onClose={onClose}
      />,
    );
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    document.body.removeChild(button);
  });
});
