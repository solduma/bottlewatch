"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { buildNeighborIndex, layoutChain, type ChainEdge, type ChainNode } from "./chainLayout";
import { normalizeChainEdge, type ValueChainEdge } from "../lib/api";
import { useMapStore, type SectorFilter } from "../lib/store";

// Regime-aligned node fill colors. Mirrors the badge palette used
// elsewhere so the graph reads the same as the scoreboard.
const REGIME_FILL: Record<string, string> = {
  PEAKING: "#fee2e2",
  PEAKED: "#ffedd5",
  RESOLVING: "#d1fae5",
  EMERGING: "#dbeafe",
  STABLE: "#f3f4f6",
  RESOLVING_FROM_LOW: "#ccfbf1",
  NO_DATA: "#f9fafb",
};

const REGIME_BORDER: Record<string, string> = {
  PEAKING: "#ef4444",
  PEAKED: "#f97316",
  RESOLVING: "#10b981",
  EMERGING: "#3b82f6",
  STABLE: "#6b7280",
  RESOLVING_FROM_LOW: "#14b8a6",
  NO_DATA: "#d1d5db",
};

interface ValueChainNodeData extends ChainNode {
  isSelected: boolean;
  isInPath: boolean;
  /** Regime to actually use for color (may differ from `regime`
   * when the cohort heatmap is active). */
  effectiveRegime: string;
  isMatch: boolean;
  onClick: (id: string) => void;
  [key: string]: unknown;
}

function ValueChainNode({ data }: NodeProps) {
  const d = data as ValueChainNodeData;
  const regime = d.effectiveRegime;
  const fill = REGIME_FILL[regime] ?? REGIME_FILL.NO_DATA;
  const border = d.isSelected
    ? "#1d4ed8" // blue-700 when selected
    : d.isMatch
      ? "#3b82f6" // blue-500 when search match
      : d.isInPath
        ? "#60a5fa" // blue-400 when in the upstream/downstream path
        : (REGIME_BORDER[regime] ?? REGIME_BORDER.NO_DATA);
  const borderWidth = d.isSelected ? 3 : d.isMatch || d.isInPath ? 2 : 1;
  const opacity = d.isMatch || !isFiltered(d) ? 1 : 0.25;

  return (
    <div
      onClick={() => d.onClick(d.id)}
      role="button"
      tabIndex={0}
      aria-label={`${d.label} (${regime})`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          d.onClick(d.id);
        }
      }}
      className="cursor-pointer rounded text-left"
      style={{
        background: fill,
        border: `${borderWidth}px solid ${border}`,
        color: "#1f2937",
        padding: "8px 10px",
        width: 200,
        fontSize: 13,
        lineHeight: 1.3,
        fontWeight: 500,
        opacity,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "#9ca3af" }} />
      <div>{d.label}</div>
      <div style={{ fontSize: 10, color: "#6b7280", marginTop: 2 }}>{d.sector}</div>
      <Handle type="source" position={Position.Right} style={{ background: "#9ca3af" }} />
    </div>
  );
}

// Helper: a node is "filtered out" when a search query is
// active and this node is not a match. Used to dim non-matches
// without removing them from the layout (so the graph
// doesn't reflow on every keystroke).
function isFiltered(d: ValueChainNodeData): boolean {
  // The node receives `isMatch: false` for non-matches. If `isMatch`
  // is undefined (legacy prop), assume not filtered.
  return d.isMatch === false;
}

const nodeTypes = { valueChain: ValueChainNode };

