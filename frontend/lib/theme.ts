/**
 * Chart colour assignment.
 *
 * Two rules from the visualisation guidelines drive everything here:
 *
 *  1. **Fixed order, never cycled.** The eight categorical slots are ordered so
 *     that adjacent pairs clear the CVD separation gate. A ninth series is not
 *     a new colour — it folds into "Other".
 *
 *  2. **Colour follows the entity, never its rank.** `SeriesPalette` remembers
 *     which slot a label was given, so filtering a dashboard cannot repaint the
 *     series that survive.
 */

export const SERIES_COLORS = [
  "var(--color-series-1)",
  "var(--color-series-2)",
  "var(--color-series-3)",
  "var(--color-series-4)",
  "var(--color-series-5)",
  "var(--color-series-6)",
  "var(--color-series-7)",
  "var(--color-series-8)",
] as const;

export const MAX_SERIES = SERIES_COLORS.length;

/** Forms that put every pair on screen at once cap at three validated slots. */
export const MAX_ALL_PAIRS_SERIES = 3;

export const OTHER_LABEL = "Other";
export const OTHER_COLOR = "var(--color-ink-muted)";

export const CHART_INK = {
  primary: "var(--color-ink)",
  secondary: "var(--color-ink-secondary)",
  muted: "var(--color-ink-muted)",
  grid: "var(--color-grid)",
  axis: "var(--color-axis)",
  surface: "var(--color-surface)",
} as const;

/**
 * A stable label -> colour map for one chart.
 *
 * Slots are handed out in first-seen order and never reassigned, so a series
 * keeps its colour across filter changes even when its rank moves.
 */
export class SeriesPalette {
  private readonly assigned = new Map<string, string>();
  private next = 0;

  constructor(initial: string[] = []) {
    this.register(initial);
  }

  register(labels: string[]): void {
    for (const label of labels) {
      if (this.assigned.has(label) || label === OTHER_LABEL) continue;
      if (this.next >= MAX_SERIES) {
        // Past the eighth slot, everything shares the "Other" treatment
        // rather than inventing a ninth hue.
        this.assigned.set(label, OTHER_COLOR);
        continue;
      }
      this.assigned.set(label, SERIES_COLORS[this.next]);
      this.next += 1;
    }
  }

  get(label: string): string {
    if (label === OTHER_LABEL) return OTHER_COLOR;
    const existing = this.assigned.get(label);
    if (existing) return existing;
    this.register([label]);
    return this.assigned.get(label) ?? OTHER_COLOR;
  }

  entries(): [string, string][] {
    return [...this.assigned.entries()];
  }
}

/**
 * Diverging scale for correlation cells (-1 .. +1).
 *
 * Two opposed hues with a neutral grey midpoint: a value near zero must read as
 * "nothing here", which a rainbow or a single-hue ramp cannot express.
 */
export function correlationColor(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "var(--color-diverging-neutral)";
  }
  const magnitude = Math.min(Math.abs(value), 1);
  if (magnitude < 0.05) return "var(--color-diverging-neutral)";
  const pole =
    value > 0
      ? "var(--color-diverging-positive)"
      : "var(--color-diverging-negative)";
  // `color-mix` keeps the ramp anchored to the same two poles in both themes.
  return `color-mix(in oklab, ${pole} ${Math.round(magnitude * 100)}%, var(--color-diverging-neutral))`;
}

/** Correlation cells carry a readable number, so ink must clear the fill. */
export function correlationTextColor(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "var(--color-ink-secondary)";
  }
  return Math.abs(value) > 0.55 ? "#ffffff" : "var(--color-ink)";
}

/** Sequential ramp for histogram bars — one hue, light to dark. */
export function sequentialColor(ratio: number): string {
  const clamped = Math.max(0, Math.min(1, ratio));
  return `color-mix(in oklab, var(--color-seq-550) ${Math.round(
    30 + clamped * 70,
  )}%, var(--color-seq-100))`;
}

/**
 * Palette-aware gradient for a RANKED bar chart (one measure, sorted).
 *
 * The highest bar shows the series-1 hue at full strength; lower bars fade
 * toward the card surface, so magnitude reads as depth of colour — a far
 * cleaner look than one flat colour, and it tracks whatever palette is active
 * (monochrome → navy gradient, corporate → blue gradient, etc.).
 *
 * `ratio` is value ÷ max, in [0, 1].
 */
export function rankedBarColor(ratio: number): string {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(ratio) ? ratio : 0));
  // Keep even the smallest bar visible (floor at 42% strength).
  const strength = Math.round(42 + clamped * 58);
  return `color-mix(in oklab, var(--color-series-1) ${strength}%, var(--color-surface))`;
}

export const STATUS_COLORS = {
  positive: "var(--color-good)",
  neutral: "var(--color-ink-muted)",
  warning: "var(--color-warning)",
  critical: "var(--color-critical)",
} as const;

/** Shared geometry so every chart uses the same mark weights. */
export const MARKS = {
  lineWidth: 2,
  dotRadius: 4,
  activeDotRadius: 6,
  barRadius: 4,
  barGap: 2,
  // Larger, ringed dots so a dense scatter is actually legible.
  scatterSize: 130,
  scatterOpacity: 0.6,
  gridOpacity: 1,
} as const;
