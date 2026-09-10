import { AIModelOption, AIProvider } from "../api";

/** 가성비 권장 모델 (OpenRouter) */
export const VALUE_MODELS: Record<string, string> = {
  lyrics: "~deepseek/deepseek-v4-flash-latest",
  prompt: "google/gemini-2.5-flash-lite",
  instruments: "google/gemini-2.5-flash-lite",
  analyze: "deepseek/deepseek-v3.2",
};

/** 가성비 권장 창의성(Temperature) */
export const VALUE_TEMPERATURES: Record<string, string> = {
  lyrics: "0.8",
  prompt: "0.5",
  instruments: "0.4",
  analyze: "0.6",
};

/** API 실패 시 사용하는 기본 모델 목록 */
export const STATIC_MODELS: Record<string, AIModelOption[]> = {
  openrouter: [
    { id: VALUE_MODELS.lyrics, name: "DeepSeek V4 Flash Latest" },
    { id: VALUE_MODELS.prompt, name: "Gemini 2.5 Flash Lite" },
    { id: VALUE_MODELS.instruments, name: "Gemini 2.5 Flash Lite" },
    { id: VALUE_MODELS.analyze, name: "DeepSeek V3.2" },
    { id: "qwen/qwen3.7-flash", name: "Qwen 3.7 Flash" },
    { id: "xiaomi/mimo-v2.5", name: "MiMo V2.5" },
    { id: "deepseek/deepseek-v4-flash", name: "DeepSeek V4 Flash" },
    { id: "google/gemini-3.7-flash", name: "Gemini 3.7 Flash" },
  ],
  openai: [
    { id: "gpt-4o-mini", name: "GPT-4o Mini" },
    { id: "gpt-4o", name: "GPT-4o" },
    { id: "gpt-5.4-mini", name: "GPT-5.4 Mini" },
    { id: "gpt-5.5", name: "GPT-5.5" },
  ],
  anthropic: [
    { id: "claude-sonnet-4-20250514", name: "Claude Sonnet 4" },
    { id: "claude-3-5-sonnet-20241022", name: "Claude 3.5 Sonnet" },
    { id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku" },
  ],
  google: [
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash" },
    { id: "gemini-2.5-flash-lite", name: "Gemini 2.5 Flash Lite" },
    { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro" },
  ],
};

export function getFallbackModels(provider: AIProvider | undefined, providerId: string): AIModelOption[] {
  if (provider?.recommended_models?.length) {
    return provider.recommended_models;
  }
  if (provider?.default_models) {
    const seen = new Set<string>();
    const fromDefaults: AIModelOption[] = [];
    for (const id of Object.values(provider.default_models)) {
      if (!id || seen.has(id)) continue;
      seen.add(id);
      fromDefaults.push({ id, name: id });
    }
    if (fromDefaults.length) return fromDefaults;
  }
  return STATIC_MODELS[providerId] || [];
}

export function mergeModels(
  models: AIModelOption[],
  currentValue: string,
): AIModelOption[] {
  if (!currentValue || models.some((m) => m.id === currentValue)) {
    return models;
  }
  return [{ id: currentValue, name: `${currentValue} (current)` }, ...models];
}
