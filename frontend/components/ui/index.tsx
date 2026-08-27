/** Shared presentational primitives. */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { ReactNode } from "react";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// ---------------------------------------------------------------------------
// surfaces
// ---------------------------------------------------------------------------

export function Card({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[var(--color-hairline)] bg-[var(--color-surface)] shadow-[0_1px_2px_rgba(11,11,11,0.04)]",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function SectionHeading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-[var(--color-ink)]">
          {title}
        </h2>
        {description ? (
          <p className="mt-1 text-sm text-[var(--color-ink-secondary)]">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------------------
// badges & buttons
// ---------------------------------------------------------------------------

const BADGE_TONES = {
  neutral:
    "bg-[var(--color-plane)] text-[var(--color-ink-secondary)] border-[var(--color-hairline)]",
  accent:
    "bg-[var(--color-accent-soft)] text-[var(--color-accent)] border-transparent",
  positive: "bg-[color-mix(in_oklab,var(--color-good)_14%,transparent)] text-[var(--color-success-text)] border-transparent",
  warning:
    "bg-[color-mix(in_oklab,var(--color-warning)_18%,transparent)] text-[var(--color-ink)] border-transparent",
  critical:
    "bg-[color-mix(in_oklab,var(--color-critical)_14%,transparent)] text-[var(--color-critical)] border-transparent",
} as const;

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: keyof typeof BADGE_TONES;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const BUTTON_VARIANTS = {
  primary:
    "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] shadow-[0_1px_2px_rgba(11,11,11,0.12)]",
  secondary:
    "border border-[var(--color-hairline)] bg-[var(--color-surface)] text-[var(--color-ink)] hover:bg-[var(--color-plane)]",
  ghost:
    "text-[var(--color-ink-secondary)] hover:bg-[var(--color-plane)] hover:text-[var(--color-ink)]",
} as const;

export function Button({
  children,
  variant = "primary",
  className,
  ...rest
}: {
  children: ReactNode;
  variant?: keyof typeof BUTTON_VARIANTS;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// states
// ---------------------------------------------------------------------------

export function Skeleton({
  className,
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={cn("skeleton rounded-md", className)} style={style} />;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("h-4 w-4 animate-spin", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2.5"
        className="opacity-20"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      {icon ? (
        <div className="text-[var(--color-ink-muted)]">{icon}</div>
      ) : null}
      <p className="text-sm font-medium text-[var(--color-ink)]">{title}</p>
      {description ? (
        <p className="max-w-sm text-sm text-[var(--color-ink-secondary)]">
          {description}
        </p>
      ) : null}
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center"
    >
      <span
        aria-hidden="true"
        className="flex h-9 w-9 items-center justify-center rounded-full bg-[color-mix(in_oklab,var(--color-critical)_14%,transparent)] text-[var(--color-critical)]"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 8v5m0 3.5h.01M10.3 3.9 2.5 17.4A2 2 0 0 0 4.2 20.4h15.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <div>
        <p className="text-sm font-semibold text-[var(--color-ink)]">{title}</p>
        <p className="mt-1 max-w-md text-sm text-[var(--color-ink-secondary)]">
          {message}
        </p>
      </div>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// tooltip
// ---------------------------------------------------------------------------

/**
 * A hover/focus explainer. Uses the title attribute as the accessible
 * fallback so the content is reachable without a pointer.
 */
export function InfoTip({
  label,
  children,
}: {
  label: string;
  children?: ReactNode;
}) {
  return (
    <span className="group relative inline-flex items-center">
      <button
        type="button"
        aria-label={label}
        title={label}
        className="flex h-4 w-4 items-center justify-center rounded-full border border-[var(--color-hairline)] text-[10px] font-semibold text-[var(--color-ink-muted)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
      >
        ?
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 w-64 -translate-x-1/2 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-3 text-left text-xs leading-relaxed text-[var(--color-ink-secondary)] opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {children ?? label}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// misc
// ---------------------------------------------------------------------------

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--color-ink-muted)]">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold text-[var(--color-ink)]">
        {value}
      </p>
      {hint ? (
        <p className="mt-0.5 text-xs text-[var(--color-ink-secondary)]">{hint}</p>
      ) : null}
    </div>
  );
}

export function ProgressBar({
  value,
  tone = "accent",
  className,
}: {
  value: number;
  tone?: "accent" | "good" | "warning" | "critical";
  className?: string;
}) {
  const color = {
    accent: "var(--color-accent)",
    good: "var(--color-good)",
    warning: "var(--color-warning)",
    critical: "var(--color-critical)",
  }[tone];

  return (
    <div
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-grid)]",
        className,
      )}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full transition-[width] duration-500 ease-out"
        style={{ width: `${Math.max(0, Math.min(100, value))}%`, backgroundColor: color }}
      />
    </div>
  );
}
