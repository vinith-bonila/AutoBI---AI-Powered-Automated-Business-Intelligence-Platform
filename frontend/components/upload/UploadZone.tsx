"use client";

/**
 * The upload control: a drag-and-drop zone plus a file picker.
 *
 * Validation happens client-side first (extension, size) for a fast error, but
 * the backend re-validates everything — the browser check is a courtesy, not a
 * security boundary.
 */

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import type { AppConfig } from "@/types";
import { formatBytes } from "@/lib/format";
import { Button, Spinner, cn } from "@/components/ui";

interface UploadZoneProps {
  config: AppConfig | null;
}

export function UploadZone({ config }: UploadZoneProps) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const maxBytes = (config?.max_upload_mb ?? 100) * 1024 * 1024;
  const allowed = config?.allowed_extensions ?? [".csv", ".tsv", ".txt"];

  const validate = useCallback(
    (file: File): string | null => {
      const dot = file.name.lastIndexOf(".");
      const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
      if (!allowed.includes(ext)) {
        return `That looks like a ${ext || "?"} file. Please upload one of: ${allowed.join(", ")}.`;
      }
      if (file.size === 0) return "That file is empty.";
      if (file.size > maxBytes) {
        return `That file is ${formatBytes(file.size)}; the limit is ${config?.max_upload_mb ?? 100} MB.`;
      }
      return null;
    },
    [allowed, maxBytes, config?.max_upload_mb],
  );

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      const problem = validate(file);
      if (problem) {
        setError(problem);
        return;
      }

      setUploading(true);
      try {
        const response = await api.upload(file);
        router.push(`/analyze/${response.dataset_id}`);
      } catch (err) {
        setUploading(false);
        setError(
          err instanceof ApiError
            ? err.message
            : "The upload failed. Please try again.",
        );
      }
    },
    [router, validate],
  );

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void handleFile(file);
        }}
        aria-label="Upload a CSV file"
        aria-busy={uploading}
        className={cn(
          "group relative flex cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors",
          dragging
            ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
            : "border-[var(--color-axis)] bg-[var(--color-surface)] hover:border-[var(--color-accent)] hover:bg-[var(--color-plane)]",
          uploading && "pointer-events-none opacity-70",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={allowed.join(",")}
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleFile(file);
            event.target.value = "";
          }}
        />

        {uploading ? (
          <>
            <Spinner className="h-7 w-7 text-[var(--color-accent)]" />
            <p className="text-sm font-medium text-[var(--color-ink)]">
              Uploading…
            </p>
          </>
        ) : (
          <>
            <span
              className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--color-accent-soft)] text-[var(--color-accent)] transition-transform group-hover:scale-105"
              aria-hidden="true"
            >
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 16V4m0 0L7 9m5-5 5 5M4 17v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <div>
              <p className="text-base font-semibold text-[var(--color-ink)]">
                Drop a CSV here, or click to browse
              </p>
              <p className="mt-1 text-sm text-[var(--color-ink-secondary)]">
                {allowed.join(", ")} up to {config?.max_upload_mb ?? 100} MB
              </p>
            </div>
            <Button variant="primary" type="button" tabIndex={-1}>
              Choose file
            </Button>
          </>
        )}
      </div>

      {error ? (
        <p
          role="alert"
          className="mt-3 flex items-center gap-2 rounded-lg bg-[color-mix(in_oklab,var(--color-critical)_10%,transparent)] px-3 py-2 text-sm text-[var(--color-critical)]"
        >
          <span aria-hidden="true">!</span>
          {error}
        </p>
      ) : null}
    </div>
  );
}
