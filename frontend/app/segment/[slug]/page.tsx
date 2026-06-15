import { notFound } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import type { Horizon, Regime, SegmentScore, SubScoreValue } from "../../lib/api";
import { getSegment, listTickers } from "../../lib/api";
import { RegimeBadge } from "../../components/RegimeBadge";
import { TickersTable } from "../../components/TickersTable";
import { displayName } from "../../lib/score_help";

const SUB_SCORE_LABELS: Record<string, string> = {
  lead_time_growth: "Lead time growth",
  capacity_tightness: "Capacity tightness",
  geo_concentration: "Geo concentration",
  regulatory_friction: "Regulatory friction",
  demand_signal: "Demand signal",
};

const SUB_SCORE_COLORS = [
  "bg-blue-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-violet-500",
  "bg-emerald-500",
];

function sourceBadge(
  source: string,
  confidence: string,
  imputed: boolean,
  normalizationMode: SubScoreValue["normalization_mode"],
) {
  const base = "ml-1 rounded px-1 py-0 text-[10px] font-medium";
  if (source === "extractor") {
    const modeLabel = normalizationMode ? ` (${normalizationMode})` : "";
    return (
      <span className={`${base} bg-green-100 text-green-800`} title={`Source: live extractor (${confidence} confidence)${modeLabel}`}>
        live
      </span>
    );
  }
  if (imputed || source === "imputed") {
    return (
      <span className={`${base} bg-gray-100 text-gray-600`} title="Value imputed because no source was available">
        imputed
      </span>
    );
  }
  return (
    <span className={`${base} bg-yellow-100 text-yellow-800`} title="Value from static research seed">
      seed
    </span>
  );
}

/**
 * Static implication string per regime per horizon.
 *
 * M2 keeps this on the frontend (read-only, no API call). M3 will
 * replace this with a dynamic call to /api/v1/screener that ranks
 * the segment within the basket.
 */
function implication(regime: Regime, side: "long" | "short"): string {
  const messages: Record<Regime, { long: string; short: string }> = {
    EMERGING: {
      long: "Proactive long candidate — low B with rising momentum.",
      short: "Not a short — momentum is rising.",
    },
    PEAKING: {
      long: "Hold or trim (no new longs) — too late to be early.",
      short: "Watch for B' to turn negative, then short.",
    },
    PEAKED: {
      long: "Stable at high — momentum has flattened. Hold or trim.",
      short: "Wait for B' to turn negative before shorting.",
    },
    RESOLVING: {
      long: "★ HARD GUARD: excluded from long basket. Do NOT long.",
      short: "Short candidate — high B and falling fast.",
    },
    RESOLVING_FROM_LOW: {
      long: "Not a long yet — watch for re-emergence from the low.",
      short: "Not a short either — B was already low.",
    },
    STABLE: {
      long: "Wait for confirmation — no clear directional signal.",
      short: "Skip — not a short candidate.",
    },
    NO_DATA: {
      long: "Insufficient data — no investment recommendation.",
      short: "Insufficient data — no investment recommendation.",
    },
  };
  return messages[regime][side];
}

