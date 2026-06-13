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
        width: 180,
        fontSize: 12,
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
  // The actual filter state lives in the page; the node
  // receives `isMatch: false` for non-matches. If `isMatch`
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

  // Search filter — compute the match set.
  const searchMatchSet = useMemo(() => {
    if (!searchQuery.trim()) return null;
    const q = searchQuery.toLowerCase();
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
  }, [nodes, searchQuery]);

  // Set of node ids that survive both filters.
  const visibleSet = useMemo(() => {
    const set = new Set<string>(sectorFilteredNodes.map((n) => n.id));
    if (searchMatchSet !== null) {
      // Intersect with matches when a query is active.
      const out = new Set<string>();
      for (const id of set) {
        if (searchMatchSet.has(id)) out.add(id);
      }
      return out;
    }
    return set;
  }, [sectorFilteredNodes, searchMatchSet]);

  // Filter nodes and edges to only those that are visible (survive both sector and search filters)
  const filteredNodes = useMemo(() => {
    return sectorFilteredNodes.filter((n) => {
      if (searchMatchSet === null) return true;
      return searchMatchSet.has(n.id);
    });
  }, [sectorFilteredNodes, searchMatchSet]);

  const filteredEdges = useMemo(() => {
    return reactFlowEdges.filter((e) => visibleSet.has(e.source) && visibleSet.has(e.target));
  }, [reactFlowEdges, visibleSet]);

  // Re-layout the graph with only the filtered nodes and edges to avoid empty spaces
  const positioned = useMemo(() => layoutChain(filteredNodes, filteredEdges), [filteredNodes, filteredEdges]);

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

  // Zoom to fit the filtered nodes whenever the sector filter or search query changes.
  useEffect(() => {
    const id = setTimeout(() => {
      rfInstanceRef.current?.fitView({
        padding: 0.15,
        duration: 300,
      });
    }, 50);
    return () => clearTimeout(id);
  }, [sectorFilter, searchQuery]);

  const flowEdges: Edge[] = useMemo(
    () =>
      filteredEdges.map((e) => {
        const isOnPath = selected !== null && inPath.has(e.source) && inPath.has(e.target);
        return {
          id: `${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          type: "smoothstep",
          animated: false,
          style: {
            stroke: isOnPath ? "#1d4ed8" : "#9ca3af",
            strokeWidth: isOnPath ? 2 : 1,
            opacity: 1,
          },
        };
      }),
    [filteredEdges, selected, inPath],
  );

  // Tier 4: PNG export. We capture the React Flow's SVG
  // element, serialize to a data URL, and trigger download.
  // The exported file has a white background so it's
  // printable / slide-deckable.
  const [exporting, setExporting] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const handleExportPng = useCallback(() => {
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
      {/* Export button — top-right of the graph panel. */}
      <button
        type="button"
        onClick={handleExportPng}
        disabled={exporting}
        className="absolute right-3 top-3 z-10 rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
        aria-label="Export value chain as image"
      >
        {exporting ? "Exporting…" : "Export SVG"}
      </button>

      {/* Cohort legend — bottom-left, only when a cohort is
          active. Explains what the color recoloring means. */}
      {cohortSegment && (
        <div className="absolute bottom-3 left-3 z-10 max-w-xs rounded border border-gray-300 bg-white/95 px-2.5 py-1.5 text-xs text-gray-700 shadow-sm">
          <strong>Cohort:</strong> colored by the regime of{" "}
          <span className="font-mono">{cohortSegment}</span>. Nodes
          without that segment's own data render grey.
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
