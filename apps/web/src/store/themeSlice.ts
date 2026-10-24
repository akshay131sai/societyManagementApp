/**
 * Theme state.
 *
 * The society's theme is applied to `document.documentElement` by
 * `applyTheme`; this slice holds the config so the customizer can preview,
 * revert and save. Nothing about the theme lives in a module-level singleton.
 */

import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";

import { api } from "@/services/api";
import { DEFAULT_THEME, applyTheme, cacheTheme, type ThemeConfig } from "@/theme/deriveTokens";
import type { ThemePayload } from "@/types";

export interface ThemeState {
  config: ThemeConfig;
  /** Unsaved preview shown live in the customizer, discarded on navigate away. */
  draft: ThemeConfig | null;
  saving: boolean;
  loaded: boolean;
}

const initialState: ThemeState = {
  config: DEFAULT_THEME,
  draft: null,
  saving: false,
  loaded: false,
};

export function fromPayload(payload: ThemePayload): ThemeConfig {
  return {
    themeMode: payload.theme_mode,
    primaryColor: payload.primary_color,
    secondaryColor: payload.secondary_color,
    accentColor: payload.accent_color,
    sidebarColor: payload.sidebar_color,
    borderRadius: payload.border_radius,
    logoUrl: payload.logo_url,
    societyName: payload.society_name ?? null,
  };
}

function toPayload(config: ThemeConfig): Record<string, unknown> {
  return {
    theme_mode: config.themeMode,
    primary_color: config.primaryColor,
    secondary_color: config.secondaryColor,
    accent_color: config.accentColor,
    sidebar_color: config.sidebarColor,
    border_radius: config.borderRadius,
    logo_url: config.logoUrl ?? null,
  };
}

export const saveTheme = createAsyncThunk<ThemeConfig, ThemeConfig>(
  "theme/save",
  async (config) => {
    const saved = await api.put<ThemePayload>("/theme", toPayload(config));
    return fromPayload(saved);
  },
);

export const resetTheme = createAsyncThunk<ThemeConfig>("theme/reset", async () => {
  const saved = await api.post<ThemePayload>("/theme/reset");
  return fromPayload(saved);
});

const themeSlice = createSlice({
  name: "theme",
  initialState,
  reducers: {
    setTheme(state, action: PayloadAction<ThemeConfig>) {
      state.config = action.payload;
      state.draft = null;
      state.loaded = true;
      applyTheme(action.payload);
    },
    /** Live preview: applied to the real document so the admin sees real UI. */
    previewTheme(state, action: PayloadAction<Partial<ThemeConfig>>) {
      state.draft = { ...(state.draft ?? state.config), ...action.payload };
      applyTheme(state.draft);
    },
    discardDraft(state) {
      state.draft = null;
      applyTheme(state.config);
    },
    reapply(state) {
      applyTheme(state.draft ?? state.config);
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(saveTheme.pending, (state) => {
        state.saving = true;
      })
      .addCase(saveTheme.fulfilled, (state, action) => {
        state.saving = false;
        state.config = action.payload;
        state.draft = null;
        state.loaded = true;
        applyTheme(action.payload);
      })
      .addCase(saveTheme.rejected, (state) => {
        state.saving = false;
        applyTheme(state.config);
      })
      .addCase(resetTheme.fulfilled, (state, action) => {
        state.config = action.payload;
        state.draft = null;
        applyTheme(action.payload);
      });
  },
});

export const { setTheme, previewTheme, discardDraft, reapply } = themeSlice.actions;
export { cacheTheme };
export default themeSlice.reducer;
