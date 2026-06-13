"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import type { TickerRow, Regime, Horizon, SegmentScore } from "../lib/api";
import { listTickers, listSegments } from "../lib/api";
import { regimePill } from "../lib/colors";
import { displayName } from "../lib/score_help";

type SectorFilter = "all" | "Materials" | "Hardware" | "Infrastructure" | "Downstream";

type Side = "long" | "short" | "all";

export default function TickersPage() {
  const [tickers, setTickers] = useState<TickerRow[]>([]);
  const [allSegments, setAllSegments] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterSide, setFilterSide] = useState<Side>("all");
  const [filterRegime, setFilterRegime] = useState<string>("");
  const [filterSegment, setFilterSegment] = useState<string>("");
  const [filterSector, setFilterSector] = useState<SectorFilter>("all");
  const [sortKey, setSortKey] = useState<keyof TickerRow>("segment");
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const [searchQuery, setSearchQuery] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tickerData, segmentData] = await Promise.all([
        listTickers(),
        listSegments(),
      ]);
      setTickers(tickerData);
      const segmentsSet = new Set<string>();
      segmentData.forEach(seg => segmentsSet.add(seg.segment));
      setAllSegments([...segmentsSet].sort());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // const segments = [...new Set(tickers.map(t => t.segment))].sort();

  // Map segments to sectors (loaded from listSegments API).
  const segmentToSector = useMemo(() => {
    const map = new Map<string, string>();
    allSegments.forEach((segment) => {
      // This is a temporary fallback; we should get this from the API.
      // For now, use the same logic as in segments_meta.py.
      // Eventually, we should add sector to TickerDetail and TickerRow.
      const valueChain = [
        { segment: "raw_inputs", sector: "MaterialsSector" },
        { segment: "semiconductor_materials", sector: "MaterialsSector" },
        { segment: "front_end_equipment", sector: "HardwareSector" },
        { segment: "advanced_node_fabs", sector: "HardwareSector" },
        { segment: "advanced_packaging", sector: "HardwareSector" },
        { segment: "hbm_memory", sector: "HardwareSector" },
        { segment: "networking_interconnect", sector: "HardwareSector" },
        { segment: "gpu_asic_silicon", sector: "HardwareSector" },
        { segment: "systems_oem_odm", sector: "HardwareSector" },
        { segment: "rack_scale_integration", sector: "HardwareSector" },
        { segment: "fuel_power_inputs", sector: "InfrastructureSector" },
        { segment: "power_generation_oem", sector: "InfrastructureSector" },
        { segment: "transformers_switchgear", sector: "InfrastructureSector" },
        { segment: "td_utilities", sector: "InfrastructureSector" },
        { segment: "data_center_shell", sector: "InfrastructureSector" },
        { segment: "cooling_water", sector: "InfrastructureSector" },
        { segment: "inference_at_scale", sector: "DownstreamSector" },
        { segment: "raw_oil_gas", sector: "MaterialsSector" },
        { segment: "raw_mining", sector: "MaterialsSector" },
        { segment: "raw_nuclear_fuel", sector: "MaterialsSector" },
        { segment: "raw_water_utilities", sector: "MaterialsSector" },
        { segment: "mat_process_gases", sector: "MaterialsSector" },
        { segment: "mat_silicon_wafers", sector: "MaterialsSector" },
        { segment: "mat_photoresist", sector: "MaterialsSector" },
        { segment: "mat_cmp_slurries", sector: "MaterialsSector" },
        { segment: "fee_optical_components", sector: "HardwareSector" },
        { segment: "fee_vacuum_robotics", sector: "HardwareSector" },
        { segment: "fee_vacuum_pumps", sector: "HardwareSector" },
        { segment: "fab_utilities", sector: "InfrastructureSector" },
        { segment: "fab_process_chemicals", sector: "MaterialsSector" },
        { segment: "pkg_substrates", sector: "HardwareSector" },
        { segment: "pkg_ubm", sector: "MaterialsSector" },
        { segment: "hbm_dram_platform", sector: "HardwareSector" },
        { segment: "hbm_tsv_equipment", sector: "HardwareSector" },
        { segment: "net_optical_transceivers", sector: "HardwareSector" },
        { segment: "net_high_speed_pcb", sector: "HardwareSector" },
        { segment: "net_switch_asics", sector: "HardwareSector" },
        { segment: "sil_power_delivery", sector: "HardwareSector" },
        { segment: "sil_ip_eda", sector: "HardwareSector" },
        { segment: "sys_psu", sector: "HardwareSector" },
        { segment: "sys_chassis", sector: "HardwareSector" },
        { segment: "rack_cdu", sector: "HardwareSector" },
        { segment: "rack_busbars", sector: "HardwareSector" },
        { segment: "shell_land_reits", sector: "InfrastructureSector" },
        { segment: "shell_dark_fiber", sector: "InfrastructureSector" },
        { segment: "shell_colo_reits", sector: "InfrastructureSector" },
        { segment: "cool_chillers", sector: "InfrastructureSector" },
        { segment: "cool_pumps", sector: "InfrastructureSector" },
        { segment: "cool_water_treatment", sector: "MaterialsSector" },
        { segment: "gen_smr", sector: "InfrastructureSector" },
        { segment: "gen_gas_turbines", sector: "InfrastructureSector" },
        { segment: "gen_wind", sector: "InfrastructureSector" },
        { segment: "gen_solar", sector: "InfrastructureSector" },
        { segment: "gen_rare_earths", sector: "MaterialsSector" },
        { segment: "tnd_electrical_steel", sector: "MaterialsSector" },
        { segment: "tnd_copper", sector: "MaterialsSector" },
        { segment: "tnd_insulation", sector: "MaterialsSector" },
        { segment: "util_regulators", sector: "InfrastructureSector" },
        { segment: "fuel_oil_gas", sector: "MaterialsSector" },
        { segment: "fuel_uranium", sector: "MaterialsSector" },
        { segment: "fuel_mining", sector: "MaterialsSector" },
        { segment: "fuel_renewables", sector: "InfrastructureSector" },
        { segment: "inf_neocloud", sector: "DownstreamSector" },
        { segment: "inf_enterprise_saas", sector: "DownstreamSector" },
      ];

      const match = valueChain.find(vc => vc.segment === segment);
      if (match) {
        map.set(segment, match.sector);
      }
    });
    return map;
  }, [allSegments]);

  const filtered = tickers
    .filter(t => {
      // Search filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const tickerMatch = t.ticker.toLowerCase().includes(q);
        const nameMatch = t.name.toLowerCase().includes(q);
        const segmentMatch = displayName(t.segment).toLowerCase().includes(q);
        if (!tickerMatch && !nameMatch && !segmentMatch) {
          return false;
        }
      }
      // Sector filter
      if (filterSector !== "all") {
        const sector = segmentToSector.get(t.segment);
        if (!sector) return false;
        if (sector.replace(/Sector$/, "") !== filterSector) {
          return false;
        }
      }
      // Existing filters
      if (filterSegment && t.segment !== filterSegment) return false;
      if (filterSide === "long" && t.regime === "RESOLVING") return false;
      if (filterSide === "short" && t.regime !== "RESOLVING") return false;
      if (filterRegime && t.regime !== filterRegime) return false;
      return true;
    })
    .sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return -sortDir;
      if (av > bv) return sortDir;
      return 0;
    });

  function toggleSort(key: keyof TickerRow) {
    if (sortKey === key) {
      setSortDir(d => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      setSortDir(1);
    }
  }

  const SIDE_OPTIONS: { label: string; value: Side }[] = [
    { label: "All", value: "all" },
    { label: "Long", value: "long" },
    { label: "Short", value: "short" },
  ];

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Tickers</h1>
        <Link href="/" className="text-sm text-blue-700 hover:underline">← Back to quadrant</Link>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        {/* Search input */}
        <div className="relative flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="Search tickers, companies, segments…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm"
            aria-label="Search tickers"
          />
        </div>

        <div className="flex gap-1 rounded border border-gray-200 bg-white p-1 text-sm">
          {SIDE_OPTIONS.map(o => (
            <button
              key={o.value}
              onClick={() => setFilterSide(o.value)}
              className={`rounded px-2 py-1 transition-colors ${
                filterSide === o.value ? "bg-blue-100 text-blue-800 font-medium" : "text-gray-600 hover:bg-gray-50"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>

        <select
          value={filterSector}
          onChange={e => setFilterSector(e.target.value as SectorFilter)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="all">All sectors</option>
          <option value="Materials">Materials</option>
          <option value="Hardware">Hardware</option>
          <option value="Infrastructure">Infrastructure</option>
          <option value="Downstream">Downstream</option>
        </select>

        <select
          value={filterSegment}
          onChange={e => setFilterSegment(e.target.value)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="">All segments</option>
          {allSegments.map(s => <option key={s} value={s}>{displayName(s)}</option>)}
        </select>

        <select
          value={filterRegime}
          onChange={e => setFilterRegime(e.target.value)}
          className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
        >
          <option value="">All regimes</option>
          {["PEAKING","PEAKED","RESOLVING","EMERGING","STABLE","RESOLVING_FROM_LOW","NO_DATA"].map(r => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <span className="ml-auto text-xs text-gray-500">
          {loading ? "Loading…" : `${filtered.length} of ${tickers.length} tickers`}
        </span>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>
      )}

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              {[
                { key: "ticker", label: "Ticker" },
                { key: "name", label: "Name" },
                { key: "segment", label: "Segment" },
                { key: "exposure_pct", label: "Exposure" },
                { key: "market_cap_bucket", label: "Mcap" },
                { key: "currency_hedge", label: "FX Hedge" },
                { key: "regime", label: "Regime" },
              ].map(col => (
                <th
                  key={col.key}
                  className="cursor-pointer px-3 py-2 select-none"
                  onClick={() => toggleSort(col.key as keyof TickerRow)}
                >
                  {col.label}
                  {sortKey === col.key && (sortDir === 1 ? " ↑" : " ↓")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(t => (
              <tr key={`${t.ticker}-${t.segment}`} className="border-t border-gray-100 hover:bg-gray-50">
                <td className="px-3 py-2">
                  <Link href={`/tickers/${t.ticker}`} className="font-mono font-medium text-blue-700 hover:underline">
                    {t.ticker}
                  </Link>
                </td>
                <td className="px-3 py-2 text-gray-700">{t.name}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-600">
                  <Link href={`/segment/${t.segment}`} className="hover:underline">{displayName(t.segment)}</Link>
                </td>
                <td className="px-3 py-2 font-mono text-right text-gray-600">{t.exposure_pct.toFixed(0)}%</td>
                <td className="px-3 py-2 text-xs text-gray-500">{t.market_cap_bucket}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{t.currency_hedge || "—"}</td>
                <td className="px-3 py-2">
                  {t.regime && (
                    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${regimePill(t.regime)}`}>
                      {t.regime}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-sm text-gray-400 italic">
                  No tickers match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
