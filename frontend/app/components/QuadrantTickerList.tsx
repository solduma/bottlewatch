"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { listTickers } from "../lib/api";
import type { TickerRow } from "../lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ready"; tickers: TickerRow[] }
  | { kind: "error"; message: string };

/**
 * Ticker list for a single segment.
 *
 * When `anchorEl` is provided the list renders as a floating popup
 * positioned near the anchor element. Clicking outside the popup or
 * pressing the close button calls `onClose`. This keeps the quadrant
 * grid compact when many segments share the same cell.
 *
 * When `anchorEl` is omitted the component falls back to the inline
 * list rendering used by tests and any future non-popup callers.
 *
 * Sorted by `exposure_pct` desc per the methodology §4 conviction
 * basket rule. Each row links to `/tickers/[ticker]`.
 */
export function QuadrantTickerList({
  segment,
  anchorEl,
  onClose,
}: {
  segment: string;
  anchorEl?: HTMLElement | null;
  onClose?: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const popupRef = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<React.CSSProperties>({});

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    listTickers(segment)
      .then((rows) => {
        if (cancelled) return;
        const sorted = [...rows].sort((a, b) => {
          const ae = a.exposure_pct ?? 0;
          const be = b.exposure_pct ?? 0;
          if (be !== ae) return be - ae;
          return a.ticker.localeCompare(b.ticker);
        });
        setState({ kind: "ready", tickers: sorted });
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
  }, [segment]);

  // Position the popup relative to the anchor element.
  useEffect(() => {
    if (!anchorEl) return;
    const rect = anchorEl.getBoundingClientRect();
    const popupWidth = 320;
    const margin = 8;

    let left = rect.left;
    if (left + popupWidth > window.innerWidth - margin) {
      left = Math.max(margin, window.innerWidth - popupWidth - margin);
    }

    // Prefer below the anchor; flip above if there is not enough room.
    const popupHeight = 240;
    let top = rect.bottom + margin;
    if (top + popupHeight > window.innerHeight - margin && rect.top - popupHeight - margin > margin) {
      top = rect.top - popupHeight - margin;
    }

    setStyle({
      position: "fixed",
      top,
      left,
      zIndex: 50,
    });
  }, [anchorEl]);

  // Close on click outside (or on the anchor itself, which toggles).
  useEffect(() => {
    if (!anchorEl || !onClose) return;
    function handleMouseDown(e: MouseEvent) {
      const target = e.target as Node;
      const popup = popupRef.current;
      if (!popup) return;
      if (popup.contains(target)) return;
      if (anchorEl?.contains(target)) return;
      onClose?.();
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [anchorEl, onClose]);

  const content =
    state.kind === "loading" ? (
      <div className="text-[10px] italic text-gray-400">Loading tickers…</div>
    ) : state.kind === "error" ? (
      <div
        className="text-[10px] text-red-500"
        title={state.message}
        role="img"
        aria-label="Ticker list unavailable"
      >
        (tickers unavailable)
      </div>
    ) : state.tickers.length === 0 ? (
      <div className="text-[10px] italic text-gray-400">
        (no tickers for this segment)
      </div>
    ) : (
      <ul
        className="space-y-0.5"
        aria-label={`Tickers for ${segment}`}
      >
        {state.tickers.map((t) => (
          <li key={t.ticker}>
            <Link
              href={`/tickers/${encodeURIComponent(t.ticker)}`}
              className="flex items-center gap-2 rounded px-1.5 py-0.5 text-[11px] hover:bg-gray-100"
            >
              <span className="font-mono font-medium text-blue-700">
                {t.ticker}
              </span>
              <span className="flex-1 truncate text-gray-700">{t.name}</span>
              <span className="font-mono text-gray-500">
                {t.exposure_pct}%
              </span>
            </Link>
          </li>
        ))}
      </ul>
    );

  if (!anchorEl) {
    return (
      <div className="mt-2 space-y-0.5 border-t border-dashed border-gray-200 pt-1.5">
        {content}
      </div>
    );
  }

  return (
    <div
      ref={popupRef}
      style={style}
      className="w-80 max-h-72 overflow-y-auto rounded border border-gray-200 bg-white p-3 shadow-lg"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
          Tickers
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close ticker list"
          >
            ×
          </button>
        )}
      </div>
      {content}
    </div>
  );
}
