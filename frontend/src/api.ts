import { builderToInstrumentSettings, isApiUnavailableError } from "./lib/instruments";

const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isForm = options?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: isForm ? options?.headers : { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(" / ") || res.statusText
          : "요청 실패";
    throw new Error(msg);
  }
  return res.json();
}

export interface MusicProfile {
  id: number;
  name: string;
  description?: string;
  genre?: string;
  mood?: string;
  tempo_bpm?: number;
  key_signature?: string;
  vocal_style?: string;
  instruments?: string;
  production_style?: string;
  reference_artists?: string;
  extra_notes?: string;
  tags?: string;
  emoji?: string;
  last_used_at?: string;
  created_at: string;
  updated_at: string;
}

export interface Album {
  id: number;
  title: string;
  concept?: string;
  mood?: string;
  target_duration_min?: number;
  track_count: number;
  music_profile_id?: number;
  created_at: string;
  updated_at: string;
}

export interface Song {
  id: number;
  album_id: number;
  track_number: number;
  title: string;
  title_en?: string;
  estimated_duration_sec?: number;
  estimated_duration_label?: string;
  estimated_duration_source?: "lyrics" | "album" | "default";
  tempo_bpm?: number;
  tempo_bpm_base?: number;
  tempo_bpm_range?: string;
  target_lyrics_lines_min?: number;
  target_lyrics_lines_max?: number;
  actual_lyrics_lines?: number;
  lyrics_length_ok?: boolean;
  lyrics_length_status?: "none" | "short" | "ok" | "long" | "unknown";
  theme?: string;
  mood?: string;
  tags?: string;
  lyrics?: string;
  lyrics_ko?: string;
  lyrics_en?: string;
  suno_prompt?: string;
  instrument_settings?: string;
  audio_path?: string;
  image_path?: string;
  pipeline_path?: string;
  music_profile_id?: number;
  reference_song_id?: number;
  created_at: string;
  updated_at: string;
}

export interface AlbumDetail extends Album {
  songs: Song[];
}

export interface GenerationResult {
  content: string;
  model_used: string;
  task_type: string;
  title?: string;
  estimated_duration_sec?: number;
  estimated_duration_label?: string;
  estimated_duration_source?: "lyrics" | "album" | "default";
  tempo_bpm?: number;
  tempo_bpm_base?: number;
  tempo_bpm_range?: string;
  target_lyrics_lines_min?: number;
  target_lyrics_lines_max?: number;
  actual_lyrics_lines?: number;
  lyrics_length_ok?: boolean;
  lyrics_length_status?: "none" | "short" | "ok" | "long" | "unknown";
}

export interface SongInstrumentItem {
  name: string;
  name_en?: string;
  role: string;
  tone?: string;
  texture?: string;
  notes?: string;
  from_preset?: boolean;
}

export interface SongInstrumentSettings {
  preset_name: string;
  mix_notes: string;
  tempo_bpm?: number | null;
  instruments: SongInstrumentItem[];
}

export interface AIProvider {
  id: string;
  name: string;
  description: string;
  key_url: string;
  key_field: string;
  default_models: Record<string, string>;
  recommended_models?: { id: string; name: string }[];
}

export interface AIModelOption {
  id: string;
  name: string;
}

export interface AppSettings {
  openrouter_api_key_set: boolean;
  openrouter_api_key_masked: string;
  openai_api_key_set: boolean;
  openai_api_key_masked: string;
  anthropic_api_key_set: boolean;
  anthropic_api_key_masked: string;
  google_api_key_set: boolean;
  google_api_key_masked: string;
  provider_lyrics: string;
  provider_prompt: string;
  provider_instruments: string;
  provider_analyze: string;
  model_lyrics: string;
  model_prompt: string;
  model_instruments: string;
  model_analyze: string;
  temperature_lyrics: string;
  temperature_prompt: string;
  temperature_instruments: string;
  temperature_analyze: string;
  /** 썸네일 3종 생성 (2026-09-10): 프롬프트용 텍스트 AI + 이미지 생성 AI */
  provider_thumbnail: string;
  model_thumbnail: string;
  image_provider: string;
  image_model: string;
  thumbnail_title_mode?: string;
  thumbnail_overlay: string;
}

export interface GenerationVariant {
  id: number;
  song_id: number;
  task_type: string;
  variant_label: string;
  content: string;
  model_used: string;
  created_at: string;
}

