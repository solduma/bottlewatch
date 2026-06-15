import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Tiny utility that merges Tailwind classes without conflict.
 *
 * `clsx` handles conditional / array inputs; `tailwind-merge` deduplicates
 * overlapping utility classes (e.g., `px-2 px-4` → `px-4`).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
