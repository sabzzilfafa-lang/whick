import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  formatSunoCopy,
  GenerationVariant,
  MusicProfile,
  Song,
  SongInstrumentSettings,
} from "../api";
import InstrumentEditor, {
  parseInstrumentSettings,
  serializeInstrumentSettings,
} from "../components/InstrumentEditor";
import SongWorkflowBar from "../components/SongWorkflowBar";
import { isStructuredSunoPrompt, SUNO_PROMPT_MAX_CHARS } from "../lib/sunoPrompt";
import { cleanTheme } from "../lib/theme";
import { currentWorkflowStep, getSongWorkflowSteps } from "../lib/songWorkflow";

type TabField = "lyrics" | "prompt" | "instruments";
type LyricsLang = "ko" | "en";

function koLyrics(song: Song): string {
  return song.lyrics_ko ?? song.lyrics ?? "";
}

function enLyrics(song: Song): string {
  return song.lyrics_en ?? "";
}

function displayTitle(song: Song, lang: LyricsLang): string {
  if (lang === "en" && song.title_en?.trim()) return song.title_en;
  return song.title;
}

function formatDurationBadge(song: Song): string | null {
  const parts: string[] = [];
  if (song.estimated_duration_label) {
    const label = song.estimated_duration_label;
    if (song.estimated_duration_source === "album") parts.push(`~${label} · 앨범 배분`);
    else if (song.estimated_duration_source === "lyrics") parts.push(`~${label} · 가사 기준`);
    else parts.push(`~${label}`);
  }
  if (song.tempo_bpm != null) {
    parts.push(
      song.tempo_bpm_range
        ? `${song.tempo_bpm} BPM (${song.tempo_bpm_range})`
        : `${song.tempo_bpm} BPM`
    );
  }
  return parts.length ? parts.join(" · ") : null;
}

function formatLyricsLengthBadge(song: Song): string | null {
  if (!song.target_lyrics_lines_min) return null;
  const actual = song.actual_lyrics_lines ?? 0;
  const range = `${song.target_lyrics_lines_min}~${song.target_lyrics_lines_max}`;
  if (song.lyrics_length_status === "ok") {
    return `가사 ${actual}줄 / 목표 ${range}줄 ✓`;
  }
  if (song.lyrics_length_status === "short") {
    return `가사 ${actual}줄 — 목표 ${range}줄 (부족)`;
  }
  if (song.lyrics_length_status === "long") {
    return `가사 ${actual}줄 — 목표 ${range}줄 (초과)`;
  }
  if (actual > 0) return `가사 ${actual}줄 / 목표 ${range}줄`;
  return `목표 가사 ${range}줄`;
}

function lyricsFieldsFromResult(result: {
  target_lyrics_lines_min?: number;
  target_lyrics_lines_max?: number;
  actual_lyrics_lines?: number;
  lyrics_length_ok?: boolean;
  lyrics_length_status?: Song["lyrics_length_status"];
}): Partial<Song> {
  if (!result.target_lyrics_lines_min) return {};
  return {
    target_lyrics_lines_min: result.target_lyrics_lines_min,
    target_lyrics_lines_max: result.target_lyrics_lines_max,
    actual_lyrics_lines: result.actual_lyrics_lines,
    lyrics_length_ok: result.lyrics_length_ok,
    lyrics_length_status: result.lyrics_length_status,
  };
}

function durationFieldsFromResult(result: {
  estimated_duration_sec?: number;
  estimated_duration_label?: string;
  estimated_duration_source?: Song["estimated_duration_source"];
  tempo_bpm?: number;
  tempo_bpm_base?: number;
  tempo_bpm_range?: string;
  target_lyrics_lines_min?: number;
  target_lyrics_lines_max?: number;
  actual_lyrics_lines?: number;
  lyrics_length_ok?: boolean;
  lyrics_length_status?: Song["lyrics_length_status"];
}): Partial<Song> {
  return {
    ...lyricsFieldsFromResult(result),
    ...(result.estimated_duration_label
      ? {
          estimated_duration_sec: result.estimated_duration_sec,
          estimated_duration_label: result.estimated_duration_label,
          estimated_duration_source: result.estimated_duration_source,
        }
      : {}),
    ...(result.tempo_bpm != null
      ? {
          tempo_bpm: result.tempo_bpm,
          tempo_bpm_base: result.tempo_bpm_base,
          tempo_bpm_range: result.tempo_bpm_range,
        }
      : {}),
  };
}

