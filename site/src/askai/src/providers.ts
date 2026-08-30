// Per-provider model factories for AskAI's BYOK setup (docs/PLAN.md §8).
//
// Each @ai-sdk/* adapter exposes the same LanguageModel interface, so this
// file is the entire "abstraction layer" — no hand-rolled per-provider
// request shapes needed, per the plan's design decision.
//
// CORS/browser-access caveat (from the plan, still true — this session has
// no API keys and its network policy doesn't reach any of these providers'
// API hosts, so none of this has been exercised against a real endpoint):
// Anthropic requires the `anthropic-dangerous-direct-browser-access` header
// on direct-from-browser calls, set below. OpenAI, Google, and Groq are
// expected to allow direct browser calls without a special header (each
// adapter here just uses fetch(), not a Node-only SDK), but that is an
// assumption carried over from the plan, not something verified live from
// this environment — if a provider's API rejects browser-origin requests in
// practice, the fix is on that provider's adapter config here, not in the
// chat loop that calls getModel().

import { createAnthropic } from "@ai-sdk/anthropic";
import { createOpenAI } from "@ai-sdk/openai";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createGroq } from "@ai-sdk/groq";
import type { LanguageModel } from "ai";

export type ProviderId = "anthropic" | "openai" | "google" | "groq";

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  defaultModel: string;
  keyPlaceholder: string;
  keyHelpUrl: string;
}

export const PROVIDERS: ProviderInfo[] = [
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    defaultModel: "claude-sonnet-4-5",
    keyPlaceholder: "sk-ant-...",
    keyHelpUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "openai",
    label: "OpenAI",
    defaultModel: "gpt-4o-mini",
    keyPlaceholder: "sk-...",
    keyHelpUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "google",
    label: "Google (Gemini)",
    defaultModel: "gemini-2.0-flash",
    keyPlaceholder: "AIza...",
    keyHelpUrl: "https://aistudio.google.com/apikey",
  },
  {
    id: "groq",
    label: "Groq",
    defaultModel: "llama-3.3-70b-versatile",
    keyPlaceholder: "gsk_...",
    keyHelpUrl: "https://console.groq.com/keys",
  },
];

export function getProviderInfo(id: ProviderId): ProviderInfo {
  const info = PROVIDERS.find((p) => p.id === id);
  if (!info) throw new Error(`Unknown provider: ${id}`);
  return info;
}

export function getModel(providerId: ProviderId, apiKey: string, modelId: string): LanguageModel {
  switch (providerId) {
    case "anthropic":
      return createAnthropic({
        apiKey,
        headers: { "anthropic-dangerous-direct-browser-access": "true" },
      })(modelId);
    case "openai":
      return createOpenAI({ apiKey })(modelId);
    case "google":
      return createGoogleGenerativeAI({ apiKey })(modelId);
    case "groq":
      return createGroq({ apiKey })(modelId);
    default: {
      const exhaustive: never = providerId;
      throw new Error(`Unknown provider: ${exhaustive}`);
    }
  }
}
