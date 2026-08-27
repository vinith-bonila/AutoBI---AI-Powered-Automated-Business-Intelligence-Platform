/**
 * Theme and colour-palette presets for the customization panel.
 *
 * Every categorical palette here is ordered so adjacent hues stay
 * distinguishable — the default "Corporate" set is the CVD-validated palette
 * from the data-visualisation guidelines. The presets are professional and
 * restrained by design (no random or clashing hues).
 *
 * A palette applies by writing CSS custom properties onto a root element, so
 * charts and cards update the instant the palette changes — the same tokens
 * the whole app already reads.
 */

export type ThemeMode = "light" | "dark" | "professional";

export interface Palette {
  id: string;
  name: string;
  /** Eight categorical series hues, fixed order. */
  series: [string, string, string, string, string, string, string, string];
  accent: string;
  accentHover: string;
  accentSoft: string;
}

/**
 * Surface/ink tokens for a theme mode. These are the same values the base
 * stylesheet ships; keeping them here lets the customizer swap the whole set.
 */
export interface Surfaces {
  plane: string;
  surface: string;
  ink: string;
  inkSecondary: string;
  inkMuted: string;
  grid: string;
  axis: string;
  hairline: string;
  /** Mode-dependent tokens charts read directly — must follow the SELECTED
   *  theme, not the OS, or a light card ends up with dark chart internals. */
  divergingNeutral: string;
  successText: string;
}

export const LIGHT_SURFACES: Surfaces = {
  plane: "#f9f9f7",
  surface: "#fcfcfb",
  ink: "#0b0b0b",
  inkSecondary: "#52514e",
  inkMuted: "#898781",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  hairline: "rgba(11,11,11,0.10)",
  divergingNeutral: "#eef0f2",
  successText: "#006300",
};

export const DARK_SURFACES: Surfaces = {
  plane: "#0d0d0d",
  surface: "#1a1a19",
  ink: "#ffffff",
  inkSecondary: "#c3c2b7",
  inkMuted: "#898781",
  grid: "#2c2c2a",
  axis: "#383835",
  hairline: "rgba(255,255,255,0.10)",
  divergingNeutral: "#383835",
  successText: "#0ca30c",
};

/** "Professional" is a light theme with a slightly cooler, calmer surface. */
export const PROFESSIONAL_SURFACES: Surfaces = {
  plane: "#f4f6f8",
  surface: "#ffffff",
  ink: "#111827",
  inkSecondary: "#4b5563",
  inkMuted: "#8a93a2",
  grid: "#e5e9ef",
  axis: "#cbd2db",
  hairline: "rgba(17,24,39,0.10)",
  divergingNeutral: "#eef1f5",
  successText: "#047857",
};

