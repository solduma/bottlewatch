// Typed fetchers for the Bottlewatch API. Server components call
// these directly; the API base is read from NEXT_PUBLIC_API_BASE
// (defaults to localhost:8000 for `make web` alongside `make api`).

export type Horizon = "near" | "med" | "long";

export type Regime =
  | "PEAKING"
  | "PEAKED"
  | "RESOLVING"
  | "EMERGING"
  | "STABLE"
  | "RESOLVING_FROM_LOW"
  | "NO_DATA";

export type RegimeConfidence = "low" | "medium" | "high";

export interface SegmentScore {
  segment: string;
  name: string;
  horizon: Horizon;
  score: number | null;
  momentum: number | null;
  regime: Regime;
  regime_confidence: RegimeConfidence;
  data_completeness: number;
  computed_at: string;
}

export interface SignalRow {
  id: number;
  segment: string;
  subsegment: string | null;
  signal_name: string;
  value_num: number | null;
  value_text: string | null;
  unit: string | null;
  geography: string | null;
  source: string;
  source_id: string | null;
  observed_at: string;
}

export interface SegmentDetail {
  segment: string;
  name: string;
  horizons: SegmentScore[];
  sub_scores: Record<string, number | null>;
  signals: SignalRow[];
}

export interface HealthResponse {
  db_ok: boolean;
  last_score_at: string | null;
  signals_count: number;
}

export interface TickerRow {
  ticker: string;
  exchange: string;
  name: string;
  segment: string;
  subsegment: string | null;
  exposure_pct: number;
  market_cap_bucket: string;
  mcap_usd: number | null;
  currency_hedge: string;
  notes: string;
  regime: Regime | null;
  regime_confidence: RegimeConfidence | null;
}

export interface ScreenerRow {
  segment: string;
  horizon: Horizon;
  score: number | null;
  momentum: number | null;
  regime: Regime;
  regime_confidence: RegimeConfidence;
  data_completeness: number;
  computed_at: string;
  rank_key: number | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`API ${path} failed: ${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export const listSegments = (horizon?: Horizon): Promise<SegmentScore[]> =>
  get(`/api/v1/segments${horizon ? `?horizon=${horizon}` : ""}`);
export const listScoresRegime = (horizon?: Horizon): Promise<SegmentScore[]> =>
  get(`/api/v1/scores/regime${horizon ? `?horizon=${horizon}` : ""}`);
export const listTickers = (segment?: string): Promise<TickerRow[]> =>
  get(`/api/v1/tickers${segment ? `?segment=${encodeURIComponent(segment)}` : ""}`);
export const getScreener = (side: "long" | "short", horizon: Horizon): Promise<ScreenerRow[]> =>
  get(`/api/v1/screener?side=${side}&horizon=${horizon}`);
export const getSegment = (slug: string): Promise<SegmentDetail> =>
  get(`/api/v1/segments/${encodeURIComponent(slug)}`);
export const getHealth = (): Promise<HealthResponse> => get("/api/v1/health");

// ---------------------------------------------------------------------------
// M3 types + fetchers
// ---------------------------------------------------------------------------

export interface ScoreHistoryPoint {
  computed_at: string;
  b: number | null;
  momentum: number | null;
  regime: string;
}

export interface ScoreHistory {
  segment: string;
  horizon: string;
  points: ScoreHistoryPoint[];
}

export interface ScoreHistoryBatched {
  horizon: string;
  months: number;
  series: { segment: string; points: ScoreHistoryPoint[] }[];
}

export const getScoreHistory = (
  segment: string,
  horizon: Horizon,
  months = 6,
): Promise<ScoreHistory> =>
  get(`/api/v1/scores/history?segment=${encodeURIComponent(segment)}&horizon=${horizon}&months=${months}`);

export const getScoreHistoryBatched = (
  segments: string[],
  horizon: Horizon,
  months = 6,
): Promise<ScoreHistoryBatched> =>
  get(
    `/api/v1/scores/history?segments=${encodeURIComponent(segments.join(","))}&horizon=${horizon}&months=${months}`,
  );

export interface TickerDetailSegment {
  segment: string;
  subsegment: string | null;
  exposure_pct: number;
  regime_near: string | null;
  score_near: number | null;
  momentum_near: number | null;
  thesis_count: number;
}

export interface TickerDetailThesis {
  id: number;
  side: string | null;
  body_md: string;
  updated_at: string;
}

export interface TickerDetail {
  ticker: string;
  exchange: string;
  name: string;
  segments: TickerDetailSegment[];
  companies: string[];
  thesis: TickerDetailThesis[];
  eta: { eta: string; confidence: string } | null;
  thesis_count: number;
}

export const getTicker = (ticker: string): Promise<TickerDetail> =>
  get(`/api/v1/tickers/${encodeURIComponent(ticker)}`);

export interface MapNode {
  id: string;
  label: string;
  sector: string;
  regime: string | null;
  score: number | null;
  momentum: number | null;
}

// The /api/v1/map endpoint returns edges with `from`/`to` (the
// backend's vocabulary); the React Flow graph expects
// `source`/`target`. `ValueChainEdge` accepts either form so the
// caller can pass the raw API response to a normalizer without
// having to declare a parallel interface.
export interface ValueChainEdge {
  from?: string;
  to?: string;
  source?: string;
  target?: string;
  commodity?: string | null;
}

// Normalize the API edge to the {source, target} shape that
// chainLayout.ts and React Flow expect. The backend currently
// uses `from`/`to`; the React Flow graph wants `source`/`target`.
// This is the single place that knows about both vocabularies.
export function normalizeChainEdge(edge: ValueChainEdge): { source: string; target: string } {
  return {
    source: edge.source ?? edge.from ?? "",
    target: edge.target ?? edge.to ?? "",
  };
}

export interface MapPathNode {
  id: string;
  regime: string | null;
  score: number | null;
  depth: number;
}

export interface MapNodeDetail {
  node: MapNode;
  upstream: MapPathNode[];
  downstream: MapPathNode[];
  companies: string[];
  eta: { eta: string; confidence: string } | null;
  thesis_count: number;
}

export const getMapNode = (slug: string): Promise<MapNodeDetail> =>
  get(`/api/v1/map/${encodeURIComponent(slug)}`);

export interface ThesisRow {
  id: number;
  segment: string;
  ticker: string | null;
  side: string | null;
  body_md: string;
  created_at: string;
  updated_at: string;
}

export const listThesis = (opts?: { segment?: string; ticker?: string; side?: string }): Promise<ThesisRow[]> => {
  const params = new URLSearchParams();
  if (opts?.segment) params.set("segment", opts.segment);
  if (opts?.ticker) params.set("ticker", opts.ticker);
  if (opts?.side) params.set("side", opts.side);
  const qs = params.toString();
  return get(`/api/v1/thesis${qs ? `?${qs}` : ""}`);
};

export const saveThesis = async (body: {
  segment: string;
  ticker?: string | null;
  side?: string | null;
  body_md: string;
}): Promise<ThesisRow> => {
  const resp = await fetch(`${API_BASE}/api/v1/thesis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`POST /thesis failed: ${resp.status}`);
  return resp.json() as Promise<ThesisRow>;
};

export const deleteThesis = async (id: number): Promise<void> => {
  const resp = await fetch(`${API_BASE}/api/v1/thesis/${id}`, { method: "DELETE" });
  if (!resp.ok && resp.status !== 204) throw new Error(`DELETE /thesis/${id} failed: ${resp.status}`);
};