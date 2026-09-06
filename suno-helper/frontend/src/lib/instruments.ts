import {
  InstrumentDetail,
  PromptBuilderTemplate,
  SongInstrumentItem,
  SongInstrumentSettings,
} from "../api";

export function builderToInstrumentSettings(
  template: PromptBuilderTemplate,
): SongInstrumentSettings {
  return {
    preset_name: template.name || "",
    mix_notes: template.musical_traits?.production_style || "",
    instruments: (template.instruments || []).map((item) => ({
      name: item.name,
      name_en: item.name_en || item.name,
      role: item.role || "texture",
      tone: item.tone || "",
      texture: item.texture || "",
      notes: item.notes || "",
      from_preset: true,
    })),
  };
}

export function isApiUnavailableError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const msg = err.message.toLowerCase();
  return (
    msg.includes("method not allowed") ||
    msg.includes("not found") ||
    msg.includes("404") ||
    msg.includes("405")
  );
}

export function instrumentItemsFromDetails(items: InstrumentDetail[]): SongInstrumentItem[] {
  return items.map((item) => ({
    name: item.name,
    name_en: item.name_en || item.name,
    role: item.role || "texture",
    tone: item.tone || "",
    texture: item.texture || "",
    notes: item.notes || "",
    from_preset: true,
  }));
}