export const PALETTES: Palette[] = [
  {
    id: "corporate",
    name: "Corporate",
    // The CVD-validated default order.
    series: [
      "#2a78d6",
      "#eb6834",
      "#1baf7a",
      "#eda100",
      "#e87ba4",
      "#008300",
      "#4a3aa7",
      "#e34948",
    ],
    accent: "#1c5cab",
    accentHover: "#184f95",
    accentSoft: "#eaf2fd",
  },
  {
    id: "ocean",
    name: "Ocean",
    series: [
      "#0e7490",
      "#2563eb",
      "#0891b2",
      "#7c3aed",
      "#0d9488",
      "#4f46e5",
      "#0ea5e9",
      "#db2777",
    ],
    accent: "#0e7490",
    accentHover: "#0b5c73",
    accentSoft: "#e0f2fe",
  },
  {
    id: "forest",
    name: "Forest",
    series: [
      "#15803d",
      "#b45309",
      "#0f766e",
      "#4d7c0f",
      "#a16207",
      "#166534",
      "#065f46",
      "#9a3412",
    ],
    accent: "#15803d",
    accentHover: "#116632",
    accentSoft: "#dcfce7",
  },
  {
    id: "purple",
    name: "Purple",
    series: [
      "#7c3aed",
      "#db2777",
      "#4f46e5",
      "#c026d3",
      "#0891b2",
      "#9333ea",
      "#e11d48",
      "#2563eb",
    ],
    accent: "#7c3aed",
    accentHover: "#6d28d9",
    accentSoft: "#f3e8ff",
  },
  {
    id: "monochrome",
    name: "Monochrome",
    // A single-hue ordered ramp for people who want a restrained, slate look.
    series: [
      "#0f172a",
      "#334155",
      "#64748b",
      "#94a3b8",
      "#1e293b",
      "#475569",
      "#7c8ca0",
      "#cbd5e1",
    ],
    accent: "#334155",
    accentHover: "#1e293b",
    accentSoft: "#f1f5f9",
  },
  {
    id: "warm",
    name: "Warm",
    series: [
      "#dc2626",
      "#ea580c",
      "#d97706",
      "#b91c1c",
      "#c2410c",
      "#9a3412",
      "#e11d48",
      "#a16207",
    ],
    accent: "#c2410c",
    accentHover: "#9a3412",
    accentSoft: "#ffedd5",
  },
  {
    id: "cool",
    name: "Cool",
    series: [
      "#0891b2",
      "#4f46e5",
      "#0d9488",
      "#2563eb",
      "#0e7490",
      "#7c3aed",
      "#0ea5e9",
      "#6366f1",
    ],
    accent: "#0891b2",
    accentHover: "#0e7490",
    accentSoft: "#cffafe",
  },
];

export const PALETTE_BY_ID = new Map(PALETTES.map((p) => [p.id, p]));

export function surfacesForMode(mode: ThemeMode): Surfaces {
  if (mode === "dark") return DARK_SURFACES;
  if (mode === "professional") return PROFESSIONAL_SURFACES;
  return LIGHT_SURFACES;
}

/**
 * Write a palette + theme onto an element as CSS custom properties.
 *
 * Everything in the app reads these `--color-*` variables, so applying them
 * here restyles every card and chart at once. A `custom` override map lets the
 * "Custom" theme tweak individual tokens on top of the chosen preset.
 */
export function applyTheme(
  element: HTMLElement,
  {
    mode,
    palette,
    custom,
  }: {
    mode: ThemeMode;
    palette: Palette;
    custom?: Partial<Record<string, string>>;
  },
): void {
  const surfaces = surfacesForMode(mode);
  const set = (key: string, value: string) =>
    element.style.setProperty(key, value);

  // Stamp the theme on the document root so the base stylesheet's
  // `prefers-color-scheme` media block is disabled and the SELECTED theme wins
  // for every token — including ones charts read directly (diverging-neutral),
  // which would otherwise follow the OS and paint dark cells on a light card.
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute(
      "data-theme",
      mode === "dark" ? "dark" : "light",
    );
    document.documentElement.style.colorScheme = mode === "dark" ? "dark" : "light";
  }

  set("--color-plane", surfaces.plane);
  set("--color-surface", surfaces.surface);
  set("--color-ink", surfaces.ink);
  set("--color-ink-secondary", surfaces.inkSecondary);
  set("--color-ink-muted", surfaces.inkMuted);
  set("--color-grid", surfaces.grid);
  set("--color-axis", surfaces.axis);
  set("--color-hairline", surfaces.hairline);
  set("--color-diverging-neutral", surfaces.divergingNeutral);
  set("--color-success-text", surfaces.successText);

  palette.series.forEach((hex, index) => set(`--color-series-${index + 1}`, hex));
  set("--color-accent", palette.accent);
  set("--color-accent-hover", palette.accentHover);
  set("--color-accent-soft", palette.accentSoft);

  if (custom) {
    for (const [key, value] of Object.entries(custom)) {
      if (value) set(key, value);
    }
  }
}
