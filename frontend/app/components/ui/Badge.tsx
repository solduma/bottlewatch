import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface BadgeProps {
  children: ReactNode;
  className?: string;
}

export function Badge({ children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700",
        className,
      )}
    >
      {children}
    </span>
  );
}