export interface QueueJob {
  id: number;
  job_type: string;
  status: string;
  progress: number;
  total: number;
  message?: string;
  result_json?: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowStage {
  id: string;
  folder: string;
  label: string;
  description: string;
  path?: string;
  project_count?: number;
}

export interface PipelineConfig {
  work_root: string;
  audio: {
    master_chain: string;
    output_codec: string;
    output_bitrate: string;
  };
  video: {
    width: number;
    height: number;
    fps: number;
    encoder: string;
    crf: number;
    amf_quality: string;
    image_duration_sec: number;
  };
  subtitle: {
    font_name: string;
    track_style: Record<string, number>;
    lyrics_style: Record<string, number>;
  };
  overlay: Record<string, unknown>;
}

export interface PipelineStatus {
  ffmpeg_available: boolean;
  detected_encoder: string | null;
  stages: WorkflowStage[];
}

export interface BrowseEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size?: number;
  modified?: string;
  kind?: string;
}

export interface BrowseResult {
  path: string;
  entries: BrowseEntry[];
}

export interface ProjectAssets {
  audio_paths: string[];
  image_paths: string[];
  lyrics_en?: string;
  lyrics_ko?: string;
  track_title?: string;
}

export interface YoutubeStatus {
  client_id: string;
  client_secret_set: boolean;
  client_secret_masked: string;
  connected: boolean;
  channel_title?: string | null;
  channel_id?: string | null;
  redirect_uri: string;
  redirect_host?: string;
  redirect_uris_hint?: string[];
}

export interface YoutubeUploadResult {
  video_id: string;
  title: string;
  privacy_status: string;
  url: string;
  moved_to?: string;
  file_name?: string;
  file_size_mb?: number;
  duration_sec?: number | null;
  thumbnail_error?: string | null;
}

export interface YoutubeUploadJob {
  id: string;
  status: "running" | "completed" | "failed";
  bytes_sent: number;
  size_bytes: number;
  percent: number;
  file_name?: string;
  result?: YoutubeUploadResult | null;
  error?: string | null;
}

export interface YoutubePublishResult {
  video_id: string;
  privacy_status: string;
  url: string;
  moved_to?: string;
}

export interface EditorConfig {
  version: number;
  mode: "single" | "playlist";
  project_paths: string[];
  last_step?: number;
  thumbnail: {
    layout: "canvas";
    title?: string;
    subtitle?: string;
    background: {
      image: string;
      mode: string;
      dim: number;
    };
    template_id?: string;
    boxes: Array<{
      id: string;
      text: string;
      x: number;
      y: number;
      w: number;
      h: number;
      font_size: number;
      bold: boolean;
      color: string;
      align: "left" | "center" | "right";
      fill?: string;
    }>;
  };
  subtitle: {
    mode: "ko" | "en" | "both";
    margin_v_en: number;
    margin_v_ko: number;
    font_size_en: number;
    font_size_ko: number;
    font_size_title: number;
    title_intro_sec: number;
    track_header_enabled: boolean;
    track_header_y: number;
    title_color: string;
  };
  overlay: {
    eq_bar_enabled: boolean;
    eq_bar_style: "none" | "bars" | "thin" | "thick" | "spaced" | "line" | "mirror" | "dots";
    eq_bar_x: number;
    eq_bar_y: number;
    eq_bar_w: number;
    eq_bar_h: number;
    eq_bar_color: string;
    eq_bar_align?: "bottom_center" | "custom";
  };
  remaster: {
    low_db: number;
    high_db: number;
    stereo_width: number;
    strip_fingerprint: boolean;
  };
  youtube: {
    title: string;
    subtitle: string;
    description_ko: string;
    description_en: string;
    include_lyrics_in_description: boolean;
    tags: string[];
    hashtags: string;
    tracks: Array<{
      index?: number;
      title: string;
      start_sec: number;
      duration_sec?: number;
      manual?: boolean;
    }>;
    description_locked: boolean;
  };
  /** 곡별 할당 스타일 프리셋 (프리셋 라이브러리 id) */
  style_preset_id?: string;
}

export interface EditorConfigResponse {
  config: EditorConfig;
  assets: {
    track_title?: string;
    has_audio: boolean;
    has_image: boolean;
    has_lyrics_en: boolean;
    has_lyrics_ko: boolean;
    image_paths: string[];
    album_images?: Array<{ path: string; label: string; folder: string; name: string; rel: string }>;
  };
}

export interface DescBlockDef {
  id: string;
  label: string;
  hint: string;
}

export interface ChannelBrand {
  channel_name: string;
  source_url: string;
  copyright_line: string;
  default_tags: string[];
  default_hashtags: string;
  watermark_enabled: boolean;
  watermark_label: string;
  watermark_pos: "top_left" | "top_right" | "bottom_left" | "bottom_right" | "custom";
  watermark_x: number;
  watermark_y: number;
  footer_enabled: boolean;
  desc_blocks: string[];
  custom_desc_block: string;
  icon_url?: string;
  available_blocks?: DescBlockDef[];
  selected_blocks?: string[];
}

