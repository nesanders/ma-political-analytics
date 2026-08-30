// Bundles the AskAI React app (docs/PLAN.md §8) into a single ES module
// consumed by site/_layouts/default.html. DuckDB-Wasm and the AI SDK
// provider packages stay external to *this* bundle only in the sense that
// their own wasm/worker assets are fetched from jsDelivr at runtime (see
// duckdb.ts) — their JS itself is bundled in normally.

import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.resolve(__dirname, "../../assets/js/askai.bundle.js");

await build({
  entryPoints: [path.join(__dirname, "src/main.tsx")],
  outfile,
  bundle: true,
  format: "esm",
  target: "es2020",
  minify: true,
  jsx: "automatic",
  define: {
    "process.env.NODE_ENV": '"production"',
  },
  loader: { ".ts": "ts", ".tsx": "tsx" },
});

console.log(`Built ${path.relative(process.cwd(), outfile)}`);