export default async function SegmentDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  let detail;
  let tickers;
  try {
    detail = await getSegment(slug);
    tickers = await listTickers(slug);
  } catch {
    notFound();
  }
  const horizons: SegmentScore[] = ["near", "med", "long"]
    .map((h) => detail.horizons.find((x) => x.horizon === h))
    .filter((x): x is SegmentScore => x !== undefined);
  const nearRegime = horizons.find((h) => h.horizon === "near")?.regime;
  const signals = detail.signals
    .slice()
    .sort((a, b) => new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime());
  return (
    <section>
      <div className="mb-2 flex items-center gap-3 text-sm text-blue-700">
        <Link href="/" className="hover:underline">← Back to quadrant</Link>
        <Link href="/scoreboard" className="hover:underline">← Back to scoreboard</Link>
      </div>
      <div className="mb-0.5 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{detail.name || detail.segment}</h1>
        <Link
          href={`/map?node=${encodeURIComponent(slug)}`}
          className="text-sm text-blue-700 hover:underline"
        >
          See on map
        </Link>
      </div>
      <p className="mb-4 font-mono text-xs text-gray-500">{detail.segment}</p>
      <p className="mb-4 text-sm text-gray-600">
        {detail.horizons.length} horizons · {signals.length} recent signals
      </p>

      {nearRegime === "RESOLVING" && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-800">
          ★ Hard guard: excluded from long basket. Do NOT long.
        </div>
      )}

      {detail.brief && (
        <div className="mb-6 rounded border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            What this segment is
          </h2>
          <div className="prose prose-sm max-w-none text-gray-700">
            <ReactMarkdown>{detail.brief.summary}</ReactMarkdown>
          </div>
        </div>
      )}

      <div className="mb-6 rounded border border-gray-200 bg-white p-4">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
          Regime call (near horizon)
        </h2>
        {horizons
          .filter((h) => h.horizon === "near")
          .map((h) => (
            <div key={h.horizon} className="mb-2 last:mb-0">
              <div className="mb-1 flex items-center gap-2">
                <RegimeBadge regime={h.regime} confidence={h.regime_confidence} />
                <span className="text-sm text-gray-700">
                  {h.regime === "RESOLVING" ? "★ Hard guard fires on long" : ""}
                </span>
              </div>
              <p className="text-sm text-gray-700">
                <strong>Long basket:</strong> {implication(h.regime, "long")}
              </p>
              <p className="text-sm text-gray-700">
                <strong>Short basket:</strong> {implication(h.regime, "short")}
              </p>
            </div>
          ))}
        {detail.brief && detail.brief.regime_call_md && (
          <div className="mt-3 border-t border-gray-100 pt-3">
            <h3 className="mb-1 text-xs font-semibold text-gray-500">Research reasoning</h3>
            <div className="prose prose-sm max-w-none text-gray-700">
              <ReactMarkdown>{detail.brief.regime_call_md}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Sub-scores
      </h2>
      <div className="mb-8 rounded border border-gray-200 bg-white p-4">
        {Object.entries(detail.sub_scores).map(([name, sub], i) => {
          const val = sub?.value ?? null;
          const v = val ?? 0;
          const pct = Math.round(v * 100);
          const colorClass = SUB_SCORE_COLORS[i % SUB_SCORE_COLORS.length];
          return (
            <div key={name} className="mb-2 last:mb-0">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 text-gray-700">
                  <span className={`inline-block h-2 w-2 rounded-full ${colorClass}`} />
                  {SUB_SCORE_LABELS[name] ?? name}
                  {sub && sourceBadge(sub.source, sub.confidence, sub.imputed, sub.normalization_mode)}
                </span>
                <span className="font-mono text-gray-500">
                  {val === null ? "—" : `${pct}%`}
                </span>
              </div>
              <div className="mt-1 h-2 w-full overflow-hidden rounded bg-gray-100">
                <div
                  className={`h-full ${colorClass}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {sub?.raw_value !== null && sub?.raw_value !== undefined && (
                <div className="mt-0.5 text-[10px] text-gray-400">
                  raw: {sub.raw_value.toFixed(3)} · {sub.normalization_mode}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Horizons
      </h2>
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {horizons.map((h) => (
          <HorizonCard key={h.horizon} h={h.horizon} score={h} />
        ))}
      </div>

      {detail.brief && (
        <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="rounded border border-gray-200 bg-white p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Momentum & direction
            </h2>
            <div className="prose prose-sm max-w-none text-gray-700">
              <ReactMarkdown>{detail.brief.momentum_summary}</ReactMarkdown>
            </div>
          </div>
          <div className="rounded border border-gray-200 bg-white p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Resolution timeline
            </h2>
            <div className="prose prose-sm max-w-none text-gray-700">
              <ReactMarkdown>{detail.brief.resolution_summary}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Tickers ({tickers.length})
      </h2>
      <TickersTable tickers={tickers} />

      <h2 className="mb-2 mt-8 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Recent signals ({signals.length})
      </h2>
      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="sticky-first-col w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2">Observed</th>
              <th className="px-3 py-2">Signal</th>
              <th className="px-3 py-2">Value</th>
              <th className="px-3 py-2">Unit</th>
              <th className="px-3 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.id} className="border-t border-gray-100">
                <td className="px-3 py-2 font-mono text-gray-600">
                  {new Date(s.observed_at).toISOString().slice(0, 10)}
                </td>
                <td className="px-3 py-2">{s.signal_name}</td>
                <td className="px-3 py-2 font-mono">
                  {s.value_num ?? s.value_text ?? "—"}
                </td>
                <td className="px-3 py-2 text-gray-500">{s.unit ?? "—"}</td>
                <td className="px-3 py-2 text-gray-500">{s.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function HorizonCard({ h, score }: { h: Horizon; score: SegmentScore }) {
  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">
        {h}
      </div>
      <div className="font-mono text-2xl">
        {score.score === null ? "—" : score.score.toFixed(1)}
      </div>
      <div className="mt-2">
        <RegimeBadge regime={score.regime} confidence={score.regime_confidence} />
      </div>
      <div className="mt-2 text-xs text-gray-500">
        momentum:{" "}
        <span className="font-mono">
          {score.momentum === null ? "—" : score.momentum.toFixed(2)}
        </span>
        {" · "}
        data:{" "}
        <span className="font-mono">
          {(score.data_completeness * 100).toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
