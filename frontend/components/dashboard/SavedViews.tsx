"use client";

/**
 * Save / load / share the current dashboard configuration.
 *
 * "Save view" persists the live `DashboardConfig` to the backend (Supabase
 * Postgres in production, local files in dev). Saved views can be reloaded onto
 * the same dataset, or their link copied to share. This is the front door to
 * the saved-dashboards table.
 */

import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { DashboardConfig } from "@/lib/dashboardConfig";
import type { DashboardConfigApi } from "@/lib/useDashboardConfig";
import type { SavedDashboardSummary } from "@/types";
import { Button, Spinner, cn } from "@/components/ui";

export function SavedViews({
  datasetId,
  cfg,
}: {
  datasetId: string;
  cfg: DashboardConfigApi;
}) {
  const [open, setOpen] = useState(false);
  const [views, setViews] = useState<SavedDashboardSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  function refresh() {
    setLoading(true);
    api
      .listDashboards(datasetId)
      .then(setViews)
      .catch(() => setViews([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (open) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function saveCurrent() {
    const name = window.prompt("Name this view:", "My dashboard view");
    if (!name?.trim()) return;
    setSaving(true);
    setNote(null);
    try {
      await api.saveDashboard(datasetId, name.trim(), cfg.config);
      setNote("Saved.");
      refresh();
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : "Could not save the view.");
    } finally {
      setSaving(false);
    }
  }

  async function loadView(id: string) {
    setNote(null);
    try {
      const record = await api.loadDashboard(id);
      cfg.loadConfig(record.config as unknown as DashboardConfig);
      setOpen(false);
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : "Could not load the view.");
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteDashboard(id);
      refresh();
    } catch {
      /* ignore */
    }
  }

  function share(id: string) {
    // A shareable link that opens this dataset with the saved view applied.
    const url = `${window.location.origin}/dashboard/${datasetId}?view=${id}`;
    navigator.clipboard?.writeText(url).then(
      () => setNote("Share link copied."),
      () => setNote(url),
    );
  }

  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" onClick={() => setOpen((v) => !v)}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
          <path
            d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z M8 3v5h7V3 M8 21v-7h8v7"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Save view
      </Button>

      {open ? (
        <div className="absolute right-0 top-full z-40 mt-1.5 w-72 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-1.5 shadow-lg">
          <button
            type="button"
            onClick={saveCurrent}
            disabled={saving}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-[var(--color-ink)] hover:bg-[var(--color-plane)]"
          >
            {saving ? <Spinner /> : <span className="text-[var(--color-accent)]">＋</span>}
            Save current view
          </button>

          <div className="my-1 h-px bg-[var(--color-hairline)]" />
          <p className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
            Saved views
          </p>

          {loading ? (
            <p className="px-2.5 py-2 text-xs text-[var(--color-ink-muted)]">Loading…</p>
          ) : views.length === 0 ? (
            <p className="px-2.5 py-2 text-xs text-[var(--color-ink-muted)]">
              No saved views yet.
            </p>
          ) : (
            <ul className="scroll-thin max-h-56 overflow-y-auto">
              {views.map((view) => (
                <li
                  key={view.id}
                  className="group flex items-center gap-1 rounded-md px-2.5 py-1.5 hover:bg-[var(--color-plane)]"
                >
                  <button
                    type="button"
                    onClick={() => loadView(view.id)}
                    className="flex-1 truncate text-left text-sm text-[var(--color-ink)]"
                    title={`Load "${view.name}"`}
                  >
                    {view.name}
                  </button>
                  <button
                    type="button"
                    onClick={() => share(view.id)}
                    aria-label="Copy share link"
                    title="Copy share link"
                    className="rounded p-1 text-[var(--color-ink-muted)] opacity-0 hover:text-[var(--color-accent)] group-hover:opacity-100"
                  >
                    ↗
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(view.id)}
                    aria-label="Delete view"
                    title="Delete"
                    className="rounded p-1 text-[var(--color-ink-muted)] opacity-0 hover:text-[var(--color-critical)] group-hover:opacity-100"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}

          {note ? (
            <p className="border-t border-[var(--color-hairline)] px-2.5 pt-1.5 text-[11px] text-[var(--color-ink-muted)]">
              {note}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
