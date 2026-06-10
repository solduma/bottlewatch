import { create } from "zustand";

interface MapState {
  focusPath: string[];        // ordered list of node ids, oldest first
  setFocus: (id: string) => void;
  drillUpstream: (id: string) => void;
  clearFocus: () => void;
}

export const useMapStore = create<MapState>((set) => ({
  focusPath: [],
  setFocus: (id: string) => set({ focusPath: [id] }),
  drillUpstream: (id: string) =>
    set((state) => ({ focusPath: [...state.focusPath, id] })),
  clearFocus: () => set({ focusPath: [] }),
}));