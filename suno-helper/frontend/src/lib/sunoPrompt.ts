export const SUNO_PROMPT_MAX_CHARS = 1000;

export function isValidSunoPromptLength(text: string | undefined | null): boolean {
  const len = text?.trim().length ?? 0;
  return len > 0 && len <= SUNO_PROMPT_MAX_CHARS;
}

export function isStructuredSunoPrompt(text: string): boolean {
  const cleaned = text.trim();
  if (cleaned.length < 120 || cleaned.length > SUNO_PROMPT_MAX_CHARS) return false;
  const markers = ["[Overview]", "[Intro]", "[Chorus", "[Outro", "[Verse"];
  return markers.filter((m) => cleaned.includes(m)).length >= 2;
}
