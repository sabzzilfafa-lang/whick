import { Song } from "../api";

export type SongWorkflowStep = "lyrics_ko" | "lyrics_en" | "instruments" | "prompt";

export interface WorkflowStepInfo {
  id: SongWorkflowStep;
  label: string;
  done: boolean;
  active: boolean;
}

function hasKo(song: Song): boolean {
  return Boolean((song.lyrics_ko || song.lyrics || "").trim());
}

function hasEn(song: Song): boolean {
  return Boolean((song.lyrics_en || "").trim());
}

function hasInstruments(song: Song): boolean {
  return Boolean(song.instrument_settings?.trim());
}

function hasPrompt(song: Song): boolean {
  return Boolean(song.suno_prompt?.trim());
}

export function getSongWorkflowSteps(song: Song): WorkflowStepInfo[] {
  const ko = hasKo(song);
  const en = hasEn(song);
  const inst = hasInstruments(song);
  const prompt = hasPrompt(song);

  let active: SongWorkflowStep = "lyrics_ko";
  if (ko && !en) active = "lyrics_en";
  else if (ko && en && !inst) active = "instruments";
  else if (ko && en && inst && !prompt) active = "prompt";
  else if (prompt) active = "prompt";

  return [
    { id: "lyrics_ko", label: "가사 (한글)", done: ko, active: active === "lyrics_ko" },
    { id: "lyrics_en", label: "가사 (영어)", done: en, active: active === "lyrics_en" },
    { id: "instruments", label: "악기 세팅", done: inst, active: active === "instruments" },
    { id: "prompt", label: "Suno 프롬프트", done: prompt, active: active === "prompt" },
  ];
}

export function currentWorkflowStep(song: Song): SongWorkflowStep {
  return getSongWorkflowSteps(song).find((s) => s.active)?.id ?? "lyrics_ko";
}
