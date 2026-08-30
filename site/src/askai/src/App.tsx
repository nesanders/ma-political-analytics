// AskAI sidebar (docs/PLAN.md §8): a hidden, toggleable panel that runs a
// manual streamText()-driven tool-calling loop against whichever provider
// the user picks, with their own API key (BYOK, localStorage only).
//
// This deliberately does not use @ai-sdk/react's useChat — that hook's
// transport API has moved fast across recent `ai` versions, and hand-rolling
// the loop over streamText()'s own `fullStream` (verified against this
// session's installed `ai@7` type definitions, not assumed from possibly
// stale training knowledge) is a small, stable surface this app fully
// controls. See tools.ts for the two tools and duckdb.ts for the data layer;
// neither the LLM round-trip nor this UI has been exercised against a real
// provider from this session (no API key, and this session's network policy
// doesn't reach any provider's API host) — see docs/PLAN.md's roadmap table
// for what's verified vs. not.

import { useCallback, useEffect, useRef, useState } from "react";
import { streamText, stepCountIs, type ModelMessage } from "ai";
import { PROVIDERS, getModel, getProviderInfo, type ProviderId } from "./providers";
import { askAiTools } from "./tools";
import { getBaseUrl, getPageContext } from "./site";
import { getItem, setItem } from "./storage";

interface ToolEvent {
  toolCallId: string;
  toolName: string;
  input: unknown;
  output?: unknown;
}

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolEvents: ToolEvent[];
}

interface SchemaCard {
  description: string;
  tables: Record<string, unknown>;
  example_queries: Array<{ question: string; sql: string }>;
}

function makeId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function buildSystemPrompt(schema: SchemaCard | null): string {
  const page = getPageContext();
  const parts = [
    "You are AskAI, an assistant embedded in a Massachusetts state legislative " +
      "election-data site (House and Senate races). Ground every factual claim " +
      "in real data: call query_data to run SQL against the dataset rather than " +
      "estimating or recalling numbers from memory. Use render_chart to " +
      "visualize a result when a chart would help, built only from data you " +
      "already queried. Be concise, and mention specific figures you retrieved.",
    `The user is currently viewing: "${page.title}" (${page.path}).` +
      (page.description ? ` ${page.description}` : ""),
  ];
  parts.push(schema ? `Dataset schema:\n${JSON.stringify(schema)}` : "Dataset schema card failed to load.");
  return parts.join("\n\n");
}

function ResultTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) return <p className="askai-muted">No rows returned.</p>;
  const columns = Object.keys(rows[0]);
  const shown = rows.slice(0, 50);
  return (
    <div className="askai-table-wrap">
      <table className="askai-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{row[c] === null || row[c] === undefined ? "" : String(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <p className="askai-muted">Showing {shown.length} of {rows.length} rows.</p>
      )}
    </div>
  );
}

function ChartView({ spec }: { spec: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(spec);
    } catch {
      return;
    }
    const vegaEmbed = (window as unknown as { vegaEmbed?: (el: Element, spec: unknown, opts?: unknown) => Promise<unknown> }).vegaEmbed;
    if (typeof vegaEmbed !== "function") return;
    vegaEmbed(ref.current, parsed, { actions: false }).catch((e: unknown) => {
      console.error("AskAI chart render failed:", e);
    });
  }, [spec]);
  return <div className="askai-chart" ref={ref} />;
}

function ToolEventView({ event }: { event: ToolEvent }) {
  const output = event.output as
    | { rows?: Array<Record<string, unknown>>; error?: string; ok?: boolean }
    | undefined;

  if (event.toolName === "query_data") {
    const sql = (event.input as { sql?: string } | undefined)?.sql;
    return (
      <div className="askai-tool-event">
        {sql && <pre className="askai-sql">{sql}</pre>}
        {!output ? (
          <p className="askai-muted">Running query…</p>
        ) : output.error ? (
          <p className="askai-error">{output.error}</p>
        ) : (
          <ResultTable rows={output.rows ?? []} />
        )}
      </div>
    );
  }
  if (event.toolName === "render_chart") {
    const spec = (event.input as { spec?: string } | undefined)?.spec ?? "{}";
    return (
      <div className="askai-tool-event">
        {!output ? (
          <p className="askai-muted">Building chart…</p>
        ) : output.ok ? (
          <ChartView spec={spec} />
        ) : (
          <p className="askai-error">{output.error}</p>
        )}
      </div>
    );
  }
  return null;
}

function MessageView({ message }: { message: DisplayMessage }) {
  return (
    <div className={`askai-message askai-message-${message.role}`}>
      {message.text && <p className="askai-message-text">{message.text}</p>}
      {message.toolEvents.map((event) => (
        <ToolEventView key={event.toolCallId} event={event} />
      ))}
    </div>
  );
}

