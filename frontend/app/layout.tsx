import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import Link from "next/link";

export const metadata: Metadata = {
  title: "AutoBI — Turn any CSV into an intelligent dashboard",
  description:
    "Upload a CSV and AutoBI automatically profiles, cleans, analyses and visualises it into an interactive business intelligence dashboard.",
};

// Proper mobile scaling; `viewport-fit=cover` respects notch safe-areas.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#1c5cab",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-40 border-b border-[var(--color-hairline)] bg-[color-mix(in_oklab,var(--color-plane)_88%,transparent)] backdrop-blur">
            <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-4 sm:px-6">
              <Link href="/" className="flex items-center gap-2.5">
                <LogoMark />
                <span className="text-base font-semibold tracking-tight text-[var(--color-ink)]">
                  AutoBI
                </span>
              </Link>
              <div className="flex items-center gap-2">
                <Link
                  href="/"
                  className="rounded-lg px-3 py-1.5 text-sm text-[var(--color-ink-secondary)] transition-colors hover:bg-[var(--color-surface)] hover:text-[var(--color-ink)]"
                >
                  New analysis
                </Link>
                <ThemeToggle />
              </div>
            </div>
          </header>

          <main className="flex-1">{children}</main>

          <footer className="border-t border-[var(--color-hairline)] py-6">
            <div className="mx-auto max-w-[1400px] px-4 text-xs text-[var(--color-ink-muted)] sm:px-6">
              AutoBI — deterministic analysis, optional AI narration. Your data
              stays on the server; nothing is sent to an AI provider unless one
              is configured.
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}

function LogoMark() {
  return (
    <span
      className="flex h-7 w-7 items-center justify-center rounded-lg"
      style={{ backgroundColor: "var(--color-accent)" }}
      aria-hidden="true"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
        <path
          d="M4 20V10m5 10V4m5 16v-7m5 7V8"
          stroke="white"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}
