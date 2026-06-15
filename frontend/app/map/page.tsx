"use client";

export const dynamic = "force-dynamic";

import { Suspense, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getMap, getMapNode, normalizeChainEdge } from "../lib/api";
import type { MapNodeDetail, MapResponse } from "../lib/api";
import { useMapStore } from "../lib/store";
import { ValueChainGraph } from "../components/ValueChainGraph";
import type { ChainNode, ChainEdge } from "../components/chainLayout";
import { MapNodeSidebar } from "../components/MapNodeSidebar";
import { MapSearch } from "../components/MapSearch";
import { displayName } from "../lib/score_help";
import { ErrorState } from "../components/ui/ErrorState";
import { Skeleton } from "../components/ui/Skeleton";
import { PageHeader } from "../components/ui/PageHeader";

function MapPageInner() {
  const searchParams = useSearchParams();
  const nodeSlug = searchParams?.get("node") ?? null;
  const [nodes, setNodes] = useState<ChainNode[] | null>(null);
  const [edges, setEdges] = useState<ChainEdge[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MapNodeDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(false);
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
      setShowSidebar(true);
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

  // Auto-select a node when the page is loaded with ?node=<slug>.
  useEffect(() => {
    if (!nodes || !nodeSlug || selected === nodeSlug) return;
    if (nodes.some((n) => n.id === nodeSlug)) {
      selectNode(nodeSlug);
      setShowSidebar(true);
    }
  }, [nodes, nodeSlug, selected, selectNode]);

  function handleRetry() {
    setError(null);
    setNodes(null);
    setEdges(null);
    getMap()
      .then((d: MapResponse) => {
        setNodes(d.nodes);
        setEdges(d.edges.map(normalizeChainEdge));
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
      });
  }

  if (error) {
    return (
      <section>
        <PageHeader
          title="Value chain"
          action={<Link href="/" className="text-sm text-blue-700 hover:underline">← Back to quadrant</Link>}
        />
        <ErrorState
          title="Failed to load value chain"
          message={error}
          onRetry={handleRetry}
        />
      </section>
    );
  }
  if (!nodes || !edges) {
    return (
      <section>
        <PageHeader
          title="Value chain"
          action={<Link href="/" className="text-sm text-blue-700 hover:underline">← Back to quadrant</Link>}
        />
        <Skeleton className="mb-3 h-12 w-full" />
        <Skeleton className="h-[60vh] min-h-[480px] w-full" />
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        title="Value chain"
        action={
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
                      {displayName(id) === id ? id.replace(/_/g, " ") : displayName(id)}
                    </button>
                  </span>
                ))}
                <button
                  onClick={clearFocus}
                  className="ml-1 text-xs text-gray-400 hover:text-gray-600"
                  aria-label="Clear focus"
                >
                  ✕
                </button>
              </div>
            )}
            <Link href="/" className="text-sm text-blue-700 hover:underline">
              ← Back to quadrant
            </Link>
          </div>
        }
      />

      <p className="mb-2 text-xs text-gray-500">
        {nodes.length} nodes · {edges.length} edges. Click a node to see its detail in the sidebar.
      </p>

      <MapSearch nodes={nodes} onSelect={selectNode} />

      <div
        className="mt-2 flex flex-col gap-4 md:flex-row"
        style={{ height: "calc(100vh - 260px)", minHeight: 480 }}
      >
        <div className="flex-1 overflow-hidden rounded border border-gray-200 bg-white">
          <ValueChainGraph
            nodes={nodes}
            edges={edges}
            selected={selected}
            onSelect={selectNode}
          />
        </div>

        {selected && (
          <button
            type="button"
            onClick={() => setShowSidebar((s) => !s)}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm md:hidden"
            aria-label={showSidebar ? "Hide details" : "Show details"}
            aria-expanded={showSidebar}
          >
            {showSidebar ? "Hide details" : "Show details"}
          </button>
        )}

        <div
          className={`w-full shrink-0 overflow-y-auto md:block md:w-96 ${
            showSidebar ? "block" : "hidden"
          }`}
        >
          <MapNodeSidebar detail={detail} loading={loadingDetail} onSelect={selectNode} />
        </div>
      </div>
    </section>
  );
}

export default function MapPage() {
  return (
    <Suspense
      fallback={
        <section>
          <PageHeader
            title="Value chain"
            action={
              <Link href="/" className="text-sm text-blue-700 hover:underline">
                ← Back to quadrant
              </Link>
            }
          />
          <Skeleton className="mb-3 h-12 w-full" />
          <Skeleton className="h-[60vh] min-h-[480px] w-full" />
        </section>
      }
    >
      <MapPageInner />
    </Suspense>
  );
}
