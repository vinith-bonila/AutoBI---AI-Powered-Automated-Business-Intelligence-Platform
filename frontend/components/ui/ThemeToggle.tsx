"use client";

/**
 * Light/dark toggle.
 *
 * Dark mode is a *selected* palette, so the toggle stamps `data-theme` on the
 * root element (which both the CSS media-query guard and the explicit scope
 * respect) and remembers the choice.
 *
 * The icon reflects the *resolved* appearance, but that resolution reads
 * `matchMedia`, which is not available on the server. To avoid a hydration
 * mismatch the button renders a stable placeholder until it has mounted, and
 * only then reads the real appearance — so server and first client render
 * always agree.
 */

import { useEffect, useState } from "react";

type Theme = "light" | "dark" | null;

export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const stored = document.documentElement.getAttribute("data-theme") as Theme;
    const systemDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;
    setIsDark(stored === "dark" || (stored === null && systemDark));
    setMounted(true);
  }, []);

  function toggle() {
    const next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("autobi-theme", next);
    } catch {
      // Storage may be unavailable (private mode); the toggle still works for
      // the current session.
    }
    setIsDark(!isDark);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={
        mounted
          ? `Switch to ${isDark ? "light" : "dark"} mode`
          : "Toggle colour theme"
      }
      className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-hairline)] text-[var(--color-ink-secondary)] transition-colors hover:bg-[var(--color-surface)] hover:text-[var(--color-ink)]"
    >
      {/* Until mounted, render the moon so server and client markup match. */}
      {mounted && isDark ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
          <path
            d="M12 2v2m0 16v2M4 12H2m20 0h-2m-2.9-7.1-1.4 1.4M6.3 17.7l-1.4 1.4m0-14.2 1.4 1.4m11.4 11.4 1.4 1.4"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}