export function ValueChainGraph({
  nodes,
  edges,
  selected,
  onSelect,
}: {
  nodes: ChainNode[];
  edges: ChainEdge[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  // Tier 2/3 state — read from the store so MapSearch can
  // drive it. Re-keyed memos below recompute when any
  // filter changes.
  const searchQuery = useMapStore((s) => s.searchQuery);
  const sectorFilter = useMapStore((s) => s.sectorFilter);
  const cohortSegment = useMapStore((s) => s.cohortSegment);

  // Debounce the search query so fast typing doesn't recompute the
  // match set (and therefore node dimming) on every keystroke.
  const [debouncedQuery, setDebouncedQuery] = useState(searchQuery);
  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(searchQuery), 300);
    return () => clearTimeout(id);
  }, [searchQuery]);

  // Sector → friendly filter string. The map's `sector`
  // values are like "MaterialsSector", "HardwareSector", etc.
  // We map the chip's short label to the matching sector
  // names. ("all" passes everything.)
  const SECTOR_TO_API: Record<SectorFilter, string[]> = {
    all: [],
    Materials: ["MaterialsSector"],
    Hardware: ["HardwareSector"],
    Infrastructure: ["InfrastructureSector"],
    Downstream: ["DownstreamSector"],
  };
  const allowedSectors = SECTOR_TO_API[sectorFilter] ?? [];

  // Tier 3 cohort: when a cohort is selected, the
  // "effective regime" of every node is the cohort's regime
  // (not the node's own). Edges still draw between visible
  // nodes; the visual just shifts color.
  const cohortScore = useMemo(() => {
    if (!cohortSegment) return null;
    const n = nodes.find((x) => x.id === cohortSegment);
    return n ? n.regime ?? null : null;
  }, [cohortSegment, nodes]);

  // Zoom to the selected node whenever it changes (search
  // click or graph click). We capture the ReactFlow instance
  // via `onInit` and call `fitView` with a nodes array so
  // the camera centers on that single node.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rfInstanceRef = useRef<any>(null);
  useEffect(() => {
    if (!selected) return;
    const id = setTimeout(() => {
      rfInstanceRef.current?.fitView({
        nodes: [{ id: selected }],
        padding: 0.3,
        duration: 300,
      });
    }, 50);
    return () => clearTimeout(id);
  }, [selected]);

  // Translate the API's `from`/`to` form to React Flow's `source`/`target`
  // at the boundary. The API may return either; we accept both for
  // forward-compat. `normalizeChainEdge` is the single point of
  // vocabulary translation.
  const reactFlowEdges: ChainEdge[] = useMemo(() => {
    const seen = new Set<string>();
    return (edges as ValueChainEdge[])
      .map(normalizeChainEdge)
      .filter((e) => {
        if (!e.source || !e.target) return false;
        const key = `${e.source}-${e.target}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }, [edges]);

  // Sector filter — drop nodes outside the selected sector(s).
  const sectorFilteredNodes = useMemo(() => {
    if (allowedSectors.length === 0) return nodes;
    return nodes.filter((n) => {
      return allowedSectors.includes(n.sector ?? "");
    });
  }, [nodes, allowedSectors]);

  // Search filter — compute the match set from the debounced query.
  const searchMatchSet = useMemo(() => {
    if (!debouncedQuery.trim()) return null;
    const q = debouncedQuery.toLowerCase();
    const matched = new Set<string>();
    for (const n of nodes) {
      if (
        n.id.toLowerCase().includes(q) ||
        (n.label ?? "").toLowerCase().includes(q) ||
        n.sector.toLowerCase().includes(q)
      ) {
        matched.add(n.id);
      } else if (n.companies && n.companies.length > 0) {
        if (n.companies.some((c) => c.toLowerCase().includes(q))) {
          matched.add(n.id);
        }
      }
    }
    return matched;
  }, [nodes, debouncedQuery]);

  // Search no longer removes nodes/edges from the layout — it only dims
  // non-matching nodes. The sector filter is the only filter that
  // changes the graph topology (and therefore triggers a re-layout).
  const sectorVisibleSet = useMemo(() => {
    return new Set<string>(sectorFilteredNodes.map((n) => n.id));
  }, [sectorFilteredNodes]);

  const sectorFilteredEdges = useMemo(() => {
    return reactFlowEdges.filter(
      (e) => sectorVisibleSet.has(e.source) && sectorVisibleSet.has(e.target),
    );
  }, [reactFlowEdges, sectorVisibleSet]);

  const positioned = useMemo(
    () => layoutChain(sectorFilteredNodes, sectorFilteredEdges),
    [sectorFilteredNodes, sectorFilteredEdges],
  );

  const { upstream, downstream } = useMemo(
    () => buildNeighborIndex(reactFlowEdges),
    [reactFlowEdges],
  );

  // Highlight set: the selected node + its 1-hop upstream + 1-hop downstream.
  const inPath = useMemo(() => {
    if (!selected) return new Set<string>();
    const set = new Set<string>([selected]);
    for (const u of upstream[selected] ?? []) set.add(u);
    for (const d of downstream[selected] ?? []) set.add(d);
    return set;
  }, [selected, upstream, downstream]);

  const handleSelect = useCallback(
    (id: string) => {
      onSelect(id);
    },
    [onSelect],
  );

  const flowNodes: Node<ValueChainNodeData>[] = useMemo(
    () =>
      positioned.map((n) => {
        const isMatch = searchMatchSet === null ? true : searchMatchSet.has(n.id);
        const effectiveRegime =
          cohortScore !== null ? cohortScore : (n.regime ?? "NO_DATA");
        return {
          id: n.id,
          type: "valueChain",
          position: n.position,
          data: {
            ...n,
            isSelected: n.id === selected,
            isInPath: inPath.has(n.id),
            isMatch,
            effectiveRegime,
            onClick: handleSelect,
          },
        };
      }),
    [positioned, selected, inPath, handleSelect, searchMatchSet, cohortScore],
  );

  // Explicit camera reset only — no automatic fit on filter changes.
  const handleFitToResults = useCallback(() => {
    rfInstanceRef.current?.fitView({
      padding: 0.15,
      duration: 300,
    });
  }, []);

  const flowEdges: Edge[] = useMemo(
    () =>
      sectorFilteredEdges.map((e) => {
        const isOnPath = selected !== null && inPath.has(e.source) && inPath.has(e.target);
        const sourceMatch = searchMatchSet === null || searchMatchSet.has(e.source);
        const targetMatch = searchMatchSet === null || searchMatchSet.has(e.target);
        const isDimmed = !sourceMatch || !targetMatch;
        // Use any explicit relationship label the edge carries; skip gracefully otherwise.
        const label = e.role_kind || e.label || undefined;
        return {
          id: `${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          type: "smoothstep",
          animated: false,
          label,
          labelStyle: { fontSize: 10, fill: "#6b7280" },
          labelBgStyle: { fill: "#ffffff", fillOpacity: 0.8 },
          labelBgPadding: [4, 2],
          labelBgBorderRadius: 4,
          style: {
            stroke: isOnPath ? "#1d4ed8" : "#9ca3af",
            strokeWidth: isOnPath ? 2 : 1,
            opacity: isDimmed ? 0.25 : 1,
          },
        };
      }),
    [sectorFilteredEdges, selected, inPath, searchMatchSet],
  );

  // Tier 4: SVG export. We capture the React Flow's SVG
  // element, serialize to a data URL, and trigger download.
  // The exported file has a white background so it's
  // printable / slide-deckable.
  const [exporting, setExporting] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const handleExportSvg = useCallback(() => {
    if (!containerRef.current) return;
    setExporting(true);
    try {
      const svg = containerRef.current.querySelector("svg.recharts-surface, .react-flow__viewport svg, svg");
      // Fallback: query any SVG in the container.
      const target = (svg ?? containerRef.current.querySelector("svg")) as SVGElement | null;
      if (!target) return;
      const clone = target.cloneNode(true) as SVGElement;
      // Inline minimal CSS to color borders if missing.
      const inlineStyle = document.createElement("style");
      inlineStyle.textContent = "svg { background: #ffffff; }";
      clone.insertBefore(inlineStyle, clone.firstChild);
      // Ensure width / height attrs are set (ReFlow uses
      // viewBox + width/height from container).
      const rect = target.getBoundingClientRect();
      clone.setAttribute("width", String(rect.width));
      clone.setAttribute("height", String(rect.height));
      const xml = new XMLSerializer().serializeToString(clone);
      const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const today = new Date().toISOString().slice(0, 10);
      a.download = `bottlewatch-chain-${today}.svg`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }, []);

  return (
    <div ref={containerRef} className="relative h-full">
      {/* Camera + export controls — top-right of the graph panel. */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-2">
        <button
          type="button"
          onClick={handleFitToResults}
          className="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
        >
          Fit to results
        </button>
        <button
          type="button"
          onClick={handleExportSvg}
          disabled={exporting}
          className="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
          aria-label="Export value chain as image"
        >
          {exporting ? "Exporting…" : "Export SVG"}
        </button>
      </div>

      {/* Cohort legend — bottom-left, only when a cohort is
          active. Explains what the color recoloring means. */}
      {cohortSegment && (
        <div className="absolute bottom-3 left-3 z-10 max-w-xs rounded border border-gray-300 bg-white/95 px-2.5 py-1.5 text-xs text-gray-700 shadow-sm">
          <strong>Color mode:</strong> every node is colored by the regime of{" "}
          <span className="font-mono">{cohortSegment}</span>. Nodes without
          data for that segment render grey.
        </div>
      )}

      <div style={{ width: "100%", height: "100%" }}>
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onInit={(inst) => {
            rfInstanceRef.current = inst;
          }}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} color="#e5e7eb" />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={(n) => {
              const data = n.data as ValueChainNodeData | undefined;
              if (!data) return "#e5e7eb";
              return REGIME_FILL[data.effectiveRegime ?? "NO_DATA"] ?? REGIME_FILL.NO_DATA;
            }}
            nodeStrokeWidth={2}
            pannable
            zoomable
          />
        </ReactFlow>
      </div>
    </div>
  );
}
