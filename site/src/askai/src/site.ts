// Reads the small amount of Jekyll-rendered context default.html stashes on
// <body> (see site/_layouts/default.html) so the bundled JS — which knows
// nothing about Jekyll's `baseurl`/page front-matter at build time — can
// still resolve site-relative asset URLs correctly and describe "the page
// the user is currently looking at" to the model.
//
// Guarded for `document` being undefined: this module is imported
// (transitively, via duckdb.ts) by scripts/verify_query_guard.mjs's Node-side
// bundle, which has no DOM.

export function getBaseUrl(): string {
  if (typeof document === "undefined") return "";
  return document.body?.dataset.askaiBaseurl ?? "";
}

export interface PageContext {
  title: string;
  description: string;
  path: string;
}

export function getPageContext(): PageContext {
  if (typeof document === "undefined") {
    return { title: "", description: "", path: "" };
  }
  return {
    title: document.body?.dataset.askaiPageTitle ?? document.title,
    description: document.body?.dataset.askaiPageDescription ?? "",
    path: window.location.pathname,
  };
}
