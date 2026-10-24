# Theme System

> Every society gets its own look. Changing Society A must never affect Society B.
> One CSS bundle serves all of them.

## 1. Approach

Themes are **data**, not CSS. A society's theme is a row in its tenant database
(`theme_settings`). At runtime the client derives a set of CSS custom properties
from that row and writes them onto `document.documentElement`. Tailwind and
every NestFlow component read those variables, so a theme change is a style
recalculation — no re-render of the tree, no stylesheet swap, no per-tenant
build.

```
tenant DB theme_settings
        |
        v
GET /api/v1/theme  (returns with /auth/me, so it lands in one round trip)
        |
        v
Redux themeSlice
        |
        v
applyTheme(): computes the full token set and sets CSS vars on <html>
        |
        v
Tailwind utilities + NF components resolve against the vars
```

Because the variables live on `<html>` and nothing is cached to a global scope
outside the session, two societies open in two browser tabs simply each set
their own variables in their own document. There is no shared mutable style
state.

## 2. Token contract

Set on `:root` by `applyTheme`:

```css
--nf-primary            /* brand base */
--nf-primary-hover
--nf-primary-active
--nf-primary-foreground /* auto-chosen for contrast */
--nf-primary-subtle     /* tinted background for badges/hover rows */

--nf-secondary
--nf-secondary-foreground
--nf-accent
--nf-accent-foreground

--nf-background         /* page */
--nf-surface            /* cards, sheets */
--nf-surface-raised     /* popovers, dropdowns */
--nf-sidebar
--nf-sidebar-foreground
--nf-sidebar-active

--nf-text
--nf-text-muted
--nf-text-subtle
--nf-border
--nf-border-strong
--nf-ring               /* focus ring */

--nf-success  --nf-success-subtle
--nf-warning  --nf-warning-subtle
--nf-danger   --nf-danger-subtle
--nf-info     --nf-info-subtle

--nf-radius             /* base; sm/md/lg/xl derived via calc() */
--nf-radius-sm  --nf-radius-lg  --nf-radius-xl
```

Derived radii use `calc()` off the single stored value, so the "roundness"
slider is one number:

```css
--nf-radius-sm: calc(var(--nf-radius) - 4px);
--nf-radius-lg: calc(var(--nf-radius) + 4px);
--nf-radius-xl: calc(var(--nf-radius) + 8px);
```

Tailwind is wired to the same variables in `tailwind.config.ts`, so
`bg-nf-primary`, `text-nf-muted`, `rounded-nf` are available as ordinary
utilities and stay in sync automatically.

## 3. Colour derivation

The society stores **four** colours (`primary`, `secondary`, `accent`,
`sidebar`) plus a mode and a radius. Everything else is derived in
`src/theme/deriveTokens.ts`.

Derivation works in **OKLCH**, not HSL. Rotating lightness in HSL makes
saturated hues (especially the pink/orange presets) go muddy or neon; OKLCH is
perceptually uniform, so `hover` and `subtle` variants stay recognisably the
same colour at every hue.

```
primary            -> parse hex to OKLCH
primary-hover      -> L * 0.92                     (darker in light mode, lighter in dark)
primary-active     -> L * 0.85
primary-subtle     -> L -> 0.96, C * 0.25          (light) | L -> 0.24, C * 0.35 (dark)
primary-foreground -> white or near-black, whichever wins APCA contrast vs primary
```

`primary-foreground` is **computed, not stored**. This is the difference between
a theme picker that looks like a toy and one that is safe: an admin who picks a
pale yellow primary still gets legible dark text on their buttons, and a deep
indigo gets white. Contrast is checked, not assumed.

Semantic colours (success/warning/danger/info) are **fixed** and not
customisable. Red must mean danger in every society.

## 4. Modes

`themeMode` is `light | dark | system`.

- `light` / `dark` — set `data-theme` on `<html>` explicitly.
- `system` — no attribute; a `matchMedia('(prefers-color-scheme: dark)')`
  listener re-derives tokens when the OS flips.

Neutrals (background, surface, text, border) come from two curated ramps rather
than being derived from the brand colour — a slightly tinted neutral ramp looks
intentional, a fully derived one looks broken at extreme hues. The brand hue is
applied to neutrals only as a very low chroma tint (C ≈ 0.006).

## 5. Flash prevention

An inline script in `index.html` runs before React mounts, reads the last known
theme from `localStorage` (`nf.theme.<societyId>`) and applies the variables
immediately. The authoritative theme then arrives with `/auth/me` and
overwrites it. A returning user sees no white flash and no wrong-colour flash.

`localStorage` is a **cache keyed by society id**, never the source of truth,
and is cleared on logout.

## 6. Theme customizer

`Society Admin → Appearance`. Requires `theme.update`.

```
+-- Mode ------------------------------------------+
|  ( ) Light      ( ) Dark      (o) System         |
+--------------------------------------------------+
+-- Primary ---------------------------------------+
|  [Indigo] [Blue] [Purple] [Pink] [Green] [Orange]|
|  Custom  #4F46E5                    [swatch]     |
+--------------------------------------------------+
+-- Secondary / Accent / Sidebar ------------------+
+-- Roundness -------------------------------------+
|  8px  --------[o]---------  20px                 |
+--------------------------------------------------+
+-- Logo ------------------------------------------+
|  [ upload ]  PNG/SVG, max 512KB                  |
+--------------------------------------------------+

  [ Reset to default ]          [ Save changes ]
```

- **Live preview** is genuinely live: the customizer applies tokens to the real
  document on change (debounced 60ms), so the admin previews against the actual
  sidebar and real cards, not a mock swatch. Navigating away without saving
  restores the persisted theme.
- **Contrast warning** appears inline if a chosen primary cannot reach APCA Lc 60
  against either candidate foreground — with a suggested nearest safe shade.
- **Save** PUTs to `/api/v1/theme`; the response is the persisted row and
  becomes the new Redux state.
- **Reset** restores the seeded default (Indigo, system, 14px).

## 7. Isolation guarantees

| Risk | Mitigation |
|---|---|
| Cross-society bleed | Theme is read from the *tenant* DB, resolved from the principal. Society B's row is unreachable from an A session. |
| `theme.update` on another society | Impossible — no society id is accepted; the write targets the caller's tenant session. |
| Stale cache after switching users | `localStorage` key is namespaced by society id and cleared on logout. |
| CSS bundle per tenant | Does not exist. One bundle, variables differ. |

Tested by `test_theme_isolation.py`: set A to pink, set B to blue, re-read both,
assert A is unchanged and B is unchanged; and a frontend test asserting
`applyTheme` writes only to `documentElement` and nothing to a module-level
singleton.

## 8. Defaults

```json
{
  "themeMode": "system",
  "primaryColor": "#4F46E5",
  "secondaryColor": "#0EA5E9",
  "accentColor": "#8B5CF6",
  "sidebarColor": "#101828",
  "borderRadius": 14,
  "logoUrl": null
}
```
