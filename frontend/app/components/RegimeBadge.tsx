import type { Regime, RegimeConfidence } from "../lib/api";
import { regimePill } from "../lib/colors";

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
      {regime}
      {confidence === "low" && <span className="opacity-50">·</span>}
    </span>
  );
}
