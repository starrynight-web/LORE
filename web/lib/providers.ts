export const PROVIDERS = [
  { label: "Groq", value: "groq" },
  { label: "OpenRouter", value: "openrouter" },
  { label: "Gemini", value: "gemini" },
  { label: "OpenAI", value: "openai" },
  { label: "Anthropic", value: "anthropic" },
]

/** Defaults match lore/core/provider.py. A saved key replaces these with the live catalog. */
export const DEFAULT_MODELS: Record<string, string[]> = {
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
  openrouter: ["openai/gpt-4o-mini"],
  gemini: ["gemini-2.5-flash"],
  openai: ["gpt-4o-mini", "gpt-4.1-mini"],
  anthropic: ["claude-haiku-4-5"],
}

export function defaultModels(provider: string) {
  return DEFAULT_MODELS[provider] ?? DEFAULT_MODELS.groq
}
