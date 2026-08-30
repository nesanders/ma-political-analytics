// Verifies duckdb.ts's query-safety logic and the published data it
// queries, against the real DuckDB engine — not a browser, but not a
// re-implementation either.
//
// Two things are checked, both for real:
// 1. assertSafeSelect() — imported from the *actual* src/duckdb.ts via a
//    one-off esbuild bundle, so this exercises the exact shipped function,
//    not a hand-copied regex that could silently drift from it.
// 2. The DuckDB engine's real query behavior against the real published
//    site/assets/data/*.parquet files, via @duckdb/duckdb-wasm's Node
//    bindings (duckdb-node-blocking — same query engine build, a
//    Node-native embedding instead of the browser Worker+CDN path).
//
// What this does NOT verify: the browser-side bundle loading via
// getJsDelivrBundles() (this session's network policy blocks
// cdn.jsdelivr.net) or the React UI. See docs/PLAN.md / this script's
// caller in pipeline/README.md for what's still unverified and why.
//
// Part 2 specifically also needs one more network host this session's
// policy blocks: read_parquet() triggers DuckDB's extension autoloading,
// which fetches the parquet extension itself from extensions.duckdb.org (see
// src/duckdb.ts's top-of-file comment). That's a real, separate CDN
// dependency for production too, just one real end-user browsers can reach
// directly. In this sandbox it makes Part 2's queries fail with "Extension
// Autoloading Error" even though registerFileBuffer/read_parquet is
// otherwise exercised correctly up to that point — Part 1 (the actual
// security boundary) is unaffected and passes in full.

import { execSync } from "node:child_process";
import { readFileSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(projectRoot, "../../.."); // site/src/askai -> repo root
const dataDir = path.join(repoRoot, "site", "assets", "data");

// --- Part 1: bundle and import the real assertSafeSelect --------------
// Output has to live under projectRoot (not the OS tmpdir) so Node's
// module resolution can still find node_modules/@duckdb/duckdb-wasm when
// evaluating the bundle's top-level import of it.
const tmpDir = path.join(projectRoot, ".verify-tmp");
mkdirSync(tmpDir, { recursive: true });
const bundleOut = path.join(tmpDir, "duckdb-guard.mjs");
execSync(
  `npx esbuild ${path.join(projectRoot, "src/duckdb.ts")} --bundle --platform=neutral --format=esm ` +
    `--external:@duckdb/duckdb-wasm --outfile=${bundleOut}`,
  { cwd: projectRoot, stdio: "inherit" }
);
const { assertSafeSelect, UnsafeQueryError } = await import(bundleOut);

let failures = 0;
function check(label, fn) {
  try {
    fn();
    console.log(`  ok: ${label}`);
  } catch (e) {
    failures++;
    console.error(`  FAIL: ${label} — ${e.message}`);
  }
}

console.log("Part 1: assertSafeSelect (real shipped function)");
check("plain SELECT allowed", () => assertSafeSelect("SELECT * FROM seats"));
check("SELECT with WHERE/ORDER BY allowed", () =>
  assertSafeSelect("SELECT district_name FROM seats WHERE chamber = 'senate' ORDER BY lean_dem_share")
);
for (const bad of [
  "DROP TABLE seats",
  "DELETE FROM seats",
  "INSERT INTO seats VALUES (1)",
  "ATTACH 'evil.db'",
  "PRAGMA database_list",
  "SELECT * FROM seats; DROP TABLE seats",
  "COPY seats TO 'out.csv'",
  "CALL some_proc()",
  "INSTALL httpfs",
]) {
  check(`rejects: ${bad}`, () => {
    let threw = false;
    try {
      assertSafeSelect(bad);
    } catch (e) {
      threw = e instanceof UnsafeQueryError;
    }
    if (!threw) throw new Error("did not throw UnsafeQueryError");
  });
}

// --- Part 2: real DuckDB engine against the real published data -------
console.log("\nPart 2: real DuckDB engine (Node bindings) against real published data");
const duckdbNode = await import("@duckdb/duckdb-wasm/dist/duckdb-node-blocking.cjs");
const DUCKDB_DIST = path.join(projectRoot, "node_modules/@duckdb/duckdb-wasm/dist");
const bundles = {
  mvp: { mainModule: `${DUCKDB_DIST}/duckdb-mvp.wasm`, mainWorker: `${DUCKDB_DIST}/duckdb-node-mvp.worker.cjs` },
  eh: { mainModule: `${DUCKDB_DIST}/duckdb-eh.wasm`, mainWorker: `${DUCKDB_DIST}/duckdb-node-eh.worker.cjs` },
};
const bundle = await duckdbNode.selectBundle(bundles);
const logger = new duckdbNode.ConsoleLogger(duckdbNode.LogLevel.WARNING);
const db = await duckdbNode.createDuckDB(bundles, logger, duckdbNode.DEFAULT_RUNTIME ?? duckdbNode.NODE_RUNTIME);
await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
const conn = db.connect();

// DuckDB-Wasm's queries run against its own virtual filesystem (even in
// the Node build) — a raw host path in read_parquet() isn't visible to it.
// Register each file's bytes under a virtual name first (this is also
// exactly how the real browser code will need to work: fetch() the bytes,
// then registerFileBuffer, since a plain URL string in read_parquet() is
// the same category of mismatch there too).
for (const table of ["seats", "results", "towns"]) {
  const buf = readFileSync(path.join(dataDir, `${table}.parquet`));
  db.registerFileBuffer(`${table}.parquet`, new Uint8Array(buf));
  conn.query(`CREATE VIEW ${table} AS SELECT * FROM read_parquet('${table}.parquet')`);
}

const schema = JSON.parse(readFileSync(path.join(dataDir, "schema.json"), "utf8"));
for (const { question, sql } of schema.example_queries) {
  try {
    const result = conn.query(sql);
    const rows = result.toArray().map((r) => (typeof r.toJSON === "function" ? r.toJSON() : r));
    console.log(`  ok: "${question}" -> ${rows.length} rows`);
    if (rows.length === 0) {
      failures++;
      console.error(`  FAIL: "${question}" returned zero rows — expected real data`);
    }
  } catch (e) {
    failures++;
    console.error(`  FAIL: "${question}" — ${e.message}`);
  }
}

// Cross-check one figure against the already-verified Python/pandas value
// (pipeline/README.md: Jeffrey L. Raymond's 2022 House WAR = 0.6017).
const warCheck = conn.query(
  "SELECT war FROM results WHERE candidate_name = 'Jeffrey L. Raymond' AND chamber = 'house' AND year = 2022"
);
const warRow = warCheck.toArray()[0];
const warVal = warRow ? (typeof warRow.toJSON === "function" ? warRow.toJSON().war : warRow.war) : undefined;
check("Jeffrey L. Raymond WAR matches the already-verified value (0.6017)", () => {
  if (Math.abs(warVal - 0.6017) > 0.0001) {
    throw new Error(`got ${warVal}`);
  }
});

conn.disconnect();
await db.terminate();

console.log(failures === 0 ? "\nAll checks passed." : `\n${failures} check(s) FAILED.`);
rmSync(tmpDir, { recursive: true, force: true });
process.exit(failures === 0 ? 0 : 1);
