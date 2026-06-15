import { Skeleton } from "../components/ui/Skeleton";

/**
 * Server-route loading fallback for /scoreboard.
 *
 * Mirrors the page header and table shape so the transition feels
 * instant rather than showing a blank screen.
 */
export default function ScoreboardLoading() {
  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-5 w-32" />
      </div>
      <Skeleton className="mb-4 h-5 w-64" />
      <div className="rounded border border-gray-200 bg-white p-3">
        <Skeleton className="mb-3 h-8 w-full" />
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="mb-2 h-10 w-full" />
        ))}
      </div>
    </section>
  );
}