function MixNotesHeader({ song }: { song: Song }) {
  const badge = formatDurationBadge(song);
  const lyricsBadge = formatLyricsLengthBadge(song);
  return (
    <div className="editor-panel-label-row">
      <label className="editor-panel-label">믹스 메모 / 프롬프트 지시</label>
      <div className="track-duration-badges">
        {badge && (
          <span className="track-duration-badge" title="앨범 배분 곡당 목표 시간">
            목표 {badge}
          </span>
        )}
        {lyricsBadge && (
          <span
            className={`track-duration-badge${song.lyrics_length_status === "short" ? " track-duration-badge--warn" : ""}`}
            title="Suno는 가사 줄 수로 곡 길이를 맞춥니다"
          >
            {lyricsBadge}
          </span>
        )}
      </div>
    </div>
  );
}

export default function SongPage() {
  const { id } = useParams<{ id: string }>();
  const [song, setSong] = useState<Song | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [message, setMessage] = useState("");
  const [variants, setVariants] = useState<GenerationVariant[]>([]);
  const [showAB, setShowAB] = useState(false);
  const [abType, setAbType] = useState<TabField>("lyrics");
  const [lyricsLang, setLyricsLang] = useState<LyricsLang>("en");
  const [translatingLyrics, setTranslatingLyrics] = useState(false);
  const [instrumentData, setInstrumentData] = useState<SongInstrumentSettings | null>(null);
  const [instrumentsOpen, setInstrumentsOpen] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [profiles, setProfiles] = useState<MusicProfile[]>([]);
  const [copiedField, setCopiedField] = useState<"lyrics" | "prompt" | "suno" | null>(null);
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = () => {
    if (!id) return;
    api.getSong(Number(id)).then(setSong).finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  useEffect(() => {
    api.listProfiles().then(setProfiles).catch(() => {});
  }, []);

  useEffect(() => {
    return () => {
      if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    };
  }, []);

  const flashCopied = (field: "lyrics" | "prompt" | "suno") => {
    setCopiedField(field);
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = setTimeout(() => setCopiedField(null), 2000);
  };

  useEffect(() => {
    if (!song) return;
    const parsed = parseInstrumentSettings(song.instrument_settings);
    if (parsed) {
      setInstrumentData(parsed);
      setPresetName(parsed.preset_name);
    }
  }, [song?.id, song?.instrument_settings]);

  const exportToWorkFolder = async (savedSong: Song, lang: LyricsLang = lyricsLang) => {
    const exportRes = await api.exportSongToPipeline(savedSong.id, "music", lang);
    await api.openPipelineFolder(exportRes.path);
    return exportRes;
  };

  const handleSave = async () => {
    if (!song) return;
    const instJson =
      instrumentData != null
        ? serializeInstrumentSettings(instrumentData)
        : song.instrument_settings;
    setGenerating("save");
    setError("");
    setMessage("");
    try {
      const updated = await api.updateSong(song.id, {
        title: song.title,
        title_en: song.title_en,
        theme: song.theme,
        mood: song.mood,
        tags: song.tags,
        lyrics: koLyrics(song),
        lyrics_ko: koLyrics(song),
        lyrics_en: song.lyrics_en,
        suno_prompt: song.suno_prompt,
        instrument_settings: instJson,
      });
      const merged = { ...song, ...updated, instrument_settings: instJson };
      const exportRes = await exportToWorkFolder(merged, lyricsLang);
      setSong({ ...merged, pipeline_path: exportRes.pipeline_path });
      setSaved(true);
      setMessage(`저장 완료 — 작업폴더: ${exportRes.path}`);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장 또는 작업폴더 반영 실패");
    } finally {
      setGenerating(null);
    }
  };

  const handleSetupInstruments = async () => {
    if (!song) return;
    setGenerating("instruments");
    setError("");
    setInstrumentsOpen(true);
    try {
      let data: SongInstrumentSettings;
      const existing = parseInstrumentSettings(song.instrument_settings);
      if (existing?.instruments.length) {
        data = existing;
        setMessage("저장된 악기 세팅을 불러왔습니다.");
      } else if (koLyrics(song).trim()) {
        // 프리셋만 복사하면 전 곡이 같아지므로, 가사 감정이 있으면 곡별 편곡까지 생성
        await api.applySongInstrumentsFromPreset(song.id);
        const result = await api.generateInstruments(song.id, undefined, true);
        const parsed = parseInstrumentSettings(result.content);
        if (!parsed?.instruments.length) {
          throw new Error("악기 제안을 파싱하지 못했습니다");
        }
        data = parsed;
        setMessage(
          "가사 감정을 반영해 이 곡용 악기를 구성했습니다. 필요하면 수정 후 저장하세요."
        );
      } else {
        const result = await api.applySongInstrumentsFromPreset(song.id);
        data = result;
        setMessage(
          "앨범 프리셋 기본 악기를 불러왔습니다. 한글 가사 작성 후 「AI 악기 제안」으로 곡별 변화를 주세요."
        );
      }
      const json = serializeInstrumentSettings(data);
      setInstrumentData(data);
      setPresetName(data.preset_name);
      setSong({ ...song, instrument_settings: json });
    } catch (e) {
      setError(e instanceof Error ? e.message : "악기 불러오기 실패");
    } finally {
      setGenerating(null);
    }
  };

  const handleSaveInstruments = async () => {
    if (!song || !instrumentData) return;
    setGenerating("instruments-save");
    setError("");
    try {
      const saved = await api.saveSongInstruments(song.id, instrumentData);
      const json = serializeInstrumentSettings(saved);
      setInstrumentData(saved);
      setSong({ ...song, instrument_settings: json });
      setMessage("악기 세팅을 저장했습니다.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setGenerating(null);
    }
  };

  const handleAiInstruments = async () => {
    if (!song) return;
    if (!koLyrics(song).trim()) {
      setError("AI 악기 제안은 한글 가사를 먼저 작성한 뒤 사용할 수 있습니다.");
      return;
    }
    setGenerating("instruments-ai");
    setError("");
    try {
      if (instrumentData) {
        await api.saveSongInstruments(song.id, instrumentData);
      }
      const result = await api.generateInstruments(song.id, undefined, true);
      const parsed = parseInstrumentSettings(result.content);
      if (parsed) {
        setInstrumentData(parsed);
        setPresetName(parsed.preset_name);
      }
      setSong({ ...song, instrument_settings: result.content });
      setInstrumentsOpen(true);
      setMessage("프리셋 악기를 바탕으로, 이 곡 가사에 맞게 제안을 반영했습니다.");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "AI 제안 실패";
      if (msg.includes("404")) {
        setError(
          "AI 모델 오류입니다. 설정에서 「가성비 권장 설정 적용」 후 저장하고, stop.bat → start.bat으로 재시작해 주세요."
        );
      } else {
        setError(msg);
      }
    } finally {
      setGenerating(null);
    }
  };

  const handleSongPresetChange = async (value: string) => {
    if (!song) return;
    const profileId = value ? Number(value) : null;
    // 프리셋을 바꾸면 이 곡의 수동 악기 편집이 프리셋 기본값으로 덮어써진다
    const hasCustom = (instrumentData?.instruments.length ?? 0) > 0;
    const targetName = profileId
      ? profiles.find((p) => p.id === profileId)?.name || "선택한 프리셋"
      : "앨범 프리셋";
    if (
      hasCustom &&
      !confirm(
        `이 곡의 프리셋을 '${targetName}'(으)로 바꿉니다.\n지금까지 편집한 악기 구성은 프리셋 기본값으로 초기화됩니다. 계속할까요?`
      )
    ) {
      // 취소 — select 표시를 원래 곡 프리셋 값으로 되돌림
      setSong({ ...song, music_profile_id: song.music_profile_id });
      return;
    }
    setGenerating("song-preset");
    setError("");
    try {
      const data = await api.applyPresetToSong(song.id, profileId);
      const json = serializeInstrumentSettings(data);
      setInstrumentData(data);
      setPresetName(data.preset_name);
      setInstrumentsOpen(true);
      setSong({
        ...song,
        music_profile_id: profileId ?? undefined,
        instrument_settings: json,
      });
      setMessage(
        profileId
          ? "이 곡의 프리셋을 변경했습니다. 악기 구성이 즉시 바뀌었으니 Suno 프롬프트도 다시 생성하세요."
          : "곡 프리셋을 해제했습니다. 앨범 프리셋 기준으로 악기를 되돌렸습니다."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "프리셋 변경 실패");
    } finally {
      setGenerating(null);
    }
  };

  const handleReloadPreset = async () => {
    if (!song || !confirm("프리셋 기본 악기로 되돌립니다. 이 곡의 수정 내용이 사라집니다.")) return;
    setGenerating("instruments");
    setError("");
    try {
      const data = await api.applySongInstrumentsFromPreset(song.id);
      const json = serializeInstrumentSettings(data);
      setInstrumentData(data);
      setPresetName(data.preset_name);
      setSong({ ...song, instrument_settings: json });
      setMessage("프리셋 기본 악기로 되돌렸습니다.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "불러오기 실패");
    } finally {
      setGenerating(null);
    }
  };

  const handleLyricsLangChange = async (lang: LyricsLang) => {
    if (!song || lang === lyricsLang) return;
    if (lang === "ko") {
      setLyricsLang("ko");
      return;
    }
    setLyricsLang("en");
    const ko = koLyrics(song).trim();
    const en = enLyrics(song).trim();
    if (!ko || en) return;

    setTranslatingLyrics(true);
    setError("");
    try {
      const result = await api.generateLyrics(song.id, undefined, "en", koLyrics(song));
      setSong({
        ...song,
        lyrics_en: result.content,
        ...(result.title?.trim() ? { title_en: result.title.trim() } : {}),
        ...durationFieldsFromResult(result),
      });
      setMessage(
        result.title?.trim()
          ? `영어 제목과 가사를 의역했습니다: ${result.title.trim()}`
          : "수정한 한글 가사를 바탕으로 영어 가사를 의역했습니다."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "가사 번역 실패");
      setLyricsLang("ko");
    } finally {
      setTranslatingLyrics(false);
    }
  };

  const handleGenerate = async (type: TabField) => {
    if (!song) return;
    if (type === "prompt") {
      if (!koLyrics(song).trim()) {
        setError("Suno 프롬프트 생성 전에 한글 가사를 먼저 작성하세요.");
        return;
      }
      const instJson =
        instrumentData != null
          ? serializeInstrumentSettings(instrumentData)
          : song.instrument_settings;
      if (!instJson?.trim()) {
        setError("악기 세팅을 불러온 뒤 믹스 메모를 입력하세요.");
        return;
      }
    }
    setGenerating(type);
    setError("");
    try {
      let result;
      if (type === "lyrics") {
        const ko = koLyrics(song).trim();
        const en = enLyrics(song).trim();
        // - 목표 언어에 이미 가사가 있으면 → 재생성 (원문 전달 없이 새로 생성)
        // - 목표 언어가 비어 있고 반대 언어가 있으면 → 의역 (원문 전달)
        // - 둘 다 없으면 → 새로 생성
        const hasTarget = lyricsLang === "ko" ? !!ko : !!en;
        result = await api.generateLyrics(
          song.id,
          undefined,
          lyricsLang,
          lyricsLang === "en" && !hasTarget ? ko || undefined : undefined,
          lyricsLang === "ko" && !hasTarget ? en || undefined : undefined
        );
      } else if (type === "prompt") {
        const instJson =
          instrumentData != null
            ? serializeInstrumentSettings(instrumentData)
            : song.instrument_settings;
        result = await api.generatePrompt(song.id, undefined, instJson);
      } else {
        await handleAiInstruments();
        return;
      }

      if (type === "lyrics") {
        const ko = koLyrics(song).trim();
        const en = enLyrics(song).trim();
        if (lyricsLang === "en") {
          setSong({
            ...song,
            lyrics_en: result.content,
            ...(result.title?.trim() ? { title_en: result.title.trim() } : {}),
            ...durationFieldsFromResult(result),
          });
          setMessage(
            result.title?.trim()
              ? ko
                ? `영어 제목과 가사를 의역했습니다: ${result.title.trim()}`
                : `영어 제목과 가사를 생성했습니다: ${result.title.trim()}`
              : "수정한 한글 가사를 바탕으로 영어 가사를 의역했습니다."
          );
        } else {
          const paraphrased = en.length > 0;
          setSong({
            ...song,
            lyrics_ko: result.content,
            lyrics: result.content,
            ...(result.title?.trim() ? { title: result.title.trim() } : {}),
            ...durationFieldsFromResult(result),
          });
          if (paraphrased) {
            setMessage(
              result.title?.trim()
                ? `한국어 제목과 가사를 의역했습니다: ${result.title.trim()}`
                : "확정된 영어 가사를 바탕으로 한글 가사를 의역했습니다."
            );
          } else if (result.title?.trim()) {
            setMessage(`곡 제목과 한글 가사를 생성했습니다: ${result.title.trim()}`);
          }
        }
      } else {
        const field = type === "prompt" ? "suno_prompt" : "instrument_settings";
        let instJson =
          type === "prompt" && instrumentData != null
            ? serializeInstrumentSettings(instrumentData)
            : song.instrument_settings;
        if (type === "prompt" && result.tempo_bpm != null) {
          const base =
            instrumentData ??
            parseInstrumentSettings(instJson) ??
            ({ preset_name: "", mix_notes: "", instruments: [] } as SongInstrumentSettings);
          const withTempo = { ...base, tempo_bpm: result.tempo_bpm };
          instJson = serializeInstrumentSettings(withTempo);
          setInstrumentData(withTempo);
        }
        setSong({
          ...song,
          [field]: result.content,
          ...(type === "prompt" && instJson ? { instrument_settings: instJson } : {}),
          ...durationFieldsFromResult(result),
        });
        if (type === "prompt") {
          const len = result.content.length;
          const bpmNote =
            result.tempo_bpm != null
              ? ` · ${result.tempo_bpm} BPM` +
                (result.tempo_bpm_range ? ` (${result.tempo_bpm_range})` : "")
              : "";
          if (isStructuredSunoPrompt(result.content)) {
            setMessage(
              `Suno 프롬프트 생성 완료 (${len}/${SUNO_PROMPT_MAX_CHARS}자)${bpmNote}.`
            );
          } else {
            setMessage(`프롬프트를 생성했습니다 (${len}자)${bpmNote}. 내용을 확인해 주세요.`);
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "생성 실패");
    } finally {
      setGenerating(null);
    }
  };

  const copyText = async (text: string, label: string, field: "lyrics" | "prompt") => {
    if (!text.trim()) {
      setError(`${label}이(가) 비어 있습니다.`);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      flashCopied(field);
      setMessage(`${label}을(를) 클립보드에 복사했습니다.`);
    } catch {
      setError("클립보드 복사에 실패했습니다.");
    }
  };

  const copyLyrics = () => {
    if (!song) return;
    const text = lyricsLang === "ko" ? koLyrics(song) : enLyrics(song);
    void copyText(text, lyricsLang === "ko" ? "한글 가사" : "영어 가사", "lyrics");
  };

  const copyPrompt = () => {
    if (!song) return;
    void copyText(song.suno_prompt || "", "Suno 프롬프트", "prompt");
  };

  const handleAB = async (type: TabField = abType) => {
    if (!song) return;
    setAbType(type);
    setGenerating("ab");
    setError("");
    try {
      const result = await api.generateAB(song.id, type, 2);
      setVariants(result);
      setShowAB(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "A/B 생성 실패");
    } finally {
      setGenerating(null);
    }
  };

  const applyVariant = async (variant: GenerationVariant) => {
    if (!song) return;
    await api.applyVariant(song.id, variant.id);
    const field =
      variant.task_type === "lyrics"
        ? lyricsLang === "en"
          ? "lyrics_en"
          : "lyrics_ko"
        : variant.task_type === "prompt"
          ? "suno_prompt"
          : "instrument_settings";
    const updates: Partial<Song> = { [field]: variant.content };
    if (variant.task_type === "lyrics" && lyricsLang === "ko") {
      updates.lyrics = variant.content;
    }
    setSong({ ...song, ...updates });
    setMessage(`${variant.variant_label}안이 적용되었습니다.`);
    setShowAB(false);
  };

  const copySuno = () => {
    if (!song) return;
    void navigator.clipboard.writeText(formatSunoCopy(song)).then(
      () => {
        flashCopied("suno");
        setMessage("Suno용 콘텐츠가 클립보드에 복사되었습니다.");
      },
      () => setError("클립보드 복사에 실패했습니다.")
    );
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!song || !e.target.files?.[0]) return;
    try {
      const res = await api.uploadAudio(song.id, e.target.files[0]);
      setSong({ ...song, audio_path: res.audio_path });
      setMessage("음원 업로드 완료 — 「저장」을 누르면 01_음악작업/앨범명/곡 폴더로 복사됩니다.");
    } catch {
      setError("음원 업로드 실패");
    } finally {
      e.target.value = "";
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!song || !e.target.files?.[0]) return;
    try {
      const res = await api.uploadSongImage(song.id, e.target.files[0]);
      setSong({ ...song, image_path: res.image_path });
      setMessage("커버 이미지 업로드 완료");
    } catch {
      setError("이미지 업로드 실패");
    }
  };

  const handleExportToStudio = async () => {
    if (!song) return;
    setGenerating("export");
    setMessage("");
    try {
      const exportRes = await exportToWorkFolder(song, lyricsLang);
      setSong({ ...song, pipeline_path: exportRes.pipeline_path });
      setMessage(`작업폴더로 복사 완료: ${exportRes.path}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(null);
    }
  };

  if (loading) return <div className="loading">불러오는 중...</div>;
  if (!song) return <div className="error">곡을 찾을 수 없습니다</div>;

  const workflowSteps = getSongWorkflowSteps(song);
  const step = currentWorkflowStep(song);

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to={`/albums/${song.album_id}`} style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            ← 앨범으로
          </Link>
          <h2 style={{ marginTop: "0.5rem" }}>
            {song.track_number}. {displayTitle(song, lyricsLang)}
          </h2>
          {song.theme && (
            <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>
              {cleanTheme(song.theme)}
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {saved && <span style={{ color: "var(--success)", fontSize: "0.85rem" }}>저장됨</span>}
          <button className="btn btn-secondary" onClick={copySuno}>
            {copiedField === "suno" ? "복사됨" : "Suno 복사"}
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={generating === "save"}>
            {generating === "save" ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success-banner">{message}</div>}

      <SongWorkflowBar steps={workflowSteps} />

      {(song.audio_path || song.image_path) && (
        <div className="card" style={{ marginBottom: "1rem", display: "flex", gap: "1.5rem", alignItems: "flex-start", flexWrap: "wrap" }}>
          {song.image_path && (
            <div>
              <div className="meta" style={{ marginBottom: "0.35rem" }}>커버 이미지 (유튜브 영상용)</div>
              <img
                src={`${api.songCoverUrl(song.id)}?t=${song.updated_at}`}
                alt="커버"
                style={{ maxWidth: "200px", borderRadius: "8px", display: "block" }}
              />
            </div>
          )}
          {song.audio_path && (
            <div className="meta">음원: 업로드됨 — 저장 시 01_음악작업/앨범/곡 폴더로 audio.* 복사</div>
          )}
        </div>
      )}

      <div className="form-group" style={{ maxWidth: "400px" }}>
        <label>이 곡의 스타일 프리셋 (악기 구성 · Suno 프롬프트 기준)</label>
        <select
          value={song.music_profile_id ?? ""}
          onChange={(e) => void handleSongPresetChange(e.target.value)}
          disabled={!!generating}
        >
          <option value="">
            (앨범 프리셋 따름{presetName ? ` — ${presetName}` : ""})
          </option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.emoji || "🎵"} {p.name}
            </option>
          ))}
        </select>
        <p className="panel-hint">
          곡마다 다른 프리셋을 고르면 악기 구성이 즉시 다시 만들어지고,
          Suno 프롬프트도 이 프리셋 기준으로 생성됩니다.
        </p>
      </div>

      <div className="form-group" style={{ maxWidth: "400px" }}>
        <label>태그 (쉼표 구분)</label>
        <input
          value={song.tags || ""}
          onChange={(e) => setSong({ ...song, tags: e.target.value })}
          placeholder="예: 발라드, 감성, 여름"
        />
      </div>

      <div className="generate-actions">
        <div className="generate-action-group">
          <button
            className={`btn ${step === "lyrics_ko" || step === "lyrics_en" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => handleGenerate("lyrics")}
            disabled={!!generating || translatingLyrics}
          >
            {generating === "lyrics"
              ? "가사 생성 중..."
              : lyricsLang === "ko"
                ? koLyrics(song).trim()
                  ? "한글 가사 재생성"
                  : enLyrics(song).trim()
                    ? "한글로 의역"
                    : "한글 가사 생성"
                : enLyrics(song).trim()
                  ? "영어 가사 재생성"
                  : koLyrics(song).trim()
                    ? "영어로 의역"
                    : "영어 가사 생성"}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void handleAB("lyrics")}
            disabled={!!generating || translatingLyrics}
            title="가사 A/B 비교 생성"
          >
            {generating === "ab" && abType === "lyrics" ? "A/B..." : "A/B"}
          </button>
        </div>
        <button
          className={`btn ${step === "instruments" ? "btn-primary" : "btn-secondary"}`}
          onClick={handleSetupInstruments}
          disabled={!!generating || translatingLyrics}
        >
          {generating === "instruments" ? "불러오는 중..." : "악기 세팅"}
        </button>
        <button
          className={`btn ${step === "prompt" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => handleGenerate("prompt")}
          disabled={!!generating || translatingLyrics}
        >
          {generating === "prompt" ? "프롬프트 생성 중..." : "Suno 프롬프트"}
        </button>
        <label className="btn btn-secondary" style={{ cursor: "pointer" }} title="다운로드 폴더 등에서 mp3/wav 파일을 선택하세요">
          음원 파일 선택
          <input type="file" accept="audio/*" onChange={handleUpload} hidden />
        </label>
        <label className="btn btn-secondary" style={{ cursor: "pointer" }}>
          커버 이미지
          <input type="file" accept="image/*" onChange={handleImageUpload} hidden />
        </label>
        <button
          className="btn btn-secondary"
          onClick={handleExportToStudio}
          disabled={!!generating}
        >
          {generating === "export" ? "복사 중..." : "작업폴더로 복사"}
        </button>
        <Link to="/studio" className="btn btn-secondary">유튜브 스튜디오</Link>
      </div>

      {showAB && (
        <div className="card ab-panel">
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1rem" }}>
            <div className="card-title" style={{ margin: 0 }}>A/B 비교</div>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              {(["lyrics", "instruments", "prompt"] as TabField[]).map((t) => (
                <button
                  key={t}
                  className={`btn btn-sm ${abType === t ? "btn-primary" : "btn-secondary"}`}
                  onClick={async () => {
                    setAbType(t);
                    if (song) {
                      const v = await api.listVariants(song.id, t);
                      setVariants(v.slice(0, 2));
                    }
                  }}
                >
                  {t === "lyrics" ? "가사" : t === "prompt" ? "프롬프트" : "악기"}
                </button>
              ))}
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => void handleAB(abType)}
                disabled={!!generating}
              >
                {generating === "ab" ? "생성 중..." : "A/B 생성"}
              </button>
              <button className="btn btn-sm btn-secondary" onClick={() => setShowAB(false)}>닫기</button>
            </div>
          </div>
          {variants.filter((v) => v.task_type === abType).length === 0 ? (
            <p style={{ color: "var(--text-muted)" }}>
              {abType === "lyrics"
                ? "가사 생성 옆 A/B로도 생성할 수 있습니다."
                : "위 A/B 생성 버튼으로 이 타입의 비교안을 만드세요."}
            </p>
          ) : (
            <div className="ab-grid">
              {variants.filter((v) => v.task_type === abType).map((v) => (
                <div key={v.id} className="ab-card">
                  <div className="ab-label">{v.variant_label}안</div>
                  <textarea value={v.content} readOnly rows={10} />
                  <button className="btn btn-primary btn-sm" onClick={() => applyVariant(v)}>
                    이 안 선택
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="song-editor">
        <div className="editor-panel editor-panel--lyrics">
          <div className="editor-panel-header">
            <div className="editor-panel-title-row">
              <h3>가사</h3>
              {formatLyricsLengthBadge(song) && (
                <span
                  className={`track-duration-badge${song.lyrics_length_status === "short" ? " track-duration-badge--warn" : ""}`}
                  title="Suno는 가사 줄 수로 곡 길이를 맞춥니다"
                >
                  {formatLyricsLengthBadge(song)}
                </span>
              )}
            </div>
            <div className="editor-panel-tools">
              <button
                type="button"
                className={`btn btn-sm ${copiedField === "lyrics" ? "btn-primary" : "btn-secondary"}`}
                onClick={copyLyrics}
                disabled={translatingLyrics}
              >
                {copiedField === "lyrics" ? "복사됨" : "복사"}
              </button>
              <div className="lang-toggle">
              <button
                type="button"
                className={`btn btn-sm ${lyricsLang === "ko" ? "btn-primary" : "btn-secondary"}`}
                onClick={() => handleLyricsLangChange("ko")}
                disabled={translatingLyrics}
              >
                한글
              </button>
              <button
                type="button"
                className={`btn btn-sm ${lyricsLang === "en" ? "btn-primary" : "btn-secondary"}`}
                onClick={() => handleLyricsLangChange("en")}
                disabled={translatingLyrics}
              >
                {translatingLyrics ? "번역 중..." : "English"}
              </button>
              </div>
            </div>
          </div>
          <div className="form-group song-title-field">
            <label>{lyricsLang === "en" ? "곡 제목 (English)" : "곡 제목 (한글)"}</label>
            <input
              value={displayTitle(song, lyricsLang)}
              onChange={(e) => {
                if (lyricsLang === "en") {
                  setSong({ ...song, title_en: e.target.value });
                } else {
                  setSong({ ...song, title: e.target.value });
                }
              }}
              placeholder={
                lyricsLang === "en"
                  ? "영어 가사 번역 시 함께 만들어지며, 직접 수정할 수 있습니다"
                  : "한글 가사 생성 시 함께 만들어지며, 직접 수정할 수 있습니다"
              }
            />
          </div>
          <textarea
            value={lyricsLang === "ko" ? koLyrics(song) : enLyrics(song)}
            onChange={(e) => {
              if (lyricsLang === "en") {
                setSong({ ...song, lyrics_en: e.target.value });
              } else {
                setSong({ ...song, lyrics_ko: e.target.value, lyrics: e.target.value });
              }
            }}
            placeholder={
              translatingLyrics
                ? lyricsLang === "en"
                  ? "한글 가사를 영어로 번역하는 중..."
                  : "영어 가사를 한글로 의역하는 중..."
                : lyricsLang === "ko"
                  ? "한글 가사 (AI 생성 또는 직접 입력)"
                  : enLyrics(song).trim()
                    ? "English lyrics"
                    : "English 탭 또는 「영어로 의역」으로 수정한 한글을 영어 가사로 옮깁니다"
            }
            rows={16}
            disabled={translatingLyrics}
            className="lyrics-textarea"
          />
        </div>
        <div className="song-editor-side">
          {(instrumentsOpen || instrumentData) && instrumentData ? (
            <div className="editor-panel editor-panel--instruments">
              <InstrumentEditor
                settings={instrumentData}
                onChange={setInstrumentData}
                presetName={presetName}
                profiles={profiles.map((p) => ({ id: p.id, name: p.name, emoji: p.emoji }))}
                songProfileId={song.music_profile_id ?? null}
                onSongPresetChange={(pid) => void handleSongPresetChange(pid == null ? "" : String(pid))}
                changingPreset={generating === "song-preset"}
              />
              <div className="instrument-ai-optional">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleAiInstruments}
                  disabled={!!generating || !koLyrics(song).trim()}
                >
                  {generating === "instruments-ai"
                    ? "AI 제안 생성 중..."
                    : "가사에 맞게 AI 악기 제안 (선택)"}
                </button>
                <p className="instrument-ai-hint">
                  가사 감정을 읽고 리드·리듬·텍스처를 곡마다 다르게 제안합니다.
                  시그니처 1~2개만 남기고 나머지를 바꿉니다. 직접 고르셨다면 건너뛰어도 됩니다.
                  「프리셋 불러오기」만 스타일 프리셋 기본 악기로 되돌립니다.
                </p>
              </div>
              <div className="instrument-editor-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleReloadPreset}
                  disabled={!!generating}
                >
                  프리셋 불러오기
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleSaveInstruments}
                  disabled={!!generating}
                >
                  {generating === "instruments-save" ? "저장 중..." : "악기 저장"}
                </button>
              </div>
            </div>
          ) : (
            <div className="editor-panel editor-panel--instruments">
              <h3>악기 세팅</h3>
              <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                「악기 세팅」을 누르면 앨범 스타일 프리셋의 기본 악기가 나옵니다.
                곡마다 추가·삭제한 뒤 <strong>악기 저장</strong>하세요.
              </p>
            </div>
          )}

          <div className="editor-section-gap" aria-hidden="true" />

          {(instrumentsOpen || instrumentData) && instrumentData ? (
            <div className="editor-panel editor-panel--mix-notes">
              <MixNotesHeader song={song} />
              <input
                value={instrumentData.mix_notes || ""}
                onChange={(e) =>
                  setInstrumentData({ ...instrumentData, mix_notes: e.target.value })
                }
                placeholder="예: 코러스에서 드럼 강하게, 브릿지는 피아노만, 전체적으로 몽환적으로"
              />
              <p className="panel-hint">
                Suno 프롬프트 생성 시 반영됩니다 (악기 저장 없이도 프롬프트 생성에 포함).
                보컬·믹스 지시(예: 남녀 혼성듀오)는 [Overview]에 영어로 들어갑니다.
              </p>
            </div>
          ) : (
            <div className="editor-panel editor-panel--mix-notes editor-panel--muted">
              <MixNotesHeader song={song} />
              <p className="panel-hint" style={{ margin: 0 }}>
                악기 세팅을 불러온 뒤 입력할 수 있습니다.
              </p>
            </div>
          )}

          <div className="editor-panel editor-panel--prompt">
            <div className="editor-panel-header">
              <h3>Suno 스타일 프롬프트</h3>
              <button
                type="button"
                className={`btn btn-sm ${copiedField === "prompt" ? "btn-primary" : "btn-secondary"}`}
                onClick={copyPrompt}
              >
                {copiedField === "prompt" ? "복사됨" : "복사"}
              </button>
            </div>
            <p className="panel-hint">
              이 곡의 가사 감정·악기 세팅을 반영해 Intro → Verse → Climax → Outro 편곡을 만듭니다.
              수동으로 고친 악기를 스타일 프리셋으로 되돌리지 않습니다.
              Suno Style of Music 칸에 붙여 넣으세요. (최대 {SUNO_PROMPT_MAX_CHARS}자)
            </p>
            <textarea
              value={song.suno_prompt || ""}
              onChange={(e) => setSong({ ...song, suno_prompt: e.target.value })}
              placeholder="「Suno 프롬프트」 버튼으로 구간별 편곡 프롬프트를 생성하세요"
              rows={12}
              className="prompt-textarea"
            />
            <p
              style={{
                fontSize: "0.85rem",
                marginTop: "0.4rem",
                color:
                  (song.suno_prompt?.length ?? 0) > SUNO_PROMPT_MAX_CHARS
                    ? "var(--danger, #e55)"
                    : "var(--text-muted)",
              }}
            >
              {(song.suno_prompt?.length ?? 0).toLocaleString()} / {SUNO_PROMPT_MAX_CHARS}자
              {(song.suno_prompt?.length ?? 0) > SUNO_PROMPT_MAX_CHARS && " — Suno 제한 초과"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
