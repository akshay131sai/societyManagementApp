import { AlertTriangle, Check, Monitor, Moon, RotateCcw, Sun } from "lucide-react";
import * as React from "react";

import { NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFField,
  NFInput,
  NFPageHeader,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { useAppDispatch, useAppSelector } from "@/store";
import { discardDraft, previewTheme, resetTheme, saveTheme } from "@/store/themeSlice";
import {
  THEME_PRESETS,
  isValidHex,
  meetsContrast,
  suggestAccessibleShade,
  type ThemeConfig,
  type ThemeMode,
} from "@/theme/deriveTokens";
import { cn } from "@/utils/cn";

const MODES: { value: ThemeMode; label: string; icon: React.ReactNode }[] = [
  { value: "light", label: "Light", icon: <Sun className="size-4" /> },
  { value: "dark", label: "Dark", icon: <Moon className="size-4" /> },
  { value: "system", label: "System", icon: <Monitor className="size-4" /> },
];

export default function AppearancePage() {
  const dispatch = useAppDispatch();
  const { config, draft, saving } = useAppSelector((s) => s.theme);
  const society = useAppSelector((s) => s.auth.society);

  const current = draft ?? config;
  const dirty = draft !== null;
  const [saved, setSaved] = React.useState(false);

  // Restore the persisted theme if the admin navigates away without saving —
  // an unsaved preview must never outlive the screen that created it.
  React.useEffect(() => {
    return () => {
      dispatch(discardDraft());
    };
  }, [dispatch]);

  const set = React.useCallback(
    (patch: Partial<ThemeConfig>) => {
      setSaved(false);
      dispatch(previewTheme(patch));
    },
    [dispatch],
  );

  async function onSave() {
    await dispatch(saveTheme(current));
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  const contrastOk = meetsContrast(current.primaryColor);
  const suggestion = contrastOk ? null : suggestAccessibleShade(current.primaryColor);

  return (
    <>
      <NFPageHeader
        title="Appearance"
        description={`Customise how NestFlow looks for ${society?.name ?? "your society"}. Only this society is affected.`}
        actions={
          <div className="flex items-center gap-2">
            <NFButton
              variant="ghost"
              onClick={() => dispatch(resetTheme())}
              disabled={saving}
            >
              <RotateCcw /> Reset
            </NFButton>
            <NFButton onClick={onSave} loading={saving} disabled={!dirty && !saved}>
              {saved ? (
                <>
                  <Check /> Saved
                </>
              ) : (
                "Save changes"
              )}
            </NFButton>
          </div>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        {/* ---------------------------------------------------------------- */}
        {/* Controls                                                          */}
        {/* ---------------------------------------------------------------- */}
        <div className="space-y-5">
          <NFCard>
            <NFCardHeader
              title="Mode"
              description="System follows each person's device setting."
            />
            <NFCardBody>
              <div
                role="radiogroup"
                aria-label="Theme mode"
                className="grid grid-cols-3 gap-2"
              >
                {MODES.map((mode) => {
                  const active = current.themeMode === mode.value;
                  return (
                    <button
                      key={mode.value}
                      role="radio"
                      aria-checked={active}
                      onClick={() => set({ themeMode: mode.value })}
                      className={cn(
                        "flex flex-col items-center gap-2 rounded-[var(--nf-radius)] border px-3 py-4 text-[13px] font-medium transition-colors",
                        active
                          ? "border-[var(--nf-primary)] bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)]"
                          : "border-[var(--nf-border)] text-[var(--nf-text-muted)] hover:border-[var(--nf-border-strong)]",
                      )}
                    >
                      {mode.icon}
                      {mode.label}
                    </button>
                  );
                })}
              </div>
            </NFCardBody>
          </NFCard>

          <NFCard>
            <NFCardHeader
              title="Brand colour"
              description="Buttons, links, highlights and the focus ring."
            />
            <NFCardBody className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {Object.entries(THEME_PRESETS).map(([name, hex]) => {
                  const active = current.primaryColor.toUpperCase() === hex.toUpperCase();
                  return (
                    <button
                      key={name}
                      onClick={() => set({ primaryColor: hex })}
                      aria-label={name}
                      aria-pressed={active}
                      title={name}
                      className={cn(
                        "flex size-11 items-center justify-center rounded-full border-2 transition-transform hover:scale-105",
                        active ? "border-[var(--nf-text)]" : "border-transparent",
                      )}
                      style={{ backgroundColor: hex }}
                    >
                      {active && <Check className="size-4 text-white drop-shadow" aria-hidden />}
                    </button>
                  );
                })}
              </div>

              <ColorField
                label="Custom colour"
                id="primary"
                value={current.primaryColor}
                onChange={(v) => set({ primaryColor: v })}
              />

              {!contrastOk && suggestion && (
                <div
                  role="alert"
                  className="flex gap-2.5 rounded-[var(--nf-radius)] border border-[var(--nf-warning)]/30 bg-[var(--nf-warning-subtle)] p-3"
                >
                  <AlertTriangle
                    className="mt-0.5 size-4 shrink-0 text-[var(--nf-warning)]"
                    aria-hidden
                  />
                  <div className="text-[12.5px] leading-relaxed">
                    <p className="font-semibold text-[var(--nf-warning)]">Low contrast</p>
                    <p className="mt-0.5 text-[var(--nf-text-muted)]">
                      Text on this colour will be hard to read. Try{" "}
                      <button
                        onClick={() => set({ primaryColor: suggestion })}
                        className="font-mono font-semibold text-[var(--nf-primary)] underline underline-offset-2"
                      >
                        {suggestion}
                      </button>{" "}
                      instead.
                    </p>
                  </div>
                </div>
              )}
            </NFCardBody>
          </NFCard>

          <NFCard>
            <NFCardHeader title="Supporting colours" />
            <NFCardBody className="grid gap-4 sm:grid-cols-2">
              <ColorField
                label="Secondary"
                id="secondary"
                value={current.secondaryColor}
                onChange={(v) => set({ secondaryColor: v })}
              />
              <ColorField
                label="Accent"
                id="accent"
                value={current.accentColor}
                onChange={(v) => set({ accentColor: v })}
              />
              <ColorField
                label="Sidebar"
                id="sidebar"
                value={current.sidebarColor}
                onChange={(v) => set({ sidebarColor: v })}
                className="sm:col-span-2"
              />
            </NFCardBody>
          </NFCard>

          <NFCard>
            <NFCardHeader title="Roundness" description="Applies to cards, buttons and inputs." />
            <NFCardBody>
              <div className="flex items-center gap-4">
                <span className="text-xs text-[var(--nf-text-muted)]">0</span>
                <input
                  type="range"
                  min={0}
                  max={32}
                  step={1}
                  value={current.borderRadius}
                  onChange={(e) => set({ borderRadius: Number(e.target.value) })}
                  aria-label="Border radius in pixels"
                  className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-[var(--nf-border)] accent-[var(--nf-primary)]"
                />
                <span className="text-xs text-[var(--nf-text-muted)]">32</span>
                <span className="w-12 text-right font-mono text-sm tabular-nums text-[var(--nf-text)]">
                  {current.borderRadius}px
                </span>
              </div>
            </NFCardBody>
          </NFCard>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Live preview — real components, not swatches                      */}
        {/* ---------------------------------------------------------------- */}
        <div className="lg:sticky lg:top-24 lg:self-start">
          <NFCard>
            <NFCardHeader
              title="Live preview"
              description="These are the real components, already using your changes."
            />
            <NFCardBody className="space-y-5">
              <div className="flex flex-wrap gap-2">
                <NFButton size="sm">Primary</NFButton>
                <NFButton size="sm" variant="secondary">
                  Secondary
                </NFButton>
                <NFButton size="sm" variant="outline">
                  Outline
                </NFButton>
                <NFButton size="sm" variant="ghost">
                  Ghost
                </NFButton>
              </div>

              <div className="flex flex-wrap gap-2">
                <NFStatusBadge status="ACTIVE" />
                <NFStatusBadge status="UNPAID" />
                <NFStatusBadge status="OVERDUE" />
                <NFStatusBadge status="TRIAL" />
              </div>

              <NFStatCard
                label="Maintenance due"
                value="₹12,950"
                hint="Q3 2026 · due 15 Sep"
                icon={<Check />}
              />

              <NFField label="Flat number" htmlFor="preview-input">
                <NFInput id="preview-input" placeholder="A-1203" defaultValue="A-1203" />
              </NFField>

              {/* Sidebar sample, so the sidebar colour is judged in context */}
              <div
                className="overflow-hidden rounded-[var(--nf-radius)]"
                style={{ backgroundColor: "var(--nf-sidebar)" }}
              >
                <div className="space-y-1 p-3">
                  <div
                    className="rounded-[var(--nf-radius-sm)] px-3 py-2 text-[13px] font-medium text-white"
                    style={{ backgroundColor: "var(--nf-sidebar-active)" }}
                  >
                    Dashboard
                  </div>
                  <div className="px-3 py-2 text-[13px] font-medium text-[var(--nf-sidebar-foreground)]">
                    Bills
                  </div>
                  <div className="px-3 py-2 text-[13px] font-medium text-[var(--nf-sidebar-foreground)]">
                    Residents
                  </div>
                </div>
              </div>
            </NFCardBody>
          </NFCard>

          {dirty && (
            <p className="mt-3 text-center text-[13px] text-[var(--nf-text-muted)]">
              You have unsaved changes.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

function ColorField({
  label,
  id,
  value,
  onChange,
  className,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const [text, setText] = React.useState(value);
  React.useEffect(() => setText(value), [value]);

  const invalid = !isValidHex(text);

  return (
    <NFField
      label={label}
      htmlFor={id}
      className={className}
      error={invalid ? "Use a 6-digit hex colour, e.g. #4F46E5" : undefined}
    >
      <div className="flex items-center gap-2">
        <label
          className="relative size-10 shrink-0 cursor-pointer overflow-hidden rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)]"
          style={{ backgroundColor: isValidHex(value) ? value : "#ffffff" }}
        >
          <input
            type="color"
            value={isValidHex(value) ? value : "#4F46E5"}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            className="absolute inset-0 cursor-pointer opacity-0"
            aria-label={`${label} colour picker`}
          />
        </label>
        <NFInput
          id={id}
          value={text}
          invalid={invalid}
          spellCheck={false}
          onChange={(e) => {
            const next = e.target.value.toUpperCase();
            setText(next);
            if (isValidHex(next)) onChange(next);
          }}
          className="font-mono uppercase"
        />
      </div>
    </NFField>
  );
}
