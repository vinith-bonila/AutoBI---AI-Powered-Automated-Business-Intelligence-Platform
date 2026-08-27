"use client";

/**
 * "Ask your data" chat panel.
 *
 * The user asks in natural language; the backend computes the answer
 * deterministically and (optionally) has the LLM phrase it. Each answer shows
 * the supporting metrics and, where relevant, a chart — so the user can see the
 * evidence behind the words. The model never invents a number.
 */

import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { AskResponse, FilterValue } from "@/types";
import { SeriesPalette } from "@/lib/theme";
import { formatCellValue } from "@/lib/format";
import { Badge, Spinner, cn } from "@/components/ui";
import { ChartRenderer } from "@/components/charts/ChartRenderer";

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  response?: AskResponse;
  error?: boolean;
}

const SUGGESTIONS = [
  "Which category has the highest value?",
  "What is the trend over time?",
  "What is the total?",
  "Show me the top 10.",
  "Which segment performs best?",
];

export function AskAiPanel({
  open,
  onClose,
  datasetId,
  filters,
  aiEnabled,
}: {
  open: boolean;
  onClose: () => void;
  datasetId: string;
  filters: FilterValue[];
  aiEnabled: boolean;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setInput("");
    const userMessage: Message = {
      id: `u_${Date.now()}`,
      role: "user",
      text: trimmed,
    };
    setMessages((prev) => [...prev, userMessage]);
    setBusy(true);

    try {
      const response = await api.ask(datasetId, trimmed, filters);
      setMessages((prev) => [
        ...prev,
        { id: `a_${Date.now()}`, role: "assistant", text: response.answer, response },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `a_${Date.now()}`,
          role: "assistant",
          text:
            err instanceof ApiError
              ? err.message
              : "I couldn't answer that. Try rephrasing the question.",
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {open ? (
        <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden="true" />
      ) : null}

      <aside
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full w-[440px] max-w-[95vw] flex-col border-l border-[var(--color-hairline)] bg-[var(--color-surface)] shadow-xl transition-transform duration-300",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between border-b border-[var(--color-hairline)] px-5 py-4">
          <div className="flex items-center gap-2">
            <span
              className="flex h-8 w-8 items-center justify-center rounded-lg text-white"
              style={{ backgroundColor: "var(--color-accent)" }}
              aria-hidden="true"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M12 3a9 9 0 0 0-9 9c0 1.6.4 3 1.2 4.3L3 21l4.7-1.2A9 9 0 1 0 12 3Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              </svg>
            </span>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-ink)]">
                Ask your data
              </h2>
              <p className="text-xs text-[var(--color-ink-muted)]">
                {aiEnabled ? "Answers are computed, then explained by AI" : "Computed answers with evidence"}
              </p>
            </div>
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

        <div ref={scrollRef} className="scroll-thin flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {messages.length === 0 ? (
            <div className="space-y-4">
              <p className="text-sm text-[var(--color-ink-secondary)]">
                Ask a question about this dataset. Every answer is calculated from
                your data — figures are never invented.
              </p>
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-[var(--color-ink-muted)]">
                  Try:
                </p>
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => ask(suggestion)}
                    className="block w-full rounded-lg border border-[var(--color-hairline)] px-3 py-2 text-left text-sm text-[var(--color-ink-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-ink)]"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) =>
              message.role === "user" ? (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-[var(--color-accent)] px-3.5 py-2 text-sm text-white">
                    {message.text}
                  </div>
                </div>
              ) : (
                <AssistantMessage key={message.id} message={message} />
              ),
            )
          )}
          {busy ? (
            <div className="flex items-center gap-2 text-sm text-[var(--color-ink-muted)]">
              <Spinner className="text-[var(--color-accent)]" /> Calculating…
            </div>
          ) : null}
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            ask(input);
          }}
          className="border-t border-[var(--color-hairline)] p-4"
        >
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  ask(input);
                }
              }}
              rows={1}
              placeholder="Ask a question…"
              className="scroll-thin max-h-28 flex-1 resize-none rounded-lg border border-[var(--color-hairline)] bg-[var(--color-plane)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none focus:border-[var(--color-accent)]"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              aria-label="Send"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-accent)] text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:opacity-40"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M4 12h15m0 0-6-6m6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}

function AssistantMessage({ message }: { message: Message }) {
  const response = message.response;
  const palette = useRef(new SeriesPalette()).current;

  return (
    <div className="space-y-2.5">
      <div
        className={cn(
          "max-w-[92%] rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-sm",
          message.error
            ? "bg-[color-mix(in_oklab,var(--color-critical)_10%,transparent)] text-[var(--color-critical)]"
            : "bg-[var(--color-plane)] text-[var(--color-ink)]",
        )}
      >
        {message.text}
        {response?.ai_used ? (
          <Badge tone="accent" className="ml-2 align-middle">
            AI
          </Badge>
        ) : null}
      </div>

      {response?.evidence?.length ? (
        <div className="ml-1 flex flex-wrap gap-1.5">
          {response.evidence.map((ev, index) => (
            <span
              key={`${ev.label}-${index}`}
              title={ev.detail ?? undefined}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-surface)] border border-[var(--color-hairline)] px-2 py-1 text-[11px]"
            >
              <span className="text-[var(--color-ink-muted)]">{ev.label}</span>
              <span className="tabular font-semibold text-[var(--color-ink)]">
                {ev.value}
              </span>
            </span>
          ))}
        </div>
      ) : null}

      {response?.chart && response.chart.data.row_count ? (
        <div className="ml-1 rounded-xl border border-[var(--color-hairline)] bg-[var(--color-surface)] p-3">
          <ChartRenderer
            spec={response.chart.chart}
            data={response.chart.data}
            palette={palette}
          />
        </div>
      ) : null}

      {response?.table?.length && !response.chart ? (
        <div className="scroll-thin ml-1 max-h-56 overflow-auto rounded-xl border border-[var(--color-hairline)]">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[var(--color-plane)]">
              <tr>
                {response.table_columns.map((col) => (
                  <th key={col} className="px-3 py-1.5 font-semibold text-[var(--color-ink-secondary)]">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {response.table.slice(0, 12).map((row, index) => (
                <tr key={index} className="border-t border-[var(--color-hairline)]">
                  {response.table_columns.map((col) => (
                    <td key={col} className="px-3 py-1.5 text-[var(--color-ink)]">
                      {formatCellValue(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
