"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getTicker } from "../../lib/api";
import type { TickerDetail } from "../../lib/api";
import { SparklineForSegment } from "../../components/SparklineForSegment";
import { regimePill } from "../../lib/colors";
import ReactMarkdown from "react-markdown";
import { displayName } from "../../lib/score_help";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { Skeleton } from "../../components/ui/Skeleton";
import { Card } from "../../components/ui/Card";

export default function TickerDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = decodeURIComponent(params.ticker);
  const [detail, setDetail] = useState<TickerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTicker(ticker)
      .then(d => { setDetail(d); setError(null); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [ticker]);

  function handleRetry() {
    setLoading(true);
    setError(null);
    getTicker(ticker)
      .then(d => { setDetail(d); setError(null); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  if (loading) {
    return (
      <section>
        <Skeleton className="mb-4 h-5 w-32" />
        <div className="mb-6 rounded border border-gray-200 bg-white p-6">
          <Skeleton className="mb-1 h-10 w-64" />
          <Skeleton className="h-6 w-48" />
        </div>
        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <section>
        <div className="mb-4">
          <Link href="/tickers" className="text-sm text-blue-700 hover:underline">← Back to tickers</Link>
        </div>
        <ErrorState
          title={`Failed to load ${ticker}`}
          message={error}
          onRetry={handleRetry}
        />
      </section>
    );
  }
  if (!detail) return null;

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <nav aria-label="breadcrumb" className="text-sm text-gray-500">
          <Link href="/" className="text-blue-700 hover:underline">Quadrant</Link>
          {" / "}
          <Link href="/tickers" className="text-blue-700 hover:underline">Tickers</Link>
          {" / "}
          <span className="font-medium text-gray-900">{detail.ticker}</span>
        </nav>
        <Link
          href={`/thesis?ticker=${encodeURIComponent(detail.ticker)}`}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          + Thesis note
        </Link>
      </div>

      <Card className="mb-6 p-6">
        <h1 className="mb-1 text-3xl font-bold">{detail.name}</h1>
        <p className="text-lg text-gray-500">{detail.ticker} · {detail.exchange}</p>
      </Card>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {detail.segments.map(seg => {
          const name = displayName(seg.segment);
          return (
          <div key={seg.segment} className="rounded border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <Link
                href={`/segment/${seg.segment}`}
                className="text-sm font-medium text-blue-700 hover:underline"
                title={`${name} (${seg.segment})`}
              >
                <div className="flex flex-col">
                  <span>{name}</span>
                  {name !== seg.segment && (
                    <span className="font-mono text-[10px] text-gray-500">
                      {seg.segment}
                    </span>
                  )}
                </div>
              </Link>
              {seg.regime_near && (
                <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${regimePill(seg.regime_near)}`}>
                  {seg.regime_near}
                </span>
              )}
            </div>
            {seg.subsegment && <p className="mb-1 text-xs text-gray-500">{seg.subsegment}</p>}
            <div className="grid grid-cols-3 gap-2 text-xs text-gray-600">
              <div>
                <div className="text-gray-400">Exposure</div>
                <div className="font-mono font-medium">{seg.exposure_pct.toFixed(0)}%</div>
              </div>
              <div>
                <div className="text-gray-400">Score</div>
                <div className="font-mono font-medium">{seg.score_near?.toFixed(1) ?? "—"}</div>
              </div>
              <div>
                <div className="text-gray-400">Momentum</div>
                <div className="font-mono font-medium">{seg.momentum_near?.toFixed(1) ?? "—"}</div>
              </div>
            </div>
            <div className="mt-3">
              <SparklineForSegment segment={seg.segment} horizon="near" months={6} height={40} />
            </div>
          </div>
          );
        })}
      </div>

      {detail.companies.length > 0 && (
        <div className="mb-6 rounded border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Companies in value chain</h2>
          <div className="flex flex-wrap gap-2">
            {detail.companies.map(c => (
              <Link
                key={c}
                href={`/tickers/${encodeURIComponent(c)}`}
                className="rounded bg-gray-100 px-2 py-1 text-xs font-mono text-gray-700 hover:bg-blue-100 hover:text-blue-800"
              >
                {c}
              </Link>
            ))}
          </div>
        </div>
      )}

      {detail.eta && (
        <div className="mb-6 rounded border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Resolution ETA</h2>
          <p className="text-sm">
            <span className="font-mono font-medium">{detail.eta.eta}</span>
            {" "}
            <span className="text-gray-500">({detail.eta.confidence} confidence)</span>
          </p>
        </div>
      )}

      {detail.thesis.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Thesis notes ({detail.thesis.length})</h2>
          <div className="space-y-3">
            {detail.thesis.map(t => (
              <div key={t.id} className="rounded border border-gray-100 bg-gray-50 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                    t.side === "long" ? "bg-blue-100 text-blue-800" : "bg-green-100 text-green-800"
                  }`}>
                    {t.side ?? "neutral"}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(t.updated_at).toLocaleDateString()}
                  </span>
                </div>
                <div className="prose prose-sm max-w-none text-gray-700">
                  <ReactMarkdown>{t.body_md}</ReactMarkdown>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
