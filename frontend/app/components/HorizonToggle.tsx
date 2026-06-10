"use client";

import type { Horizon } from "../lib/api";

export function HorizonToggle({
  value,
  onChange,
}: {
  value: Horizon;
  onChange: (h: Horizon) => void;
}) {
  const horizons: Horizon[] = ["near", "med", "long"];
  return (
    <div className="inline-flex rounded border border-gray-300 bg-white">
      {horizons.map((h) => (
        <button
          key={h}
          type="button"
          onClick={() => onChange(h)}
          className={`px-4 py-1.5 text-sm font-medium ${
            value === h
              ? "bg-gray-900 text-white"
              : "text-gray-700 hover:bg-gray-50"
          } first:rounded-l last:rounded-r`}
        >
          {h}
        </button>
      ))}
    </div>
  );
}