export interface YoutubeDraft {
  mode: string;
  title: string;
  subtitle: string;
  description_ko: string;
  description_en: string;
  include_lyrics_in_description: boolean;
  tags: string[];
  hashtags: string;
  tracks: EditorConfig["youtube"]["tracks"];
  description_locked: boolean;
  description_preview: string;
  auto_block?: string;
  char_count: number;
}

export interface FingerprintCheck {
  ok: boolean | null;
  checks: Array<{ file: string; has_suno: boolean; path: string }>;
}

export interface YoutubeProjectMeta {
  video_id?: string | null;
  meta?: {
    video_id: string;
    title: string;
    privacy_status: string;
    url: string;
    uploaded_at: string;
  } | null;
  upload_file?: {
    name: string;
    path: string;
    size_bytes: number;
    size_mb: number;
    duration_sec?: number | null;
  } | null;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  category?: string;
  emoji?: string;
  tags?: string;
  genre?: string;
  mood?: string;
  tempo_bpm?: number;
  vocal_style?: string;
  instruments?: string;
  production_style?: string;
  reference_artists?: string;
}

export interface InstrumentDetail {
  name: string;
  name_en?: string;
  role?: string;
  tone?: string;
  texture?: string;
  notes?: string;
}

export interface MusicalTraits {
  genre?: string;
  mood?: string;
  tempo_bpm?: number;
  key_signature?: string;
  vocal_style?: string;
  production_style?: string;
  reference_artists?: string;
  description?: string;
}

export interface PromptBuilderTemplate {
  preset_id?: string;
  profile_id?: number;
  name?: string;
  emoji?: string;
  category?: string;
  musical_traits: MusicalTraits;
  instruments: InstrumentDetail[];
  draft_prompt_english: string;
}

export interface FavoriteTrack {
  id: number;
  title: string;
  artist?: string;
  lyrics?: string;
  notes?: string;
  audio_path?: string;
  analysis_json?: string;
  suno_prompt?: string;
  created_at: string;
  updated_at: string;
}

export interface SearchResult {
  type: "album" | "song";
  id: number;
  title: string;
  subtitle?: string;
  album_id?: number;
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  // Settings
  getSettings: () => request<AppSettings>("/settings"),
  updateSettings: (data: Record<string, string>) =>
    request<AppSettings>("/settings", { method: "PATCH", body: JSON.stringify(data) }),
  listProviders: () => request<AIProvider[]>("/providers"),
  listProviderModels: async (provider: string): Promise<{ provider: string; models: AIModelOption[] }> => {
    try {
      return await request<{ provider: string; models: AIModelOption[] }>(
        `/providers/${provider}/models`,
      );
    } catch {
      const legacy = await request<{ id: string; name: string }[]>(
        `/models?provider=${encodeURIComponent(provider)}`,
      );
      return {
        provider,
        models: legacy.map((m) => ({ id: m.id, name: m.name })),
      };
    }
  },
  testProviderApi: (provider: string) =>
    request<{ ok: boolean; model_count: number }>(`/settings/test-api/${provider}`, {
      method: "POST",
    }),
  testApiKey: () =>
    request<{ ok: boolean; model_count: number }>("/settings/test-api", { method: "POST" }),

  // Search
  search: (q: string) =>
    request<SearchResult[]>(`/search?q=${encodeURIComponent(q)}`),

