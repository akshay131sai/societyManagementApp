/** Ephemeral UI state: sidebar, toasts, per-route list filters. */

import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export interface ListFilters {
  page: number;
  limit: number;
  q: string;
  [key: string]: string | number | boolean | undefined;
}

export interface UiState {
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  /** Keyed by route so returning to a list restores its page and search. */
  filters: Record<string, ListFilters>;
}

const SIDEBAR_KEY = "nf.ui.sidebarCollapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "true";
  } catch {
    return false;
  }
}

const initialState: UiState = {
  sidebarCollapsed: readCollapsed(),
  mobileNavOpen: false,
  filters: {},
};

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    toggleSidebar(state) {
      state.sidebarCollapsed = !state.sidebarCollapsed;
      try {
        localStorage.setItem(SIDEBAR_KEY, String(state.sidebarCollapsed));
      } catch {
        /* private browsing */
      }
    },
    setMobileNav(state, action: PayloadAction<boolean>) {
      state.mobileNavOpen = action.payload;
    },
    setFilters(state, action: PayloadAction<{ key: string; filters: Partial<ListFilters> }>) {
      const { key, filters } = action.payload;
      state.filters[key] = {
        ...{ page: 1, limit: 25, q: "" },
        ...(state.filters[key] ?? {}),
        ...filters,
      } as ListFilters;
    },
    resetFilters(state, action: PayloadAction<string>) {
      delete state.filters[action.payload];
    },
  },
});

export const { toggleSidebar, setMobileNav, setFilters, resetFilters } = uiSlice.actions;
export default uiSlice.reducer;
