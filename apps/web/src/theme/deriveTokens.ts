/**
 * Theme token derivation.
 *
 * A society stores four colours, a mode and a radius. Every other token is
 * computed here and written onto `document.documentElement` as a CSS custom
 * property — which is why one CSS bundle serves every society.
 *
 * Derivation works in **OKLCH**, not HSL. Scaling lightness in HSL turns
 * saturated hues (the pink and orange presets especially) muddy or neon;
 * OKLCH is perceptually uniform, so a hover state stays recognisably the same
 * colour at every hue.
 *
 * Foreground colours are **computed against measured contrast**, never
 * assumed. An admin who picks pale yellow still gets legible dark text on
 * their buttons.
 */

export type ThemeMode = "light" | "dark" | "system";

export interface ThemeConfig {
  themeMode: ThemeMode;
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  sidebarColor: string;
  borderRadius: number;
  logoUrl?: string | null;
  societyName?: string | null;
}

export const DEFAULT_THEME: ThemeConfig = {
  themeMode: "system",
  primaryColor: "#4F46E5",
  secondaryColor: "#0EA5E9",
  accentColor: "#8B5CF6",
  sidebarColor: "#101828",
  borderRadius: 14,
  logoUrl: null,
  societyName: null,
};

export const THEME_PRESETS: Record<string, string> = {
  Indigo: "#4F46E5",
  Blue: "#2563EB",
  Purple: "#7C3AED",
  Pink: "#DB2777",
  Green: "#059669",
  Orange: "#EA580C",
};

const HEX_RE = /^#[0-9A-Fa-f]{6}$/;

/** Only a strict 6-digit hex is ever written into a custom property. */
export function isValidHex(value: string): boolean {
  return HEX_RE.test(value);
}

/* -------------------------------------------------------------------------- */
/* Colour space conversion                                                    */
/* -------------------------------------------------------------------------- */