  // Profiles
  listProfiles: () => request<MusicProfile[]>("/profiles"),
  getActiveProfile: () => request<MusicProfile | null>("/profiles/active"),
  getProfile: (id: number) => request<MusicProfile>(`/profiles/${id}`),
  createProfile: (data: Partial<MusicProfile>) =>
    request<MusicProfile>("/profiles", { method: "POST", body: JSON.stringify(data) }),
  updateProfile: (id: number, data: Partial<MusicProfile>) =>
    request<MusicProfile>(`/profiles/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteProfile: (id: number) =>
    request(`/profiles/${id}`, { method: "DELETE" }),
  activateProfile: (id: number) =>
    request<MusicProfile>(`/profiles/${id}/activate`, { method: "POST" }),
  duplicateProfile: (id: number) =>
    request<MusicProfile>(`/profiles/${id}/duplicate`, { method: "POST" }),
  applyProfileToAlbum: (profileId: number, albumId: number) =>
    request(`/profiles/${profileId}/apply-to-album/${albumId}`, { method: "POST" }),

  // Presets
  listPresets: (category?: string) =>
    request<Preset[]>(category ? `/presets?category=${encodeURIComponent(category)}` : "/presets"),
  listPresetCategories: () => request<string[]>("/presets/categories"),
  loadPreset: (id: string) =>
    request<MusicProfile>(`/presets/${id}/load`, { method: "POST" }),
  applyPreset: (id: string) =>
    request<{ profile_id: number; name: string }>(`/presets/${id}/apply`, { method: "POST" }),

  // Preset instrument template (internal — used when loading album style instruments)
  getProfileBuilder: (profileId: number) =>
    request<PromptBuilderTemplate>(`/profiles/${profileId}/builder`),

  // Albums
  listAlbums: () => request<Album[]>("/albums"),
  getAlbum: (id: number) => request<AlbumDetail>(`/albums/${id}`),
  createAlbum: (data: Partial<Album>) =>
    request<Album>("/albums", { method: "POST", body: JSON.stringify(data) }),
  updateAlbum: (id: number, data: Partial<Album>) =>
    request<Album>(`/albums/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteAlbum: (id: number) =>
    request(`/albums/${id}`, { method: "DELETE" }),

  // Songs
  createSong: (data: {
    album_id: number;
    title: string;
    track_number?: number;
    theme?: string;
    tags?: string;
    reference_song_id?: number;
  }) =>
    request<Song>("/songs", { method: "POST", body: JSON.stringify(data) }),
  updateSong: (id: number, data: Partial<Song>) =>
    request<Song>(`/songs/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteSong: (id: number) =>
    request(`/songs/${id}`, { method: "DELETE" }),
  getSong: (id: number) => request<Song>(`/songs/${id}`),

  // A/B Variants
  listVariants: (songId: number, taskType?: string) =>
    request<GenerationVariant[]>(
      `/songs/${songId}/variants${taskType ? `?task_type=${taskType}` : ""}`
    ),
  generateAB: (songId: number, taskType: string, count = 2) =>
    request<GenerationVariant[]>("/generate/ab", {
      method: "POST",
      body: JSON.stringify({ song_id: songId, task_type: taskType, count }),
    }),
  applyVariant: (songId: number, variantId: number) =>
    request(`/songs/${songId}/variants/${variantId}/apply`, { method: "POST" }),

  // Queue
  listQueue: () => request<QueueJob[]>("/queue"),
  getQueueJob: (id: number) => request<QueueJob>(`/queue/${id}`),
  cancelQueueJob: (id: number) =>
    request<QueueJob>(`/queue/${id}/cancel`, { method: "POST" }),

  // Generation
  generateLyrics: (
    songId: number,
    additional?: string,
    language: "ko" | "en" = "ko",
    lyricsKo?: string
  ) =>
    request<GenerationResult>("/generate/lyrics", {
      method: "POST",
      body: JSON.stringify({
        song_id: songId,
        additional_instructions: additional,
        language,
        ...(lyricsKo !== undefined ? { lyrics_ko: lyricsKo } : {}),
      }),
    }),
  generatePrompt: (songId: number, additional?: string, instrumentSettings?: string) =>
    request<GenerationResult>("/generate/prompt", {
      method: "POST",
      body: JSON.stringify({
        song_id: songId,
        additional_instructions: additional,
        ...(instrumentSettings !== undefined ? { instrument_settings: instrumentSettings } : {}),
      }),
    }),
  generateInstruments: (songId: number, additional?: string, useAi = true) =>
    request<GenerationResult>("/generate/instruments", {
      method: "POST",
      body: JSON.stringify({
        song_id: songId,
        additional_instructions: additional,
        use_ai: useAi,
      }),
    }),
  getSongInstrumentsPreset: (songId: number) =>
    request<SongInstrumentSettings>(`/songs/${songId}/instruments/preset`),
  applyPresetToSong: (songId: number, profileId: number | null) =>
    request<SongInstrumentSettings>(`/songs/${songId}/apply-preset`, {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),
  applySongInstrumentsFromPreset: async (songId: number) => {
    try {
      return await request<SongInstrumentSettings>(
        `/songs/${songId}/instruments/from-preset`,
        { method: "POST" },
      );
    } catch (err) {
      if (!isApiUnavailableError(err)) throw err;
      const song = await request<Song>(`/songs/${songId}`);
      const album = await request<{ music_profile_id?: number }>(`/albums/${song.album_id}`);
      const profileId = album.music_profile_id;
      if (!profileId) {
        throw new Error("앨범에 스타일 프리셋이 연결되어 있지 않습니다.");
      }
      const builder = await request<PromptBuilderTemplate>(`/profiles/${profileId}/builder`);
      const data = builderToInstrumentSettings(builder);
      const json = JSON.stringify(data, null, 2);
      await request<Song>(`/songs/${songId}`, {
        method: "PATCH",
        body: JSON.stringify({ instrument_settings: json }),
      });
      return data;
    }
  },
  saveSongInstruments: async (songId: number, data: SongInstrumentSettings) => {
    try {
      return await request<SongInstrumentSettings>(`/songs/${songId}/instruments`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
    } catch (err) {
      if (!isApiUnavailableError(err)) throw err;
      const json = JSON.stringify(data, null, 2);
      await request<Song>(`/songs/${songId}`, {
        method: "PATCH",
        body: JSON.stringify({ instrument_settings: json }),
      });
      return data;
    }
  },
  generateSimilar: (data: {
    reference_song_id: number;
    album_id: number;
    title: string;
    theme?: string;
  }) =>
    request<Song>("/generate/similar", { method: "POST", body: JSON.stringify(data) }),
  generateAlbumTracks: (albumId: number, themes?: string[]) =>
    request<QueueJob>("/generate/album-tracks", {
      method: "POST",
      body: JSON.stringify({ album_id: albumId, track_themes: themes, use_queue: true }),
    }),
  generateAlbumLyrics: (albumId: number) =>
    request<{ updated: number; total: number; model_used: string }>(
      "/generate/album-lyrics",
      {
        method: "POST",
        body: JSON.stringify({ album_id: albumId }),
      }
    ),
  repairAlbumLyrics: (albumId: number) =>
    request<{ updated: number; total: number; recovered_tracks: number }>(
      "/generate/repair-album-lyrics",
      {
        method: "POST",
        body: JSON.stringify({ album_id: albumId }),
      }
    ),

  // Favorite tracks
  listFavoriteTracks: () => request<FavoriteTrack[]>("/favorite-tracks"),
  createFavoriteTrack: (data: Partial<FavoriteTrack>) =>
    request<FavoriteTrack>("/favorite-tracks", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateFavoriteTrack: (id: number, data: Partial<FavoriteTrack>) =>
    request<FavoriteTrack>(`/favorite-tracks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteFavoriteTrack: (id: number) =>
    request(`/favorite-tracks/${id}`, { method: "DELETE" }),
  analyzeFavoriteTrack: (id: number) =>
    request<{ analysis: Record<string, unknown>; suno_prompt: string }>(
      `/favorite-tracks/${id}/analyze`,
      { method: "POST" }
    ),
  createProfileFromTrack: (id: number) =>
    request<{ profile_id: number }>(`/favorite-tracks/${id}/create-profile`, {
      method: "POST",
    }),

  uploadAudio: async (songId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/songs/${songId}/upload-audio`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error("업로드 실패");
    return res.json();
  },

  uploadSongImage: async (songId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/songs/${songId}/upload-image`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error("이미지 업로드 실패");
    return res.json();
  },

  songCoverUrl: (songId: number) => `${API_BASE}/songs/${songId}/cover-image`,

  uploadFavoriteAudio: async (trackId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/favorite-tracks/${trackId}/upload-audio`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error("업로드 실패");
    return res.json();
  },

  exportBackup: () => {
    window.open(`${API_BASE}/backup/export`, "_blank");
  },

  importBackup: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/backup/import`, { method: "POST", body: form });
    if (!res.ok) throw new Error("복원 실패");
    return res.json();
  },

  // Pipeline / Studio
  getPipelineStatus: () => request<PipelineStatus>("/pipeline/status"),
  getImageModels: () =>
    request<{ ok: boolean; models: { id: string; name: string }[] }>(
      "/editor/album-thumbs/0/image-models"
    ),
  getPipelineConfig: () => request<PipelineConfig>("/pipeline/config"),
  updatePipelineConfig: (data: Partial<PipelineConfig> & { work_root?: string }) =>
    request<PipelineConfig>("/pipeline/config", {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  initPipelineFolders: () =>
    request<{
      work_root: string;
      created: string[];
      migrated: { from: string; to: string }[];
      removed_legacy: string[];
      legacy_remaining: string[];
      stages: WorkflowStage[];
    }>("/pipeline/init-folders", { method: "POST" }),
  getPipelineStages: () =>
    request<{ work_root: string; stages: WorkflowStage[] }>("/pipeline/stages"),
  browsePipeline: (path = "") =>
    request<BrowseResult>(`/pipeline/browse?path=${encodeURIComponent(path)}`),
  getProjectAssets: (path: string) =>
    request<ProjectAssets>(`/pipeline/assets?path=${encodeURIComponent(path)}`),
  pipelineMediaUrl: (filePath: string) =>
    `${API_BASE}/pipeline/media?path=${encodeURIComponent(filePath)}`,
  openPipelineFolder: (path: string) =>
    request<{ ok: boolean; path: string }>("/pipeline/open-folder", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  movePipelineStage: (projectPath: string, toStage: string) =>
    request<{ path: string; stage: string }>("/pipeline/move-stage", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, to_stage: toStage }),
    }),
  exportSongToPipeline: (songId: number, stageId = "music", language: "ko" | "en" = "en") =>
    request<{ path: string; pipeline_path: string }>("/pipeline/export-song", {
      method: "POST",
      body: JSON.stringify({ song_id: songId, stage_id: stageId, language }),
    }),
  runPipeline: (
    projectPath: string,
    targetStage = "review",
    songId?: number,
    projectPaths?: string[],
  ) =>
    request<{ job_id: number; message: string; path?: string }>("/pipeline/run", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        target_stage: targetStage,
        song_id: songId,
        project_paths: projectPaths,
      }),
    }),
  runPlaylistPipeline: (data: {
    project_paths: string[];
    title?: string;
    subtitle?: string;
    target_stage?: string;
  }) =>
    request<{
      job_id: number;
      path: string;
      message: string;
    }>("/pipeline/run-playlist", {
      method: "POST",
      body: JSON.stringify({
        project_paths: data.project_paths,
        title: data.title,
        subtitle: data.subtitle,
        target_stage: data.target_stage ?? "review",
      }),
    }),

  // YouTube
  getYoutubeStatus: () => request<YoutubeStatus>("/youtube/status"),
  saveYoutubeCredentials: (data: {
    youtube_client_id?: string;
    youtube_client_secret?: string;
    redirect_host?: "localhost" | "127.0.0.1";
  }) =>
    request<YoutubeStatus>("/youtube/credentials", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getYoutubeAuthUrl: () => request<{ auth_url: string }>("/youtube/auth-url"),
  disconnectYoutube: () => request<{ ok: boolean }>("/youtube/disconnect", { method: "POST" }),
  startYoutubeUpload: (
    projectPath: string,
    options?: {
      privacyStatus?: "private" | "unlisted" | "public";
      moveToStage?: string | null;
      title?: string;
      description?: string;
      tags?: string[];
    }
  ) =>
    request<YoutubeUploadJob>("/youtube/upload", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        privacy_status: options?.privacyStatus ?? "private",
        move_to_stage: options?.moveToStage ?? null,
        title: options?.title,
        description: options?.description,
        tags: options?.tags,
      }),
    }),
  getYoutubeUploadJob: (jobId: string) => request<YoutubeUploadJob>(`/youtube/upload/${jobId}`),

  /* in-flight upload tracker — prevent duplicate uploads of the same project */
  _uploadingProject: "",
  uploadToYoutube: async (
    projectPath: string,
    options?: {
      privacyStatus?: "private" | "unlisted" | "public";
      moveToStage?: string | null;
      title?: string;
      description?: string;
      tags?: string[];
    },
    onProgress?: (job: YoutubeUploadJob) => void
  ) => {
    /* prevent duplicate upload of the same project */
    if (api._uploadingProject === projectPath) {
      throw new Error("이미 업로드 중입니다");
    }
    api._uploadingProject = projectPath;
    try {
      const started = await api.startYoutubeUpload(projectPath, options);
      onProgress?.(started);
      let job = started;
      while (job.status === "running") {
      await new Promise((r) => setTimeout(r, 400));
      job = await api.getYoutubeUploadJob(job.id);
      onProgress?.(job);
    }
    if (job.status === "failed") {
      throw new Error(job.error || "업로드 실패");
    }
    if (!job.result?.url) {
      throw new Error("업로드 결과를 받지 못했습니다");
    }
    return job.result;
  } finally {
    api._uploadingProject = "";
  }
  },
  publishOnYoutube: (projectPath: string, videoId?: string) =>
    request<YoutubePublishResult>("/youtube/publish", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        video_id: videoId,
        move_to_stage: null,
      }),
    }),
  getYoutubeProjectMeta: (path: string) =>
    request<YoutubeProjectMeta>(`/youtube/project-meta?path=${encodeURIComponent(path)}`),

  // Video Editor (8-step studio)
  getBrand: () => request<ChannelBrand>(`/editor/brand`),
  saveBrand: (data: Partial<ChannelBrand>) =>
    request<ChannelBrand>(`/editor/brand`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  uploadBrandIcon: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ ok: boolean; icon_url: string }>(`/editor/brand/icon`, {
      method: "POST",
      body: fd,
    });
  },
  resetBrandIcon: () =>
    request<{ ok: boolean; removed: boolean }>(`/editor/brand/icon`, { method: "DELETE" }),
  getEditorConfig: (path: string) =>
    request<EditorConfigResponse>(`/editor/config?path=${encodeURIComponent(path)}`),
  saveEditorConfig: (path: string, data: Partial<EditorConfig>) =>
    request<{ config: EditorConfig }>(`/editor/config?path=${encodeURIComponent(path)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  listStylePresets: () =>
    request<{ presets: { id: string; name: string; created_at: string }[] }>(
      `/editor/style-presets`,
    ),
  createStylePreset: (path: string, name: string, config: Partial<EditorConfig>) =>
    request<{ preset: { id: string; name: string; created_at: string } }>(
      `/editor/style-presets?path=${encodeURIComponent(path)}`,
      { method: "POST", body: JSON.stringify({ name, config }) },
    ),
  applyStylePreset: (path: string, presetId: string) =>
    request<{ config: EditorConfig }>(
      `/editor/style-presets/apply?path=${encodeURIComponent(path)}`,
      { method: "POST", body: JSON.stringify({ preset_id: presetId }) },
    ),
  deleteStylePreset: (presetId: string) =>
    request<{ ok: boolean; remaining: number }>(`/editor/style-presets/${presetId}`, {
      method: "DELETE",
    }),
  renderEditorThumbnail: async (path: string, thumbnail?: EditorConfig["thumbnail"]) => {
    const res = await fetch(
      `${API_BASE}/editor/preview/thumbnail/render?path=${encodeURIComponent(path)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thumbnail }),
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof err.detail === "string" ? err.detail : "미리보기 실패");
    }
    return res.blob();
  },
  editorThumbnailPreviewUrl: (path: string) =>
    `${API_BASE}/editor/preview/thumbnail?path=${encodeURIComponent(path)}&t=${Date.now()}`,
  editorSubtitlePreviewUrl: (path: string) =>
    `${API_BASE}/editor/preview/subtitle?path=${encodeURIComponent(path)}&t=${Date.now()}`,
  editorCoverFrameUrl: (path: string) =>
    `${API_BASE}/editor/preview/cover-frame?path=${encodeURIComponent(path)}&t=${Date.now()}`,
  editorAudioPreviewUrl: (path: string) =>
    `${API_BASE}/editor/preview/audio?path=${encodeURIComponent(path)}&t=${Date.now()}`,
  editorVideoUrl: (path: string, preview = false) =>
    `${API_BASE}/editor/video?path=${encodeURIComponent(path)}&preview=${preview ? "1" : "0"}`,
  renderEditorPreviewVideo: (path: string) =>
    request<{ ok: boolean; path: string; duration_sec: number }>(
      `/editor/preview/video?path=${encodeURIComponent(path)}`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  saveEditorThumbnail: (path: string, thumbnail?: EditorConfig["thumbnail"]) =>
    request<{ ok: boolean; path: string; config?: EditorConfig }>(
      `/editor/preview/thumbnail/save?path=${encodeURIComponent(path)}`,
      {
        method: "POST",
        body: JSON.stringify({ thumbnail }),
      }
    ),
  getEditorFingerprintCheck: (path: string) =>
    request<FingerprintCheck>(`/editor/fingerprint-check?path=${encodeURIComponent(path)}`),
  getYoutubeDraft: (path: string) =>
    request<YoutubeDraft>(`/editor/youtube-draft?path=${encodeURIComponent(path)}`),
  saveYoutubeDraft: (path: string, data: Partial<YoutubeDraft>) =>
    request<{ ok: boolean; description: string; char_count: number; auto_block?: string }>(
      `/editor/youtube-draft?path=${encodeURIComponent(path)}`,
      { method: "PUT", body: JSON.stringify(data) }
    ),
  regenerateYoutubeChapters: (projectPath: string, projectPaths: string[]) =>
    request<{ tracks: EditorConfig["youtube"]["tracks"] }>("/editor/youtube-draft/regenerate-chapters", {
      method: "POST",
      body: JSON.stringify({ project_path: projectPath, project_paths: projectPaths }),
    }),
};

