import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";

interface IconButtonProps {
  icon: LucideIcon;
  "aria-label": string;
  onClick?: () => void;
  size?: "sm" | "md";
  className?: string;
}

export function IconButton({
  icon: Icon,
  "aria-label": ariaLabel,
  onClick,
  size = "md",
  className,
}: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center rounded text-gray-600 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50",
        size === "sm" ? "h-7 w-7" : "h-9 w-9",
        className,
      )}
    >
      <Icon className={cn(size === "sm" ? "h-4 w-4" : "h-5 w-5")} />
    </button>
  );
}
