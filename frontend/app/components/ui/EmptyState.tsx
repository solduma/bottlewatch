import { cn } from "../../lib/cn";

interface EmptyStateProps {
  title?: string;
  description?: string;
  className?: string;
}

/**
 * Consistent empty-state placeholder for lists, tables, and cells.
 *
 * Use this instead of inline italic `(none)` / `(empty)` text so every
 * empty view shares the same tone and spacing.
 */
export function EmptyState({
  title = "No data yet",
  description,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "rounded border border-dashed border-gray-200 bg-gray-50 p-4 text-sm text-gray-500",
        className,
      )}
    >
      <p className="font-medium">{title}</p>
      {description && <p className="mt-1 text-xs text-gray-400">{description}</p>}
    </div>
  );
}
