"use client";

/**
 * Export menu.
 *
 * Data-level exports (cleaned CSV, Excel, config, semantic model, report,
 * data dictionary) are plain downloads from the backend. Image exports (PNG,
 * PDF) are rendered client-side from the live dashboard DOM so they capture
 * exactly what the user customised.
 */

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { DashboardConfig } from "@/lib/dashboardConfig";
import { Button, cn } from "@/components/ui";
import { exportDashboardImage, exportDashboardPdf } from "@/lib/exportImage";

interface ExportMenuProps {
  datasetId: string;
  config: DashboardConfig;
  captureRef: React.RefObject<HTMLElement | null>;
  title: string;
}

const DATA_EXPORTS: { kind: string; label: string; hint: string }[] = [
  { kind: "cleaned-csv", label: "Cleaned CSV", hint: "The transformed dataset" },
  { kind: "excel", label: "Excel workbook", hint: "KPIs, data, dictionary" },
  { kind: "report", label: "Analysis report", hint: "Markdown summary" },
  { kind: "data-dictionary", label: "Data dictionary", hint: "Columns & roles" },
  { kind: "semantic-model", label: "Semantic model", hint: "Power BI-ready JSON" },
];

export function ExportMenu({ datasetId, config, captureRef, title }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  function downloadData(kind: string) {
    // A hidden anchor triggers the browser's own download for the file the API
    // streams back with a Content-Disposition header.
    const link = document.createElement("a");
    link.href = api.exportUrl(datasetId, kind);
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setOpen(false);
  }

  function downloadConfig() {
    // The client config (theme, layout, ordering, custom charts) is the live
    // one, so it is serialised here rather than fetched from the server.
    const blob = new Blob([JSON.stringify(config, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${slug(title)}_dashboard_config.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setOpen(false);
  }

  async function downloadImage(kind: "png" | "pdf") {
    if (!captureRef.current) return;
    setBusy(kind);
    try {
      if (kind === "png") {
        await exportDashboardImage(captureRef.current, `${slug(title)}.png`);
      } else {
        await exportDashboardPdf(captureRef.current, `${slug(title)}.pdf`);
      }
    } catch (err) {
      console.error("Image export failed", err);
    } finally {
      setBusy(null);
      setOpen(false);
    }
  }

  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" onClick={() => setOpen((v) => !v)}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        Export
      </Button>

      {open ? (
        <div className="absolute right-0 top-full z-40 mt-1.5 w-64 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] p-1.5 shadow-lg">
          <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
            Dashboard
          </p>
          <ExportRow
            label="PNG image"
            hint="Snapshot of this view"
            busy={busy === "png"}
            onClick={() => downloadImage("png")}
          />
          <ExportRow
            label="PDF"
            hint="Printable dashboard"
            busy={busy === "pdf"}
            onClick={() => downloadImage("pdf")}
          />
          <ExportRow
            label="Dashboard config"
            hint="Reloadable JSON"
            onClick={downloadConfig}
          />

          <div className="my-1 h-px bg-[var(--color-hairline)]" />
          <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
            Data
          </p>
          {DATA_EXPORTS.map((item) => (
            <ExportRow
              key={item.kind}
              label={item.label}
              hint={item.hint}
              onClick={() => downloadData(item.kind)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ExportRow({
  label,
  hint,
  onClick,
  busy,
}: {
  label: string;
  hint: string;
  onClick: () => void;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-[var(--color-plane)] disabled:opacity-60",
      )}
    >
      <span>
        <span className="block text-sm text-[var(--color-ink)]">{label}</span>
        <span className="block text-[11px] text-[var(--color-ink-muted)]">{hint}</span>
      </span>
      {busy ? (
        <span className="text-[11px] text-[var(--color-ink-muted)]">…</span>
      ) : (
        <span className="text-[var(--color-ink-muted)]">↓</span>
      )}
    </button>
  );
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "dashboard";
}
