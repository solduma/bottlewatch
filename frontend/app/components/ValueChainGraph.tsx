"use client";

import { useCallback, useMemo } from "react";
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
  onClick: (id: string) => void;
  [key: string]: unknown;
}

function ValueChainNode({ data }: NodeProps) {
  const d = data as ValueChainNodeData;
  const regime = d.regime ?? "NO_DATA";
  const fill = REGIME_FILL[regime] ?? REGIME_FILL.NO_DATA;
  const border = d.isSelected
    ? "#1d4ed8" // blue-700 when selected
    : d.isInPath
      ? "#60a5fa" // blue-400 when in the upstream/downstream path
      : (REGIME_BORDER[regime] ?? REGIME_BORDER.NO_DATA);
  const borderWidth = d.isSelected ? 3 : d.isInPath ? 2 : 1;

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
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "#9ca3af" }} />
      <div>{d.label}</div>
      <div style={{ fontSize: 10, color: "#6b7280", marginTop: 2 }}>{d.sector}</div>
      <Handle type="source" position={Position.Right} style={{ background: "#9ca3af" }} />
    </div>
  );
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
  // Translate the API's `from`/`to` form to React Flow's `source`/`target`
  // at the boundary. The API may return either; we accept both for
  // forward-compat. `normalizeChainEdge` is the single point of
  // vocabulary translation.
  const reactFlowEdges: ChainEdge[] = useMemo(
    () =>
      (edges as ValueChainEdge[])
        .map(normalizeChainEdge)
        .filter((e) => e.source && e.target),
    [edges],
  );

  const positioned = useMemo(() => layoutChain(nodes, reactFlowEdges), [nodes, reactFlowEdges]);

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
      positioned.map((n) => ({
        id: n.id,
        type: "valueChain",
        position: n.position,
        data: {
          ...n,
          isSelected: n.id === selected,
          isInPath: inPath.has(n.id),
          onClick: handleSelect,
        },
      })),
    [positioned, selected, inPath, handleSelect],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      reactFlowEdges.map((e) => {
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
          },
        };
      }),
    [reactFlowEdges, selected, inPath],
  );

  return (
    <div style={{ width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
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
            return REGIME_FILL[data.regime ?? "NO_DATA"] ?? REGIME_FILL.NO_DATA;
          }}
          nodeStrokeWidth={2}
          pannable
          zoomable
        />
      </ReactFlow>
    </div>
  );
}
