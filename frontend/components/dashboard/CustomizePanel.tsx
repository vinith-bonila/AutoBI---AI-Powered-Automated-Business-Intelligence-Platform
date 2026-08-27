"use client";

/**
 * The Customize side panel.
 *
 * Every control writes to the central `DashboardConfig`, so nothing here is
 * cosmetic-only — theme, palette, layout and KPI changes all persist and all
 * feed the same renderer and the exported configuration. The AI-generated
 * configuration is never lost: customisation edits a copy on top of it, and
 * "Reset" restores the original.
 */

import type { KPI } from "@/types";
import type { DashboardConfigApi } from "@/lib/useDashboardConfig";
import type { KpiFormatOverride, LayoutMode } from "@/lib/dashboardConfig";
import { PALETTES } from "@/lib/palettes";
import { Button, cn } from "@/components/ui";

const THEMES: { id: "light" | "dark" | "professional"; label: string }[] = [
  { id: "professional", label: "Professional" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

const LAYOUTS: { id: LayoutMode; label: string; hint: string }[] = [
  { id: "two-column", label: "2 columns", hint: "Balanced default" },
  { id: "three-column", label: "3 columns", hint: "Dense overview" },
  { id: "compact", label: "Compact", hint: "Smaller cards" },
  { id: "wide", label: "Wide charts", hint: "One per row" },
  { id: "executive", label: "Executive", hint: "Hero + supporting" },
];

const CUSTOM_TOKENS: { key: string; label: string }[] = [
  { key: "--color-accent", label: "Primary" },
  { key: "--color-surface", label: "Card background" },
  { key: "--color-plane", label: "Background" },
  { key: "--color-ink", label: "Text" },
];

const KPI_FORMATS: { value: KpiFormatOverride; label: string }[] = [
  { value: "number", label: "Number" },
  { value: "currency", label: "Currency" },
  { value: "percent", label: "Percent" },
  { value: "count", label: "Count" },
  { value: "decimal", label: "Decimal" },
];

export function CustomizePanel({
  open,
  onClose,
  api,
  kpis,
}: {
  open: boolean;
  onClose: () => void;
  api: DashboardConfigApi;
  kpis: KPI[];
}) {
  const { config } = api;

  return (
    <>
      {open ? (
        <div
          className="fixed inset-0 z-40 bg-black/20"
          onClick={onClose}
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full w-[360px] max-w-[92vw] flex-col border-l border-[var(--color-hairline)] bg-[var(--color-surface)] shadow-xl transition-transform duration-300",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between border-b border-[var(--color-hairline)] px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--color-ink)]">
              Customize dashboard
            </h2>
            <p className="text-xs text-[var(--color-ink-muted)]">
              Changes apply live and are saved automatically.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--color-ink-muted)] hover:bg-[var(--color-plane)]"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="scroll-thin flex-1 space-y-7 overflow-y-auto px-5 py-5">
          {/* Theme */}
          <Section title="Theme">
            <div className="grid grid-cols-3 gap-2">
              {THEMES.map((theme) => (
                <OptionChip
                  key={theme.id}
                  label={theme.label}
                  active={config.theme.mode === theme.id}
                  onClick={() => api.setTheme({ mode: theme.id })}
                />
              ))}
            </div>
          </Section>

          {/* Palette */}
          <Section title="Colour palette">
            <div className="grid grid-cols-2 gap-2">
              {PALETTES.map((palette) => (
                <button
                  key={palette.id}
                  type="button"
                  onClick={() => api.setTheme({ paletteId: palette.id })}
                  className={cn(
                    "flex flex-col gap-2 rounded-lg border p-2.5 text-left transition-colors",
                    config.theme.paletteId === palette.id
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                      : "border-[var(--color-hairline)] hover:bg-[var(--color-plane)]",
                  )}
                >
                  <span className="text-xs font-medium text-[var(--color-ink)]">
                    {palette.name}
                  </span>
                  <span className="flex gap-1">
                    {palette.series.slice(0, 6).map((hex) => (
                      <span
                        key={hex}
                        className="h-3 w-3 rounded-full"
                        style={{ backgroundColor: hex }}
                      />
                    ))}
                  </span>
                </button>
              ))}
            </div>
          </Section>

          {/* Custom colors */}
          <Section title="Custom colours" hint="Override individual tokens">
            <div className="space-y-2">
              {CUSTOM_TOKENS.map((token) => (
                <div key={token.key} className="flex items-center justify-between">
                  <span className="text-sm text-[var(--color-ink-secondary)]">
                    {token.label}
                  </span>
                  <input
                    type="color"
                    value={hexFor(config.theme.custom[token.key], token.key)}
                    onChange={(event) =>
                      api.setTheme({
                        custom: {
                          ...config.theme.custom,
                          [token.key]: event.target.value,
                        },
                      })
                    }
                    className="h-7 w-12 cursor-pointer rounded border border-[var(--color-hairline)] bg-transparent"
                    aria-label={token.label}
                  />
                </div>
              ))}
              {Object.keys(config.theme.custom).length ? (
                <button
                  type="button"
                  onClick={() => api.setTheme({ custom: {} })}
                  className="text-xs text-[var(--color-ink-muted)] underline-offset-2 hover:underline"
                >
                  Clear custom colours
                </button>
              ) : null}
            </div>
          </Section>

          {/* Layout */}
          <Section title="Layout">
            <div className="space-y-1.5">
              {LAYOUTS.map((layout) => (
                <button
                  key={layout.id}
                  type="button"
                  onClick={() => api.setLayout(layout.id)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors",
                    config.layout === layout.id
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                      : "border-[var(--color-hairline)] hover:bg-[var(--color-plane)]",
                  )}
                >
                  <span className="text-sm font-medium text-[var(--color-ink)]">
                    {layout.label}
                  </span>
                  <span className="text-xs text-[var(--color-ink-muted)]">
                    {layout.hint}
                  </span>
                </button>
              ))}
            </div>
          </Section>

          {/* KPIs */}
          <Section title="KPIs" hint="Show, hide, reorder or reformat">
            <ul className="space-y-1.5">
              {config.kpiOrder.map((id, index) => {
                const kpi = kpis.find((k) => k.id === id);
                if (!kpi) return null;
                const conf = config.kpiConfig[id];
                const hidden = conf?.hidden ?? false;
                return (
                  <li
                    key={id}
                    className="rounded-lg border border-[var(--color-hairline)] p-2"
                  >
                    <div className="flex items-center gap-2">
                      <div className="flex flex-col">
                        <button
                          type="button"
                          aria-label="Move up"
                          disabled={index === 0}
                          onClick={() => api.moveKpi(index, index - 1)}
                          className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] disabled:opacity-30"
                        >
                          ▲
                        </button>
                        <button
                          type="button"
                          aria-label="Move down"
                          disabled={index === config.kpiOrder.length - 1}
                          onClick={() => api.moveKpi(index, index + 1)}
                          className="text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] disabled:opacity-30"
                        >
                          ▼
                        </button>
                      </div>
                      <span
                        className={cn(
                          "flex-1 truncate text-sm",
                          hidden
                            ? "text-[var(--color-ink-muted)] line-through"
                            : "text-[var(--color-ink)]",
                        )}
                      >
                        {kpi.name}
                      </span>
                      <button
                        type="button"
                        onClick={() => api.toggleKpi(id, !hidden)}
                        aria-label={hidden ? "Show KPI" : "Hide KPI"}
                        className="text-xs text-[var(--color-ink-secondary)] hover:text-[var(--color-ink)]"
                      >
                        {hidden ? "Show" : "Hide"}
                      </button>
                    </div>
                    {!hidden ? (
                      <div className="mt-2 flex items-center gap-1.5">
                        <span className="text-[11px] text-[var(--color-ink-muted)]">
                          Format
                        </span>
                        <select
                          value={conf?.formatOverride ?? ""}
                          onChange={(event) =>
                            api.setKpiFormat(
                              id,
                              (event.target.value || null) as KpiFormatOverride | null,
                            )
                          }
                          className="rounded-md border border-[var(--color-hairline)] bg-[var(--color-surface)] px-1.5 py-0.5 text-xs text-[var(--color-ink)]"
                        >
                          <option value="">Default ({kpi.format})</option>
                          {KPI_FORMATS.map((f) => (
                            <option key={f.value} value={f.value}>
                              {f.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </Section>
        </div>

        <footer className="border-t border-[var(--color-hairline)] px-5 py-4">
          <Button
            variant="secondary"
            className="w-full"
            onClick={() => {
              if (
                window.confirm(
                  "Reset the dashboard to its original AI-generated configuration? Your customisations will be discarded.",
                )
              ) {
                api.reset();
              }
            }}
          >
            Reset to original
          </Button>
        </footer>
      </aside>
    </>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2.5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
          {title}
        </h3>
        {hint ? (
          <p className="text-[11px] text-[var(--color-ink-muted)]">{hint}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function OptionChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
          : "border-[var(--color-hairline)] text-[var(--color-ink-secondary)] hover:bg-[var(--color-plane)]",
      )}
    >
      {label}
    </button>
  );
}

/** color inputs need a concrete hex; fall back to the live computed token. */
function hexFor(stored: string | undefined, token: string): string {
  if (stored && /^#[0-9a-f]{6}$/i.test(stored)) return stored;
  if (typeof window !== "undefined") {
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue(token)
      .trim();
    if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  }
  return "#2a78d6";
}
