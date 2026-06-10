"use client";

import Link from "next/link";
import type { MapNodeDetail } from "../lib/api";
import { regimeCard } from "../lib/colors";

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

  return (
    <div className="space-y-3">
      <div className={`rounded border p-4 ${colors.bg} ${colors.text} ring-1 ${colors.ring}`}>
        <h3 className="text-lg font-semibold">{detail.node.label}</h3>
        <p className="mb-2 text-xs opacity-70">{detail.node.sector}</p>
        {detail.node.regime && (
          <span className="inline-block rounded bg-white/60 px-2 py-0.5 text-xs font-medium">
            {detail.node.regime}
          </span>
        )}
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
          <div>
            <span className="opacity-60">Score</span>
            <br />
            <span className="font-mono">{detail.node.score?.toFixed(1) ?? "—"}</span>
          </div>
          <div>
            <span className="opacity-60">Momentum</span>
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
          {upNodes.map((n) => (
            <button
              key={n.id}
              onClick={() => onSelect(n.id)}
              className="mb-1 block w-full rounded bg-gray-50 px-2 py-1 text-left text-xs hover:bg-blue-50"
            >
              <span className="font-medium">{n.id.replace(/_/g, " ")}</span>
              {n.regime && <span className="ml-2 text-gray-400">{n.regime}</span>}
              <span className="ml-2 text-gray-300">depth:{n.depth}</span>
            </button>
          ))}
        </div>
      )}

      {downNodes.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Downstream ({downNodes.length})
          </p>
          {downNodes.map((n) => (
            <button
              key={n.id}
              onClick={() => onSelect(n.id)}
              className="mb-1 block w-full rounded bg-gray-50 px-2 py-1 text-left text-xs hover:bg-blue-50"
            >
              <span className="font-medium">{n.id.replace(/_/g, " ")}</span>
              {n.regime && <span className="ml-2 text-gray-400">{n.regime}</span>}
            </button>
          ))}
        </div>
      )}

      {detail.companies.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Companies ({detail.companies.length})
          </p>
          <div className="flex flex-wrap gap-1">
            {detail.companies.map((c) => (
              <span key={c} className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-mono text-gray-600">
                {c}
              </span>
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
