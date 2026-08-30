import { useMemo, useState } from "react";
import { SongInstrumentItem, SongInstrumentSettings } from "../api";

const ROLES: { id: string; label: string }[] = [
  { id: "lead", label: "리드" },
  { id: "rhythm", label: "리듬" },
  { id: "bass", label: "베이스" },
  { id: "harmony", label: "하모니" },
  { id: "texture", label: "텍스처" },
  { id: "effects", label: "효과" },
];

export function parseInstrumentSettings(raw?: string | null): SongInstrumentSettings | null {
  if (!raw?.trim()) return null;
  try {
    const data = JSON.parse(raw);
    if (Array.isArray(data.instruments)) {
      return {
        preset_name: data.preset_name || "",
        mix_notes: data.mix_notes || "",
        tempo_bpm:
          typeof data.tempo_bpm === "number"
            ? data.tempo_bpm
            : data.tempo_bpm != null && data.tempo_bpm !== ""
              ? Number(data.tempo_bpm)
              : null,
        instruments: data.instruments,
      };
    }
    const legacy: SongInstrumentItem[] = [];
    const map: Record<string, string> = {
      lead: "lead",
      rhythm: "rhythm",
      texture: "texture",
      effects: "effects",
    };
    for (const [key, role] of Object.entries(map)) {
      const val = data[key];
      if (!val) continue;
      const names = Array.isArray(val) ? val : [val];
      for (const name of names) {
        if (name) legacy.push({ name: String(name), role, from_preset: false });
      }
    }
    if (legacy.length) {
      return { preset_name: "", mix_notes: data.mix_notes || "", instruments: legacy };
    }
  } catch {
    return null;
  }
  return null;
}

export function serializeInstrumentSettings(data: SongInstrumentSettings): string {
  return JSON.stringify(data, null, 2);
}

interface Props {
  settings: SongInstrumentSettings;
  onChange: (next: SongInstrumentSettings) => void;
  presetName?: string;
}

export default function InstrumentEditor({ settings, onChange, presetName }: Props) {
  const [newName, setNewName] = useState("");

  const summary = useMemo(
    () => settings.instruments.map((i) => i.name).filter(Boolean).join(", "),
    [settings.instruments],
  );

  const addInstrument = () => {
    const name = newName.trim();
    if (!name) return;
    onChange({
      ...settings,
      instruments: [
        ...settings.instruments,
        { name, role: "texture", from_preset: false },
      ],
    });
    setNewName("");
  };

  const removeAt = (index: number) => {
    onChange({
      ...settings,
      instruments: settings.instruments.filter((_, i) => i !== index),
    });
  };

  const updateItem = (index: number, patch: Partial<SongInstrumentItem>) => {
    onChange({
      ...settings,
      instruments: settings.instruments.map((item, i) =>
        i === index ? { ...item, ...patch } : item,
      ),
    });
  };

  return (
    <div className="instrument-editor">
      <div className="instrument-editor-header">
        <div>
          <h3>악기 세팅</h3>
          {(presetName || settings.preset_name) && (
            <p className="instrument-preset-label">
              앨범 프리셋: {presetName || settings.preset_name}
            </p>
          )}
          {settings.tempo_bpm != null && Number.isFinite(settings.tempo_bpm) && (
            <p className="instrument-summary">
              이 곡 BPM: {settings.tempo_bpm}
              <span style={{ color: "var(--text-muted)", marginLeft: "0.35rem" }}>
                (프리셋 ±5, 가사·분위기 반영)
              </span>
            </p>
          )}
          {summary && (
            <p className="instrument-summary">{summary}</p>
          )}
        </div>
      </div>

      {settings.instruments.length === 0 ? (
        <p className="instrument-empty">
          프리셋에 등록된 악기가 없습니다. 아래에서 악기를 추가하세요.
        </p>
      ) : (
        <ul className="instrument-list">
          {settings.instruments.map((item, index) => (
            <li key={`${item.name}-${index}`} className="instrument-row">
              <input
                value={item.name}
                onChange={(e) => updateItem(index, { name: e.target.value })}
                placeholder="악기명"
              />
              <select
                value={item.role}
                onChange={(e) => updateItem(index, { role: e.target.value })}
              >
                {ROLES.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
              <input
                value={item.notes || ""}
                onChange={(e) => updateItem(index, { notes: e.target.value })}
                placeholder="이 곡에서의 역할 (선택)"
                className="instrument-notes"
              />
              {item.from_preset && <span className="badge">프리셋</span>}
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={() => removeAt(index)}
                title="삭제"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="instrument-section-label">악기 추가</div>
      <div className="instrument-add-row">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="악기 추가 (예: 피아노, 스트링)"
          onKeyDown={(e) => e.key === "Enter" && addInstrument()}
        />
        <button type="button" className="btn btn-secondary btn-sm" onClick={addInstrument}>
          + 추가
        </button>
      </div>
    </div>
  );
}
