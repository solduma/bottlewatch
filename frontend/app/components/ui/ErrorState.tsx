import { cn } from "../../lib/cn";

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * Consistent error placeholder with an optional retry action.
 *
 * Use this wherever a client fetch can fail so users can recover
 * without reloading the whole page.
 */
export function ErrorState({
  title = "Failed to load",
  message,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        "rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800",
        className,
      )}
      role="alert"
    >
      <p className="font-medium">{title}</p>
      {message && <p className="mt-1 text-xs text-red-700">{message}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      )}
    </div>
  );
}
