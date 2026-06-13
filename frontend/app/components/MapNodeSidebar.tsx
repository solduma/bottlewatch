"use client";

import Link from "next/link";
import type { MapNodeDetail } from "../lib/api";
import { regimeCard } from "../lib/colors";
import { displayName } from "../lib/score_help";

export function MapNodeSidebar({
  detail,
  loading,
  onSelect,
}: {
  detail: MapNodeDetail | null;
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  if (!detail && !loading) {
    return (
      <div className="rounded border border-dashed border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-400">
        Click a node to see details
      </div>
    );
  }
  if (loading) {
    return (
      <div className="rounded border border-gray-200 bg-white p-4 text-sm text-gray-500">
        Loading…
      </div>
    );
  }
  if (!detail) return null;

  const colors = regimeCard(detail.node.regime ?? "NO_DATA");
  const upNodes = detail.upstream ?? [];
  const downNodes = detail.downstream ?? [];
  const nodeName = displayName(detail.node.id);

  return (
    <div className="space-y-3">
      <div className={`rounded border p-4 ${colors.bg} ${colors.text} ring-1 ${colors.ring}`}>
        <h3
          className="text-lg font-semibold"
          title={nodeName !== detail.node.id ? `${detail.node.id} (${nodeName})` : detail.node.id}
        >
          {detail.node.label}
        </h3>
        {nodeName !== detail.node.id && (
          <p className="mb-1 font-mono text-[10px] opacity-60">{detail.node.id}</p>
        )}
        <p className="mb-2 text-xs opacity-70">{(detail.node.sector ?? "").replace(/Sector$/, "")}</p>
        {detail.node.regime && (
          <span className="inline-block rounded bg-white/60 px-2 py-0.5 text-xs font-medium">
            {detail.node.regime}
          </span>
        )}
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
          <div>
            <span className="opacity-60">Score (B)</span>
            <br />
            <span className="font-mono">{detail.node.score?.toFixed(1) ?? "—"}</span>
          </div>
          <div>
            <span className="opacity-60">Momentum (B')</span>
            <br />
            <span className="font-mono">{detail.node.momentum?.toFixed(1) ?? "—"}</span>
          </div>
        </div>
      </div>

      {detail.eta && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="text-xs text-gray-500">Resolution ETA</p>
          <p className="font-mono text-sm font-medium">{detail.eta.eta}</p>
          <p className="text-xs text-gray-400">({detail.eta.confidence} confidence)</p>
        </div>
      )}

      {upNodes.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Upstream ({upNodes.length})
          </p>
          {upNodes.map((n) => {
            const upName = displayName(n.id);
            return (
              <button
                key={n.id}
                onClick={() => onSelect(n.id)}
                title={upName !== n.id ? `${n.id} (${upName})` : n.id}
                className="mb-1 block w-full rounded bg-gray-50 px-2 py-1 text-left text-xs hover:bg-blue-50"
              >
                <div className="flex flex-col">
                  <span className="font-medium">{upName}</span>
                  {upName !== n.id && (
                    <span className="font-mono text-[10px] text-gray-500">{n.id}</span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[10px]">
                  {n.regime && <span className="text-gray-500">{n.regime}</span>}
                  <span className="text-gray-300">depth:{n.depth}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {downNodes.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Downstream ({downNodes.length})
          </p>
          {downNodes.map((n) => {
            const dnName = displayName(n.id);
            return (
              <button
                key={n.id}
                onClick={() => onSelect(n.id)}
                title={dnName !== n.id ? `${n.id} (${dnName})` : n.id}
                className="mb-1 block w-full rounded bg-gray-50 px-2 py-1 text-left text-xs hover:bg-blue-50"
              >
                <div className="flex flex-col">
                  <span className="font-medium">{dnName}</span>
                  {dnName !== n.id && (
                    <span className="font-mono text-[10px] text-gray-500">{n.id}</span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[10px]">
                  {n.regime && <span className="text-gray-500">{n.regime}</span>}
                  <span className="text-gray-300">depth:{n.depth}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {detail.companies.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Companies ({detail.companies.length})
          </p>
          <div className="flex flex-wrap gap-1">
            {detail.companies.map((c) => (
              <Link
                key={c}
                href={`/tickers/${encodeURIComponent(c)}`}
                className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-blue-700 hover:bg-blue-100"
              >
                {c}
              </Link>
            ))}
          </div>
        </div>
      )}

      {detail.thesis_count > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="text-xs text-gray-500">Thesis notes</p>
          <p className="text-sm font-medium">{detail.thesis_count} notes</p>
          <Link href="/thesis" className="text-xs text-blue-700 hover:underline">
            View →
          </Link>
        </div>
      )}
    </div>
  );
}