export function formatSunoCopy(song: Song): string {
  const parts = [];
  if (song.suno_prompt) parts.push(`[Style]\n${song.suno_prompt}`);
  const lyricsText = song.lyrics_en || song.lyrics_ko || song.lyrics;
  if (lyricsText) parts.push(`[Lyrics]\n${lyricsText}`);
  if (song.instrument_settings) parts.push(`[Instruments]\n${song.instrument_settings}`);
  return parts.join("\n\n");
}

// ---------------------------------------------------------------------------
// Whick 라이선스·API키 (2026-09-08 API키 전환)
// ---------------------------------------------------------------------------

export interface WhickLicenseStatus {
  state: "valid" | "grace" | "expired" | "none";
  email?: string;
  has_api_key?: boolean;
  expired_at?: string | null;
  [k: string]: unknown;
}

export const licenseApi = {
  /** 라이선스·API키 상태 */
  status: () => request<WhickLicenseStatus>("/license/status"),
  /** whick.org 내 계정 → API키 발급 후 붙여넣어 활성화 */
  activateWithApiKey: (apiKey: string) =>
    request<WhickLicenseStatus>("/license/activate-api-key", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    }),
  /** 보관된 API키 재검증 (작업 게이트와 동일 기준) */
  verifyKey: () => request<Record<string, unknown>>("/license/verify-key", { method: "POST" }),
  /** 로컬 활성 해제 (기기 이전 전 웹에서 해지 권장) */
  deactivate: () => request<{ state: string }>("/license/deactivate", { method: "POST" }),
};