interface Oklch {
  l: number; // 0..1
  c: number; // 0..~0.4
  h: number; // degrees
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(r: number, g: number, b: number): string {
  const to = (v: number) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

const srgbToLinear = (v: number) => {
  const s = v / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
};

const linearToSrgb = (v: number) => {
  const s = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  return s * 255;
};

function hexToOklch(hex: string): Oklch {
  const [r8, g8, b8] = hexToRgb(hex);
  const r = srgbToLinear(r8);
  const g = srgbToLinear(g8);
  const b = srgbToLinear(b8);

  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);

  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;

  const c = Math.sqrt(A * A + B * B);
  let h = (Math.atan2(B, A) * 180) / Math.PI;
  if (h < 0) h += 360;

  return { l: L, c, h };
}

function oklchToHex({ l, c, h }: Oklch): string {
  const hr = (h * Math.PI) / 180;
  const A = c * Math.cos(hr);
  const B = c * Math.sin(hr);

  const l_ = (l + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m_ = (l - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s_ = (l - 0.0894841775 * A - 1.291485548 * B) ** 3;

  const r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_;
  const g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_;
  const b = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_;

  return rgbToHex(linearToSrgb(r), linearToSrgb(g), linearToSrgb(b));
}

/* -------------------------------------------------------------------------- */
/* Contrast                                                                    */
/* -------------------------------------------------------------------------- */

function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio, 1..21. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const LIGHT_FG = "#FFFFFF";
const DARK_FG = "#101828";

/**
 * Pick the foreground that is actually readable on `background`.
 *
 * This is the difference between a theme picker that looks like a toy and one
 * that is safe: a pale primary gets dark text, a deep primary gets white, and
 * neither is guessed.
 */
export function readableForeground(background: string): string {
  return contrastRatio(background, LIGHT_FG) >= contrastRatio(background, DARK_FG)
    ? LIGHT_FG
    : DARK_FG;
}

/** Whether `background` can carry legible text at WCAG AA (4.5:1). */
export function meetsContrast(background: string): boolean {
  return contrastRatio(background, readableForeground(background)) >= 4.5;
}

/** Nearest shade of the same hue that reaches AA, for the customizer's hint. */
export function suggestAccessibleShade(hex: string): string {
  if (!isValidHex(hex)) return DEFAULT_THEME.primaryColor;
  const base = hexToOklch(hex);
  for (const delta of [0, -0.05, -0.1, -0.15, 0.05, -0.2, 0.1, -0.25, -0.3]) {
    const candidate = oklchToHex({ ...base, l: clamp(base.l + delta, 0.1, 0.95) });
    if (meetsContrast(candidate)) return candidate;
  }
  return hex;
}

/* -------------------------------------------------------------------------- */
/* Derivation                                                                 */
/* -------------------------------------------------------------------------- */

function shift(hex: string, lightnessFactor: number): string {
  const base = hexToOklch(hex);
  return oklchToHex({ ...base, l: clamp(base.l * lightnessFactor, 0.05, 0.98) });
}

function subtle(hex: string, dark: boolean): string {
  const base = hexToOklch(hex);
  return dark
    ? oklchToHex({ ...base, l: 0.26, c: base.c * 0.38 })
    : oklchToHex({ ...base, l: 0.955, c: base.c * 0.22 });
}

/** Neutral ramp, tinted very slightly toward the brand hue. */
function neutral(l: number, hue: number, dark: boolean): string {
  return oklchToHex({ l, c: dark ? 0.008 : 0.006, h: hue });
}

export function resolveMode(mode: ThemeMode): "light" | "dark" {
  if (mode !== "system") return mode;
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Compute the full token set. Pure — no DOM access, so it is unit-testable.
 */
export function deriveTokens(config: ThemeConfig): Record<string, string> {
  const resolved = resolveMode(config.themeMode);
  const dark = resolved === "dark";

  const primary = isValidHex(config.primaryColor)
    ? config.primaryColor
    : DEFAULT_THEME.primaryColor;
  const secondary = isValidHex(config.secondaryColor)
    ? config.secondaryColor
    : DEFAULT_THEME.secondaryColor;
  const accent = isValidHex(config.accentColor) ? config.accentColor : DEFAULT_THEME.accentColor;
  const sidebar = isValidHex(config.sidebarColor)
    ? config.sidebarColor
    : DEFAULT_THEME.sidebarColor;

  const hue = hexToOklch(primary).h;
  const radius = clamp(config.borderRadius ?? 14, 0, 32);

  // In dark mode a "hover" is lighter, not darker.
  const hoverFactor = dark ? 1.1 : 0.92;
  const activeFactor = dark ? 1.18 : 0.84;

  const sidebarFg = readableForeground(sidebar);
  const sidebarIsDark = sidebarFg === LIGHT_FG;

  return {
    "--nf-primary": primary,
    "--nf-primary-hover": shift(primary, hoverFactor),
    "--nf-primary-active": shift(primary, activeFactor),
    "--nf-primary-foreground": readableForeground(primary),
    "--nf-primary-subtle": subtle(primary, dark),

    "--nf-secondary": secondary,
    "--nf-secondary-foreground": readableForeground(secondary),
    "--nf-accent": accent,
    "--nf-accent-foreground": readableForeground(accent),

    "--nf-background": dark ? neutral(0.17, hue, true) : neutral(0.975, hue, false),
    "--nf-surface": dark ? neutral(0.22, hue, true) : "#ffffff",
    "--nf-surface-raised": dark ? neutral(0.26, hue, true) : "#ffffff",

    "--nf-sidebar": sidebar,
    "--nf-sidebar-foreground": sidebarIsDark ? "#cbd5e1" : "#334155",
    "--nf-sidebar-active": shift(sidebar, sidebarIsDark ? 1.45 : 0.92),

    "--nf-text": dark ? neutral(0.96, hue, true) : neutral(0.22, hue, false),
    "--nf-text-muted": dark ? neutral(0.7, hue, true) : neutral(0.55, hue, false),
    "--nf-text-subtle": dark ? neutral(0.55, hue, true) : neutral(0.68, hue, false),
    "--nf-border": dark ? neutral(0.29, hue, true) : neutral(0.91, hue, false),
    "--nf-border-strong": dark ? neutral(0.38, hue, true) : neutral(0.85, hue, false),
    "--nf-ring": primary,

    // Semantic colours stay fixed across societies; only their subtle
    // backgrounds follow the mode.
    "--nf-success": dark ? "#34d399" : "#059669",
    "--nf-success-subtle": dark ? "#052e23" : "#ecfdf5",
    "--nf-warning": dark ? "#fbbf24" : "#d97706",
    "--nf-warning-subtle": dark ? "#2e1e05" : "#fffbeb",
    "--nf-danger": dark ? "#f87171" : "#dc2626",
    "--nf-danger-subtle": dark ? "#2e1010" : "#fef2f2",
    "--nf-info": dark ? "#38bdf8" : "#0284c7",
    "--nf-info-subtle": dark ? "#05233a" : "#f0f9ff",

    "--nf-radius": `${radius}px`,
    "--nf-radius-sm": `${Math.max(radius - 6, 2)}px`,
    "--nf-radius-lg": `${radius + 4}px`,
    "--nf-radius-xl": `${radius + 10}px`,
  };
}

/* -------------------------------------------------------------------------- */
/* Application                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * Write the token set onto `<html>`.
 *
 * Everything is scoped to `documentElement` — nothing is cached in a
 * module-level singleton, so two societies open in two tabs cannot interfere.
 */
export function applyTheme(config: ThemeConfig): void {
  if (typeof document === "undefined") return;

  const root = document.documentElement;
  const tokens = deriveTokens(config);

  for (const [name, value] of Object.entries(tokens)) {
    root.style.setProperty(name, value);
  }

  if (config.themeMode === "system") {
    root.removeAttribute("data-theme");
    root.dataset.resolvedTheme = resolveMode("system");
  } else {
    root.setAttribute("data-theme", config.themeMode);
    root.dataset.resolvedTheme = config.themeMode;
  }

  root.style.colorScheme = resolveMode(config.themeMode);
}

const CACHE_PREFIX = "nf.theme.";

/**
 * Cache the theme per society so a returning user sees no wrong-colour flash.
 * This is a cache, never the source of truth — the API response overwrites it.
 */
export function cacheTheme(societyId: string, config: ThemeConfig): void {
  try {
    localStorage.setItem(CACHE_PREFIX + societyId, JSON.stringify(config));
    localStorage.setItem(`${CACHE_PREFIX}last`, societyId);
  } catch {
    // Private browsing or blocked storage: the theme still applies this session.
  }
}

export function readCachedTheme(societyId: string): ThemeConfig | null {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + societyId);
    return raw ? (JSON.parse(raw) as ThemeConfig) : null;
  } catch {
    return null;
  }
}

/** Clear every cached theme. Called on logout so no colour leaks to the next user. */
export function clearThemeCache(): void {
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(CACHE_PREFIX))
      .forEach((k) => localStorage.removeItem(k));
  } catch {
    /* ignore */
  }
}

/** Re-derive when the OS flips, but only while the society is on "system". */
export function watchSystemTheme(getConfig: () => ThemeConfig): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    const config = getConfig();
    if (config.themeMode === "system") applyTheme(config);
  };

  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
