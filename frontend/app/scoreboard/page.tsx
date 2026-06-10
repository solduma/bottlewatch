import Link from "next/link";
import { listSegments } from "../lib/api";
import { ScoreboardTable } from "../components/ScoreboardTable";

export const dynamic = "force-dynamic";

export default async function ScoreboardTablePage() {
  const rows = await listSegments();
  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Bottleneck scoreboard</h1>
        <Link href="/" className="text-sm text-blue-700 hover:underline">
          ← Back to quadrant
        </Link>
      </div>
      <p className="mb-4 text-sm text-gray-600">
        {rows.length} rows · 10 segments × 3 horizons. Click a column to sort;
        click a segment to drill in.
      </p>
      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <ScoreboardTable rows={rows} />
      </div>
    </section>
  );
}