// ---------------------------------------------------------------------------
// 업데이트 체크 (2026-09-09 — whick.org 채널, 기동 시 1회 확인)
// ---------------------------------------------------------------------------

export interface UpdateInfo {
  version: string;
  update: {
    version: string;
    current: string;
    notes?: string;
    download_url?: string;
  } | null;
}

export const updateApi = {
  /** 현재 버전 + 새 버전 메타데이터 (새 버전 없으면 update: null) */
  check: () => request<UpdateInfo>("/version"),
};

// ---------------------------------------------------------------------------
// 앨범 썸네일 3종 AI 생성 (2026-09-09 — 유튜브 Test&Compare 대비 3변형)
// ---------------------------------------------------------------------------

export interface AlbumThumbFile {
  variant: "A" | "B" | "C";
  path: string;
  ready: boolean;
  url?: string;
}

export interface AlbumThumbsStatus {
  ok: boolean;
  files: AlbumThumbFile[];
  dir: string;
}

export interface AlbumThumbsResult extends AlbumThumbsStatus {
  provider?: string;
  model?: string;
  prompts?: string[];
}

export interface SongImageStatus {
  song_id: number;
  track: number;
  title: string;
  ready: boolean;
  url: string;
}

export const songImagesApi = {
  /** 곡별 배경 이미지 생성 현황 */
  list: (albumId: number) =>
    request<{ ok: boolean; songs: SongImageStatus[] }>(`/editor/song-images/${albumId}`),
  /** 곡 배경 이미지 일괄 생성 (song_ids 미지정 시 앨범 전체) */
  generate: (
    albumId: number,
    options?: { song_ids?: number[]; provider?: string; model?: string },
  ) =>
    request<{ ok: boolean; generated: { song_id: number; track: number; prompt: string }[]; errors: { song_id?: number; track?: number; error?: string }[]; total: number }>(
      `/editor/song-images/${albumId}/generate`,
      { method: "POST", body: JSON.stringify(options ?? {}) },
    ),
};

