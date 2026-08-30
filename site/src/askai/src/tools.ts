// AskAI's two tools (docs/PLAN.md §8): query_data runs read-only SQL against
// the in-browser DuckDB-Wasm instance; render_chart hands back a validated
// Vega-Lite spec for the UI to render. Both run entirely client-side — no
// server in the loop.

import { tool } from "ai";
import { z } from "zod";
import { runQuery, UnsafeQueryError } from "./duckdb";

export const queryDataTool = tool({
  description:
    "Run a single read-only SQL SELECT against the site's MA state legislative " +
    "election dataset (DuckDB syntax) and return the matching rows. Use this " +
    "to ground any factual claim in real data rather than guessing. See the " +
    "system prompt's schema card for table and column names. Only SELECT is " +
    "allowed — no DDL/DML, no multiple statements. Results are capped at 200 " +
    "rows; add your own ORDER BY/LIMIT to get the rows that matter most.",
  inputSchema: z.object({
    sql: z.string().describe("A single DuckDB SELECT statement."),
  }),
  execute: async ({ sql }) => {
    try {
      const rows = await runQuery(sql);
      return { rows };
    } catch (error) {
      if (error instanceof UnsafeQueryError) {
        return { error: `Query rejected: ${error.message}` };
      }
      return { error: `Query failed: ${error instanceof Error ? error.message : String(error)}` };
    }
  },
});

export const renderChartTool = tool({
  description:
    "Render a chart in the sidebar from data you already fetched with " +
    "query_data. spec must be a Vega-Lite v5 specification (as a JSON " +
    "string) with the data inlined via a top-level \"data\": {\"values\": [...]} " +
    "array — do not reference external files or URLs.",
  inputSchema: z.object({
    spec: z.string().describe('A Vega-Lite v5 chart spec, as a JSON string, with data inlined under "data.values".'),
  }),
  execute: async ({ spec }) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(spec);
    } catch {
      return { ok: false as const, error: "spec is not valid JSON." };
    }
    if (typeof parsed !== "object" || parsed === null) {
      return { ok: false as const, error: "spec must be a JSON object." };
    }
    return { ok: true as const };
  },
});

export const askAiTools = {
  query_data: queryDataTool,
  render_chart: renderChartTool,
};
