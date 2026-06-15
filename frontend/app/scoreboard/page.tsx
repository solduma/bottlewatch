import Link from "next/link";
import { listSegments } from "../lib/api";
import { ScoreboardTable } from "../components/ScoreboardTable";
import { PageHeader } from "../components/ui/PageHeader";

export const dynamic = "force-dynamic";

export default async function ScoreboardTablePage() {
  const rows = await listSegments();
  return (
    <section>
      <PageHeader
        title="Bottleneck scoreboard"
        subtitle={`${rows.length} rows · 10 segments × 3 horizons. Click a column to sort; click a segment to drill in.`}
        action={
          <Link href="/" className="text-sm text-blue-700 hover:underline">
            ← Back to quadrant
          </Link>
        }
      />
      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <ScoreboardTable rows={rows} />
      </div>
    </section>
  );
}
