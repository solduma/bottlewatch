import Link from "next/link";
import { getBacktestReport } from "../lib/api";
import { Card } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default async function BacktestPage({
  searchParams,
}: {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = (await searchParams) ?? {};
  const horizon = typeof params.horizon === "string" ? params.horizon : "near";
  const forwardDays = typeof params.forward_days === "string" ? parseInt(params.forward_days, 10) : 90;
  const normalizationMode =
    typeof params.normalization_mode === "string" ? params.normalization_mode : "both";

  const report = await getBacktestReport({
    horizon: horizon as "near" | "med" | "long",
    forward_days: forwardDays,
    normalization_mode: normalizationMode as "fixed" | "rolling" | "both",
  });

  const longBaskets = report.baskets.filter((b) => b.side === "long");
  const shortBaskets = report.baskets.filter((b) => b.side === "short");

  const avg = (xs: (number | null)[]) => {
    const vals = xs.filter((x): x is number => x !== null);
    return vals.length > 0 ? vals.reduce((sum, x) => sum + x, 0) / vals.length : null;
  };

  const longReturn = avg(longBaskets.map((b) => b.equal_weight_return));
  const longNetReturn = avg(longBaskets.map((b) => b.net_return));
  const shortReturn = avg(shortBaskets.map((b) => b.equal_weight_return));
  const shortNetReturn = avg(shortBaskets.map((b) => b.net_return));

  return (
    <section className="space-y-6">
      <PageHeader
        title="Backtest report"
        subtitle={`${report.n_eval_dates} evaluation dates · ${report.n_eval_points} (segment, ticker, date) tuples · ${report.horizon} horizon · ${report.forward_days}-day forward return`}
        action={
          <Link href="/" className="text-sm text-blue-700 hover:underline">
            ← Back to quadrant
          </Link>
        }
      />

      {report.seed_share_warning_dates.length > 0 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          ⚠️ Seed-share warning: {report.seed_share_warning_dates.length} evaluation dates had
          &gt;80% static-seed coverage. Results on those dates are research-seed dominated.
        </div>
      )}

      {report.n_eval_dates > 0 && report.n_eval_dates < 8 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          ⚠️ Low confidence: only {report.n_eval_dates} evaluation dates. The date-level bootstrap CI and
          p-value are wide and unstable on so few dates — treat the IC as indicative, not conclusive.
        </div>
      )}

      {(report.n_constant_score_segments > 0 || report.n_segments_evaluated > 0) && (
        <div className="text-xs text-gray-500">
          Disclosure: {report.n_segments_evaluated} segment(s) evaluated;{" "}
          {report.n_constant_score_segments} dropped for constant scores over the window (no IC computable).
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <div className="text-sm text-gray-600">Overall IC</div>
          <div className="text-2xl font-semibold">
            {report.overall_ic != null ? report.overall_ic.toFixed(3) : "n/a"}
          </div>
          <div className="text-xs text-gray-500">
            p={report.overall_p_value?.toFixed(3) ?? "n/a"} ·{" "}
            {report.overall_ci_low != null && report.overall_ci_high != null
              ? `95% CI [${report.overall_ci_low.toFixed(3)}, ${report.overall_ci_high.toFixed(3)}]`
              : "CI n/a"}
          </div>
        </Card>
        <Card>
          <div className="text-sm text-gray-600">Avg long basket return (gross)</div>
          <div className="text-2xl font-semibold">
            {longReturn != null ? `${(longReturn * 100).toFixed(1)}%` : "n/a"}
          </div>
          <div className="text-xs text-gray-500">
            {longBaskets.length} rebalances · net {longNetReturn != null ? `${(longNetReturn * 100).toFixed(1)}%` : "n/a"}
          </div>
        </Card>
        <Card>
          <div className="text-sm text-gray-600">Avg short basket return (gross)</div>
          <div className="text-2xl font-semibold">
            {shortReturn != null ? `${(shortReturn * 100).toFixed(1)}%` : "n/a"}
          </div>
          <div className="text-xs text-gray-500">
            {shortBaskets.length} rebalances · net {shortNetReturn != null ? `${(shortNetReturn * 100).toFixed(1)}%` : "n/a"}
          </div>
        </Card>
      </div>

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Per-segment IC</h2>
        {report.per_segment_ic.length === 0 ? (
          <p className="text-sm text-gray-600">No per-segment IC available.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">Segment</th>
                  <th className="px-3 py-2 font-medium">N</th>
                  <th className="px-3 py-2 font-medium">ρ</th>
                  <th className="px-3 py-2 font-medium">p-value</th>
                  <th className="px-3 py-2 font-medium">95% CI</th>
                  <th className="px-3 py-2 font-medium">BH</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.per_segment_ic.map((row) => (
                  <tr key={row.segment}>
                    <td className="px-3 py-2 font-medium">{row.segment}</td>
                    <td className="px-3 py-2">{row.n}</td>
                    <td className="px-3 py-2">{row.rho != null ? row.rho.toFixed(3) : "n/a"}</td>
                    <td className="px-3 py-2">{row.p_value?.toFixed(3) ?? "n/a"}</td>
                    <td className="px-3 py-2">
                      {row.ci_low != null && row.ci_high != null
                        ? `[${row.ci_low.toFixed(3)}, ${row.ci_high.toFixed(3)}]`
                        : "n/a"}
                    </td>
                    <td className="px-3 py-2">{row.bh_rejected ? "✅" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Basket snapshots</h2>
        {report.baskets.length === 0 ? (
          <p className="text-sm text-gray-600">No baskets available.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">Date</th>
                  <th className="px-3 py-2 font-medium">Side</th>
                  <th className="px-3 py-2 font-medium">Tickers</th>
                  <th className="px-3 py-2 font-medium">Gross</th>
                  <th className="px-3 py-2 font-medium">Net</th>
                  <th className="px-3 py-2 font-medium">Vol (ann)</th>
                  <th className="px-3 py-2 font-medium">Max DD</th>
                  <th className="px-3 py-2 font-medium">Hit rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.baskets.map((b) => (
                  <tr key={`${b.eval_date}-${b.side}`}>
                    <td className="px-3 py-2">{b.eval_date}</td>
                    <td className="px-3 py-2">{b.side}</td>
                    <td className="px-3 py-2">{b.tickers.join(", ")}</td>
                    <td className="px-3 py-2">
                      {b.equal_weight_return != null ? `${(b.equal_weight_return * 100).toFixed(1)}%` : "n/a"}
                    </td>
                    <td className="px-3 py-2">
                      {b.net_return != null ? `${(b.net_return * 100).toFixed(1)}%` : "n/a"}
                    </td>
                    <td className="px-3 py-2">
                      {b.volatility != null ? `${(b.volatility * 100).toFixed(1)}%` : "n/a"}
                    </td>
                    <td className="px-3 py-2">
                      {b.max_drawdown != null ? `${(b.max_drawdown * 100).toFixed(1)}%` : "n/a"}
                    </td>
                    <td className="px-3 py-2">
                      {b.hit_rate != null ? `${(b.hit_rate * 100).toFixed(0)}%` : "n/a"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {report.fixed_vs_rolling && (
        <Card>
          <h2 className="mb-3 text-lg font-semibold">Fixed vs rolling</h2>
          <div className="mb-3 grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-600">Fixed overall IC:</span>{" "}
              {report.fixed_vs_rolling.fixed_overall_ic?.toFixed(3) ?? "n/a"}
            </div>
            <div>
              <span className="text-gray-600">Rolling overall IC:</span>{" "}
              {report.fixed_vs_rolling.rolling_overall_ic?.toFixed(3) ?? "n/a"}
            </div>
          </div>
          {report.fixed_vs_rolling.per_segment.length === 0 ? (
            <p className="text-sm text-gray-600">No common fixed/rolling points to compare.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="px-3 py-2 font-medium">Segment</th>
                    <th className="px-3 py-2 font-medium">Mean |ΔB|</th>
                    <th className="px-3 py-2 font-medium">Regime flips</th>
                    <th className="px-3 py-2 font-medium">Common points</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {report.fixed_vs_rolling.per_segment.map((row) => (
                    <tr key={row.segment}>
                      <td className="px-3 py-2 font-medium">{row.segment}</td>
                      <td className="px-3 py-2">
                        {row.mean_abs_b_diff != null ? row.mean_abs_b_diff.toFixed(3) : "n/a"}
                      </td>
                      <td className="px-3 py-2">{row.regime_flips}</td>
                      <td className="px-3 py-2">{row.n_common_points}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </section>
  );
}
