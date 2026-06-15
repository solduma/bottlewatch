import { Skeleton } from "../../components/ui/Skeleton";

/**
 * Server-route loading fallback for /segment/[slug].
 */
export default function SegmentDetailLoading() {
  return (
    <section>
      <Skeleton className="mb-2 h-5 w-32" />
      <Skeleton className="mb-0.5 h-8 w-72" />
      <Skeleton className="mb-4 h-4 w-48" />
      <Skeleton className="mb-6 h-24 w-full" />
      <Skeleton className="mb-2 h-5 w-24" />
      <Skeleton className="mb-8 h-40 w-full" />
      <Skeleton className="mb-2 h-5 w-24" />
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
      <Skeleton className="mb-2 h-5 w-24" />
      <Skeleton className="mb-8 h-64 w-full" />
      <Skeleton className="mb-2 h-5 w-28" />
      <Skeleton className="h-48 w-full" />
    </section>
  );
}