export default function App() {
  const [open, setOpen] = useState(() => getItem("askai:open") === "1");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [provider, setProviderState] = useState<ProviderId>(
    () => (getItem("askai:provider") as ProviderId | null) ?? "anthropic"
  );
  const [apiKey, setApiKeyState] = useState(() => getItem(`askai:apiKey:${provider}`) ?? "");
  const [modelId, setModelIdState] = useState(
    () => getItem(`askai:model:${provider}`) ?? getProviderInfo(provider).defaultModel
  );
  const [schema, setSchema] = useState<SchemaCard | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<"idle" | "streaming">("idle");
  const [error, setError] = useState<string | null>(null);

  const historyRef = useRef<ModelMessage[]>([]);

  useEffect(() => {
    fetch(`${getBaseUrl()}/assets/data/schema.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: SchemaCard) => setSchema(data))
      .catch((e) => console.error("AskAI: failed to load schema.json", e));
  }, []);

  const toggleOpen = useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      setItem("askai:open", next ? "1" : "0");
      return next;
    });
  }, []);

  const changeProvider = useCallback((next: ProviderId) => {
    setProviderState(next);
    setItem("askai:provider", next);
    setApiKeyState(getItem(`askai:apiKey:${next}`) ?? "");
    setModelIdState(getItem(`askai:model:${next}`) ?? getProviderInfo(next).defaultModel);
  }, []);

  const changeApiKey = useCallback(
    (next: string) => {
      setApiKeyState(next);
      setItem(`askai:apiKey:${provider}`, next);
    },
    [provider]
  );

  const changeModelId = useCallback(
    (next: string) => {
      setModelIdState(next);
      setItem(`askai:model:${provider}`, next);
    },
    [provider]
  );

  const updateAssistant = useCallback((id: string, update: (msg: DisplayMessage) => DisplayMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? update(m) : m)));
  }, []);

  const clearChat = useCallback(() => {
    setMessages([]);
    historyRef.current = [];
    setError(null);
  }, []);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || status === "streaming") return;
    if (!apiKey.trim()) {
      setError("Add an API key in Settings before chatting.");
      setSettingsOpen(true);
      return;
    }

    setInput("");
    setError(null);
    setStatus("streaming");

    setMessages((prev) => [...prev, { id: makeId(), role: "user", text, toolEvents: [] }]);
    historyRef.current = [...historyRef.current, { role: "user", content: text }];

    const assistantId = makeId();
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", text: "", toolEvents: [] }]);

    try {
      const model = getModel(provider, apiKey, modelId);
      const result = streamText({
        model,
        system: buildSystemPrompt(schema),
        messages: historyRef.current,
        tools: askAiTools,
        stopWhen: stepCountIs(6),
      });

      for await (const part of result.fullStream) {
        if (part.type === "text-delta") {
          updateAssistant(assistantId, (m) => ({ ...m, text: m.text + part.text }));
        } else if (part.type === "tool-call") {
          updateAssistant(assistantId, (m) => ({
            ...m,
            toolEvents: [...m.toolEvents, { toolCallId: part.toolCallId, toolName: part.toolName, input: part.input }],
          }));
        } else if (part.type === "tool-result") {
          updateAssistant(assistantId, (m) => ({
            ...m,
            toolEvents: m.toolEvents.map((ev) => (ev.toolCallId === part.toolCallId ? { ...ev, output: part.output } : ev)),
          }));
        } else if (part.type === "tool-error") {
          updateAssistant(assistantId, (m) => ({
            ...m,
            toolEvents: m.toolEvents.map((ev) =>
              ev.toolCallId === part.toolCallId ? { ...ev, output: { error: describeError(part.error) } } : ev
            ),
          }));
        } else if (part.type === "error") {
          setError(describeError(part.error));
        }
      }

      const responseMessages = await result.responseMessages;
      historyRef.current = [...historyRef.current, ...responseMessages];
    } catch (e) {
      setError(describeError(e));
    } finally {
      setStatus("idle");
    }
  }, [input, status, apiKey, provider, modelId, schema, updateAssistant]);

  return (
    <>
      {!open && (
        <button type="button" className="askai-toggle" onClick={toggleOpen} aria-expanded={open}>
          Ask AI
        </button>
      )}
      {open && (
        <aside className="askai-panel" aria-label="AskAI assistant">
          <div className="askai-panel-header">
            <h2>AskAI</h2>
            <div className="askai-panel-header-actions">
              <button type="button" className="askai-link-button" onClick={() => setSettingsOpen((s) => !s)}>
                {settingsOpen ? "Hide settings" : "Settings"}
              </button>
              <button type="button" className="askai-link-button" onClick={clearChat}>
                New chat
              </button>
              <button type="button" className="askai-link-button" onClick={toggleOpen} aria-expanded={open}>
                Close
              </button>
            </div>
          </div>

          {settingsOpen && (
            <div className="askai-settings">
              <label>
                Provider
                <select value={provider} onChange={(e) => changeProvider(e.target.value as ProviderId)}>
                  {PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Model
                <input type="text" value={modelId} onChange={(e) => changeModelId(e.target.value)} />
              </label>
              <label>
                API key
                <input
                  type="password"
                  value={apiKey}
                  placeholder={getProviderInfo(provider).keyPlaceholder}
                  onChange={(e) => changeApiKey(e.target.value)}
                />
              </label>
              <p className="askai-muted">
                Stored only in this browser's localStorage. Requests go directly from your browser to{" "}
                {getProviderInfo(provider).label} — this site never sees your key or your questions.{" "}
                <a href={getProviderInfo(provider).keyHelpUrl} target="_blank" rel="noreferrer">
                  Get a key
                </a>
                .
              </p>
            </div>
          )}

          <div className="askai-messages">
            {messages.length === 0 && (
              <p className="askai-muted">
                Ask about MA House/Senate races — e.g. "Which Senate seats are competitive?" or "Who overperformed
                their district's lean in 2022?"
              </p>
            )}
            {messages.map((m) => (
              <MessageView key={m.id} message={m} />
            ))}
            {error && <p className="askai-error">{error}</p>}
          </div>

          <form
            className="askai-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              void handleSend();
            }}
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question…"
              disabled={status === "streaming"}
            />
            <button type="submit" disabled={status === "streaming" || !input.trim()}>
              {status === "streaming" ? "…" : "Send"}
            </button>
          </form>
        </aside>
      )}
    </>
  );
}
