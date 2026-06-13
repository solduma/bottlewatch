import { notFound } from "next/navigation";
import type { Horizon, Regime, SegmentScore, TickerRow } from "../../lib/api";
import { getSegment, listTickers } from "../../lib/api";
import { RegimeBadge } from "../../components/RegimeBadge";
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
  return (
    <section>
      <h1 className="mb-0.5 text-2xl font-semibold">{detail.name || detail.segment}</h1>
      <p className="mb-4 font-mono text-xs text-gray-500">{detail.segment}</p>
      <p className="mb-4 text-sm text-gray-600">
        {detail.horizons.length} horizons · {detail.signals.length} recent signals
      </p>

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
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Sub-scores
      </h2>
      <div className="mb-8 rounded border border-gray-200 bg-white p-4">
        {Object.entries(detail.sub_scores).map(([name, val], i) => {
          const v = val ?? 0;
          const pct = Math.round(v * 100);
          return (
            <div key={name} className="mb-2 last:mb-0">
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-700">
                  {SUB_SCORE_LABELS[name] ?? name}
                </span>
                <span className="font-mono text-gray-500">
                  {val === null ? "—" : `${pct}%`}
                </span>
              </div>
              <div className="mt-1 h-2 w-full overflow-hidden rounded bg-gray-100">
                <div
                  className={`h-full ${SUB_SCORE_COLORS[i % SUB_SCORE_COLORS.length]}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
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

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Tickers
      </h2>
      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Exchange</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Subsegment</th>
              <th className="px-3 py-2">Exposure %</th>
              <th className="px-3 py-2">Market Cap</th>
              <th className="px-3 py-2">Currency Hedge</th>
              <th className="px-3 py-2">Notes</th>
            </tr>
          </thead>
          <tbody>
            {tickers.map((t) => (
              <tr key={t.ticker} className="border-t border-gray-100">
                <td className="px-3 py-2 font-mono font-medium">
                  <a
                    href={`/tickers/${t.ticker}`}
                    className="text-blue-700 hover:underline"
                  >
                    {t.ticker}
                  </a>
                </td>
                <td className="px-3 py-2 text-gray-700">{t.exchange}</td>
                <td className="px-3 py-2 text-gray-700">{t.name}</td>
                <td className="px-3 py-2 text-gray-700">
                  {t.subsegment ?? "—"}
                </td>
                <td className="px-3 py-2 font-mono text-gray-700">
                  {t.exposure_pct}%
                </td>
                <td className="px-3 py-2 text-gray-700">
                  {t.market_cap_bucket}
                </td>
                <td className="px-3 py-2 text-gray-700">
                  {t.currency_hedge}
                </td>
                <td className="px-3 py-2 text-gray-700 text-xs">
                  {t.notes}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mb-2 mt-8 text-sm font-semibold uppercase tracking-wide text-gray-500">
        Recent signals
      </h2>
      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="w-full text-sm">
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
            {detail.signals.map((s) => (
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
