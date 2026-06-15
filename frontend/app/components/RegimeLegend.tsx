import { REGIME_CLASSES } from "../lib/colors";

/**
 * Small legend that maps each regime color to its investment meaning.
 *
 * Place this near the quadrant or scoreboard so first-time users can
 * decode the badge colors without hovering everything.
 */
export function RegimeLegend() {
  const items = [
    { regime: "EMERGING", label: "EMERGING", hint: "proactive long" },
    { regime: "PEAKING", label: "PEAKING / PEAKED", hint: "hold or trim" },
    { regime: "RESOLVING", label: "RESOLVING", hint: "short / avoid long" },
    { regime: "STABLE", label: "STABLE", hint: "wait for signal" },
  ] as const;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
      {items.map(({ regime, label, hint }) => {
        const classes = REGIME_CLASSES[regime];
        return (
          <div key={regime} className="flex items-center gap-1.5">
            <span className={`h-3 w-3 rounded ${classes.pill.split(" ")[0]}`} />
            <span className="font-medium text-gray-700">{label}</span>
            <span className="text-gray-400">— {hint}</span>
          </div>
        );
      })}
    </div>
  );
}
