// Dagre-based left-to-right layout for the value chain DAG.
//
// Pure functions (no React, no DOM). The frontend has no JS test
// runner; coverage is via the manual /map page render and the
// build's TypeScript check.

import dagre from "dagre";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 60;

export interface ChainNode {
  id: string;
  label: string;
  sector: string;
  regime?: string | null;
  score?: number | null;
  momentum?: number | null;
  companies?: string[];
}

export interface ChainEdge {
  source: string;
  target: string;
}

export interface PositionedNode extends ChainNode {
  position: { x: number; y: number };
}

/** Layout a chain left-to-right with dagre. Returns nodes with `position` populated. */
export function layoutChain(nodes: ChainNode[], edges: ChainEdge[]): PositionedNode[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: "LR",
    nodesep: 30,
    ranksep: 80,
    marginx: 20,
    marginy: 20,
  });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  // Dedupe edges so dagre doesn't choke on parallel duplicates.
  const seen = new Set<string>();
  for (const e of edges) {
    const key = `${e.source}->${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    g.setEdge(e.source, e.target);
  }
  dagre.layout(g);

  return nodes.map((n) => {
    const layoutNode = g.node(n.id);
    return {
      ...n,
      position: {
        x: layoutNode.x - NODE_WIDTH / 2,
        y: layoutNode.y - NODE_HEIGHT / 2,
      },
    };
  });
}

export interface NeighborIndex {
  upstream: Record<string, string[]>;
  downstream: Record<string, string[]>;
}

/** Build a {node_id: {upstream, downstream}} index from edges. */
export function buildNeighborIndex(edges: ChainEdge[]): NeighborIndex {
  const upstream: Record<string, string[]> = {};
  const downstream: Record<string, string[]> = {};
  for (const e of edges) {
    if (!e.source || !e.target) continue;
    (downstream[e.source] ??= []).push(e.target);
    (upstream[e.target] ??= []).push(e.source);
  }
  return { upstream, downstream };
}
