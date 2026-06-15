import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface FilterGroupProps {
  children: ReactNode;
  className?: string;
}

export function FilterGroup({ children, className }: FilterGroupProps) {
  return (
    <div className={cn("mb-4 flex flex-wrap gap-3", className)}>
      {children}
    </div>
  );
}