export const albumThumbsApi = {
  /** 3종 생성 현황 */
  list: (albumId: number) =>
    request<AlbumThumbsStatus>(`/editor/album-thumbs/${albumId}`),
  /** 이미지 프롬프트 3개만 생성 (미리보기) */
  makePrompts: (albumId: number) =>
    request<{ ok: boolean; prompts: string[] }>(`/editor/album-thumbs/${albumId}/prompts`, {
      method: "POST",
    }),
  /** 썸네일 3장 AI 생성 (google gemini / openai gpt-image) */
  generate: (albumId: number, options?: { provider?: string; model?: string; prompts?: string[] }) =>
    request<AlbumThumbsResult>(`/editor/album-thumbs/${albumId}/generate`, {
      method: "POST",
      body: JSON.stringify(options ?? {}),
    }),
  thumbnailFileUrl: (albumId: number, variant: "A" | "B" | "C") =>
    `${API_BASE}/editor/album-thumbs/${albumId}/file/${variant}?t=${Date.now()}`,
  /** 생성본을 곡 thumbnail.jpg로 적용 (projectPath 미지정 시 첫 곡 자동 선택) */
  apply: (albumId: number, variant: "A" | "B" | "C", projectPath?: string) =>
    request<{ ok: boolean; path: string; applied_to?: string }>(
      `/editor/album-thumbs/${albumId}/apply/${variant}${projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : ""}`,
      { method: "POST" }
    ),
};
