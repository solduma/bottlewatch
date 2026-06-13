import { create } from "zustand";

export type SectorFilter = "all" | "Materials" | "Hardware" | "Infrastructure" | "Downstream";

interface MapState {
  // Existing focus state (already used by the breadcrumb).
  focusPath: string[];
  setFocus: (id: string) => void;
  drillUpstream: (id: string) => void;
  clearFocus: () => void;

  // Tier 2: search + sector filter.
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  sectorFilter: SectorFilter;
  setSectorFilter: (s: SectorFilter) => void;

  // Tier 3: cohort heatmap. When `cohortSegment` is set, the
  // graph recolors every node by that segment's regime rather
  // than each node's own regime.
  cohortSegment: string | null;
  setCohortSegment: (id: string | null) => void;
}

export const useMapStore = create<MapState>((set) => ({
  focusPath: [],
  setFocus: (id: string) => set({ focusPath: [id] }),
  drillUpstream: (id: string) =>
    set((state) => ({ focusPath: [...state.focusPath, id] })),
  clearFocus: () => set({ focusPath: [] }),

  searchQuery: "",
  setSearchQuery: (q) => set({ searchQuery: q }),
  sectorFilter: "all",
  setSectorFilter: (s) => set({ sectorFilter: s }),

  cohortSegment: null,
  setCohortSegment: (id) => set({ cohortSegment: id }),
}));