import { builderToInstrumentSettings, isApiUnavailableError } from "./lib/instruments";

const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === "string" ? err.detail : "요청 실패");
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
}

export interface YoutubePublishResult {
  video_id: string;
  privacy_status: string;
  url: string;
  moved_to?: string;
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
  runPipeline: (projectPath: string, targetStage = "review", songId?: number) =>
    request<{ job_id: number; message: string }>("/pipeline/run", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        target_stage: targetStage,
        song_id: songId,
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
  uploadToYoutube: (
    projectPath: string,
    privacyStatus: "private" | "unlisted" | "public" = "private",
    moveToStage?: string | null
  ) =>
    request<YoutubeUploadResult>("/youtube/upload", {
      method: "POST",
      body: JSON.stringify({
        project_path: projectPath,
        privacy_status: privacyStatus,
        move_to_stage: moveToStage ?? null,
      }),
    }),
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
};

export function formatSunoCopy(song: Song): string {
  const parts = [];
  if (song.suno_prompt) parts.push(`[Style]\n${song.suno_prompt}`);
  const lyricsText = song.lyrics_en || song.lyrics_ko || song.lyrics;
  if (lyricsText) parts.push(`[Lyrics]\n${lyricsText}`);
  if (song.instrument_settings) parts.push(`[Instruments]\n${song.instrument_settings}`);
  return parts.join("\n\n");
}
