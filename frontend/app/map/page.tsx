"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { getMap, getMapNode, normalizeChainEdge } from "../lib/api";
import type { MapNodeDetail, MapResponse } from "../lib/api";
import { useMapStore } from "../lib/store";
import { ValueChainGraph } from "../components/ValueChainGraph";
import type { ChainNode, ChainEdge } from "../components/chainLayout";
import { MapNodeSidebar } from "../components/MapNodeSidebar";
import { MapSearch } from "../components/MapSearch";

export default function MapPage() {
  const [nodes, setNodes] = useState<ChainNode[] | null>(null);
  const [edges, setEdges] = useState<ChainEdge[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MapNodeDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const focusPath = useMapStore((s) => s.focusPath);
  const setFocus = useMapStore((s) => s.setFocus);
  const clearFocus = useMapStore((s) => s.clearFocus);

  // Load the value chain JSON once.
  useEffect(() => {
    getMap()
      .then((d: MapResponse) => {
        setNodes(d.nodes);
        setEdges(d.edges.map(normalizeChainEdge));
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
      });
  }, []);

  const selectNode = useCallback(
    async (id: string) => {
      setSelected(id);
      setLoadingDetail(true);
      setDetail(null);
      try {
        const d = await getMapNode(id);
        setDetail(d);
        setFocus(id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoadingDetail(false);
      }
    },
    [setFocus],
  );

  if (error) {
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>
    );
  }
  if (!nodes || !edges) {
    return <div className="text-sm text-gray-500">Loading value chain…</div>;
  }

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Value chain</h1>
        <div className="flex items-center gap-3">
          {focusPath.length > 0 && (
            <div className="flex items-center gap-1">
              <span className="text-xs text-gray-500">Focus:</span>
              {focusPath.map((id, i) => (
                <span key={id} className="flex items-center gap-0.5">
                  {i > 0 && <span className="text-gray-400">›</span>}
                  <button
                    onClick={() => selectNode(id)}
                    className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800 hover:bg-blue-200"
                  >
                    {id.replace(/_/g, " ")}
                  </button>
                </span>
              ))}
              <button
                onClick={clearFocus}
                className="ml-1 text-xs text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
          )}
          <Link href="/" className="text-sm text-blue-700 hover:underline">
            ← Back to quadrant
          </Link>
        </div>
      </div>

      <p className="mb-2 text-xs text-gray-500">
        {nodes.length} nodes · {edges.length} edges. Click a node to see its detail in the sidebar.
      </p>

      <MapSearch nodes={nodes} onSelect={selectNode} />

      <div className="mt-2 flex gap-4" style={{ height: "calc(100vh - 260px)", minHeight: 480 }}>
        <div className="flex-1 overflow-hidden rounded border border-gray-200 bg-white">
          <ValueChainGraph
            nodes={nodes}
            edges={edges}
            selected={selected}
            onSelect={selectNode}
          />
        </div>
        <div className="w-80 shrink-0 overflow-y-auto">
          <MapNodeSidebar detail={detail} loading={loadingDetail} onSelect={selectNode} />
        </div>
      </div>
    </section>
  );
}
