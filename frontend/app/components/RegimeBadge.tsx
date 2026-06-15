import type { Regime, RegimeConfidence } from "../lib/api";
import { regimePill } from "../lib/colors";

const REGIME_DESCRIPTION: Record<Regime, string> = {
  EMERGING: "Emerging bottleneck — proactive long",
  PEAKING: "Peaking bottleneck — hold or trim",
  PEAKED: "Peaked bottleneck — hold or trim",
  RESOLVING: "Resolving bottleneck — short or avoid long",
  RESOLVING_FROM_LOW: "Resolving from low — not yet long",
  STABLE: "Stable bottleneck — wait for signal",
  NO_DATA: "No regime data",
};

export function RegimeBadge({
  regime,
  confidence,
}: {
  regime: Regime;
  confidence: RegimeConfidence;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ring-1 ${regimePill(regime)}`}
      title={`regime_confidence: ${confidence}`}
    >
      <span aria-hidden="true">{regime}</span>
      <span className="sr-only">{REGIME_DESCRIPTION[regime]}</span>
      {confidence === "low" && <span className="opacity-50" aria-hidden="true">·</span>}
    </span>
  );
}
