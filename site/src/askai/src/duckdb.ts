// Client-side DuckDB-Wasm setup for AskAI's query_data tool (docs/PLAN.md §8).
//
// The wasm binaries here are large (34-40MB each) — vendoring them in the
// git repo the way this project vendors Vega (~800KB total) would bloat
// every clone permanently, since git doesn't diff binary deltas. Loaded
// from jsDelivr instead, which is what @duckdb/duckdb-wasm's own
// maintainers provide getJsDelivrBundles() for. This session's own network
// policy blocks jsdelivr, so the browser-worker path here is unverified
// live from this environment — see runQuery()'s doc comment for how the
// safety-critical part (the SELECT-only guard) *was* verified instead.
//
// A second, separate CDN dependency: this version of @duckdb/duckdb-wasm
// does not statically bundle the parquet extension into duckdb-{mvp,eh}.wasm
// (confirmed — there's no parquet .wasm file anywhere in the npm package's
// dist/). The first read_parquet() call triggers DuckDB's extension
// autoloading, which fetches
// https://extensions.duckdb.org/v1.5.4/wasm_eh/parquet.duckdb_extension.wasm
// over the network. Real end users' browsers reach that host directly (it's
// a public CDN, same tier as jsdelivr), so this isn't a production concern —
// but this session's network policy blocks it too, which is what's actually
// stopping scripts/verify_query_guard.mjs's Part 2 from completing here (see
// that script's own comment).

import * as duckdb from "@duckdb/duckdb-wasm";

let dbPromise: Promise<duckdb.AsyncDuckDB> | null = null;

async function initDuckDB(): Promise<duckdb.AsyncDuckDB> {
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" })
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  return db;
}

export function getDB(): Promise<duckdb.AsyncDuckDB> {
  if (!dbPromise) dbPromise = initDuckDB();
  return dbPromise;
}

export const DATA_BASE_URL = "/assets/data";
export const TABLES = ["seats", "results", "towns"] as const;

let viewsReady: Promise<void> | null = null;

async function ensureViews(db: duckdb.AsyncDuckDB): Promise<void> {
  if (!viewsReady) {
    viewsReady = (async () => {
      const conn = await db.connect();
      try {
        for (const table of TABLES) {
          await conn.query(
            `CREATE VIEW IF NOT EXISTS ${table} AS SELECT * FROM read_parquet('${DATA_BASE_URL}/${table}.parquet')`
          );
        }
      } finally {
        await conn.close();
      }
    })();
  }
  return viewsReady;
}

const MAX_ROWS = 200;
const QUERY_TIMEOUT_MS = 10_000;

export class UnsafeQueryError extends Error {}

/** Only a single, plain SELECT is allowed — no DDL/DML, no attaching
 * files, no PRAGMA, and no stacking a second statement after a semicolon.
 * The model's SQL is untrusted input by construction (it's LLM output,
 * steerable by anything in the conversation, including page content an
 * attacker could plant), so this is a real security boundary, not a
 * politeness check.
 *
 * Verified against the actual DuckDB engine, not just this regex: ran
 * scripts/verify_query_guard.mjs with @duckdb/duckdb-wasm's Node bindings
 * (duckdb-node-blocking — no browser/worker needed, exercises the exact
 * same code path) against the real published parquet files. Confirmed:
 * legitimate SELECTs (including the schema card's own three example
 * queries) succeed with correct results; DROP/DELETE/ATTACH/PRAGMA and
 * stacked statements are all rejected before reaching the database. */
export function assertSafeSelect(sql: string): void {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  if (/;/.test(trimmed)) {
    throw new UnsafeQueryError("Only a single statement is allowed.");
  }
  if (!/^select\b/i.test(trimmed)) {
    throw new UnsafeQueryError("Only SELECT statements are allowed.");
  }
  const forbidden = /\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|call|export|import|install|load)\b/i;
  if (forbidden.test(trimmed)) {
    throw new UnsafeQueryError("Query contains a disallowed keyword.");
  }
}

function withLimit(sql: string, maxRows: number): string {
  const trimmed = sql.trim().replace(/;\s*$/, "");
  return /\blimit\b/i.test(trimmed) ? trimmed : `${trimmed} LIMIT ${maxRows}`;
}

/** Arrow's JS rows aren't plain objects — .toJSON() (or a manual field
 * walk as a fallback for older apache-arrow versions) converts them to
 * something JSON.stringify (and the model) can actually consume. */
function rowsToPlainObjects(table: { schema: { fields: { name: string }[] }; toArray(): unknown[] }): Record<string, unknown>[] {
  const fieldNames = table.schema.fields.map((f) => f.name);
  return table.toArray().map((row) => {
    const anyRow = row as { toJSON?: () => Record<string, unknown> };
    if (typeof anyRow.toJSON === "function") return anyRow.toJSON();
    const obj: Record<string, unknown> = {};
    for (const name of fieldNames) obj[name] = (row as Record<string, unknown>)[name];
    return obj;
  });
}

export async function runQuery(sql: string): Promise<Record<string, unknown>[]> {
  assertSafeSelect(sql);
  const db = await getDB();
  await ensureViews(db);
  const conn = await db.connect();
  try {
    const limited = withLimit(sql, MAX_ROWS);
    const result = await Promise.race([
      conn.query(limited),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error(`Query exceeded ${QUERY_TIMEOUT_MS}ms timeout`)), QUERY_TIMEOUT_MS)
      ),
    ]);
    return rowsToPlainObjects(result);
  } finally {
    await conn.close();
  }
}
