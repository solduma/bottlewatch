"use client";

import { cn } from "../../lib/cn";

interface SkeletonProps {
  className?: string;
}

/**
 * Simple pulse skeleton used for loading placeholders.
 *
 * Width/height are controlled entirely by the caller via `className`
 * so the shape matches whatever it replaces (text line, card, table row).
 */
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn("animate-pulse rounded bg-gray-200", className)}
      aria-hidden="true"
    />
  );
}
