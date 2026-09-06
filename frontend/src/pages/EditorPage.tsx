import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  BrowseEntry,
  ChannelBrand,
  EditorConfig,
  EditorConfigResponse,
  YoutubeDraft,
  YoutubeProjectMeta,
  YoutubeUploadJob,
} from "../api";
import ThumbnailCanvasEditor, { newTextBox, type ThumbCanvasState } from "../components/ThumbnailCanvasEditor";
import {
  THUMB_TEMPLATE_IDS,
  THUMB_TEMPLATE_LABELS,
  applyTemplate,
  currentTemplateId,
  trackNamesFromPaths,
  type ThumbTemplateId,
} from "../lib/thumbnailTemplates";
import whickMark from "../assets/whick-shellphone.jpg";

const THUMB_COLOR_PRESETS = [
  { id: "white", label: "흰색", color: "#FFFFFF" },
  { id: "gold", label: "골드", color: "#E8C896" },
  { id: "ivory", label: "아이보리", color: "#F5F5F5" },
  { id: "gray", label: "연회색", color: "#D2D2DA" },
  { id: "cream", label: "크림", color: "#F0EDE8" },
  { id: "dark", label: "다크", color: "#1A1A1E" },
] as const;

const STEPS = [
  "곡 선택",
  "썸네일",
  "자막",
  "리마스터",
  "영상 인코딩",
  "유튜브 설명",
  "업로드",
] as const;

const SESSION_KEY = "suno_helper_editor_session";

function clampEditorStep(n: number) {
  const raw = Math.max(1, Number(n) || 1);
  const mapped = ({ 8: 6, 9: 7 } as Record<number, number>)[raw] ?? raw;
  return Math.min(STEPS.length, mapped);
}

function pathsFromSearch(params: URLSearchParams): string[] {
  const many = params.get("paths");
  if (many) return many.split("|").map((s) => s.trim()).filter(Boolean);
  const one = params.get("path");
  return one ? [one] : [];
}

/**
 * 프로젝트 로드 실패가 "폴더가 정말 없음"인지 판별.
 * 백엔드가 "프로젝트 폴더가 아닙니다"(400)를 반환할 때만 폴더 문제로 간주하고,
 * 네트워크 오류·서버 재시작(빈 응답, Failed to fetch 등)은 일시적 오류로 재시도 대상이 된다.
 */
function isStaleProjectError(err: unknown): boolean {
  return err instanceof Error && err.message.includes("프로젝트 폴더가 아닙니다");
}

function readEditorSession(): { paths: string[]; step: number } | null {
  try {
    const data = JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
    if (!data || !Array.isArray(data.paths) || data.paths.length === 0) return null;
    return {
      paths: data.paths.map(String).filter(Boolean),
      step: clampEditorStep(data.step),
    };
  } catch {
    return null;
  }
}

function writeEditorSession(paths: string[], step: number) {
  if (!paths.length) {
    localStorage.removeItem(SESSION_KEY);
    return;
  }
  localStorage.setItem(SESSION_KEY, JSON.stringify({ paths, step }));
}

const SUB_MODE_LABELS: Record<"ko" | "en" | "both", string> = {
  ko: "한글만",
  en: "영어만",
  both: "영어 위 / 한글 아래",
};

const ASS_PLAY_W = 2560;
const ASS_PLAY_H = 1440;
const ASS_MARGIN_LR = 80;
const ASS_OUTLINE = 3;
const ASS_FONT = '"Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif';

function assFontCqh(size: number): string {
  return `${(size / ASS_PLAY_H) * 100}cqh`;
}

function assOverlayBox() {
  const side = `${(ASS_MARGIN_LR / ASS_PLAY_W) * 100}%`;
  return {
    left: side,
    right: side,
    fontFamily: ASS_FONT,
    lineHeight: 1 as const,
    WebkitTextStroke: `${(ASS_OUTLINE / ASS_PLAY_H) * 100}cqh rgba(0,0,0,0.82)`,
  };
}
const VIDEO_W = 1920;
const VIDEO_H = 1080;
const DEFAULT_OVERLAY = {
  eq_bar_enabled: false,
  eq_bar_style: "none" as const,
  eq_bar_x: 460,
  eq_bar_y: 980,
  eq_bar_w: 1000,
  eq_bar_h: 80,
  eq_bar_color: "#FFFFFF",
  eq_bar_align: "bottom_center" as "bottom_center" | "custom",
};
const EQ_STYLES = [
  { id: "none", label: "없음", n: 0 },
  { id: "bars", label: "둥근 막대", n: 28 },
  { id: "thin", label: "가는 막대", n: 32 },
  { id: "thick", label: "굵은 막대", n: 16 },
  { id: "spaced", label: "띄운 막대", n: 22 },
  { id: "line", label: "라인", n: 28 },
  { id: "mirror", label: "미러", n: 18 },
  { id: "dots", label: "도트", n: 18 },
] as const;

function trackHeaderSample(projectPath: string): string {
  const parts = projectPath.replace(/\\/g, "/").split("/").filter(Boolean);
  const folder = parts[parts.length - 1] || "Song";
  const album = parts[parts.length - 2] || "";
  const num = folder.match(/^(\d{1,2})/);
  const idx = num ? num[1].padStart(2, "0") : "01";
  const name = folder.replace(/^(?:track\s*)?\d{1,2}(?:\.\d+)?[.\s_\-]+/i, "").trim() || folder;
  return album ? `Track ${idx}. ${name}  |  ${album}` : `Track ${idx}. ${name}`;
}

function albumNameFromPath(absPath: string): string {
  const parts = absPath.replace(/\\/g, "/").split("/").filter(Boolean);
  if (parts.length < 2) return "";
  const parent = parts[parts.length - 2];
  if (/^\d{2}_/.test(parent)) return "";
  return parent.replace(/^\d+[\s._-]+/, "").trim() || parent;
}

function relPath(workRoot: string, absPath: string): string {
  const root = workRoot.replace(/\\/g, "/").replace(/\/$/, "");
  const p = absPath.replace(/\\/g, "/");
  if (p.toLowerCase().startsWith(root.toLowerCase() + "/")) {
    return p.slice(root.length + 1);
  }
  return absPath;
}

function fmtDuration(sec?: number | null) {
  if (!sec || sec < 1) return "";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}시간 ${m}분`;
  return `${m}분`;
}

export default function EditorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const restored = useRef(readEditorSession());
  const urlHadStep = searchParams.has("step");
  const urlPaths = pathsFromSearch(searchParams);
  const [step, setStep] = useState(() => {
    if (urlHadStep) return clampEditorStep(Number(searchParams.get("step")));
    if (urlPaths.length && restored.current && restored.current.paths[0] === urlPaths[0]) {
      return restored.current.step;
    }
    if (!urlPaths.length && restored.current) return restored.current.step;
    return 1;
  });
  const [workRoot, setWorkRoot] = useState("");
  const [browsePath, setBrowsePath] = useState("");
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [selectedPaths, setSelectedPaths] = useState<string[]>(() => {
    if (urlPaths.length) return urlPaths;
    return restored.current?.paths ?? [];
  });
  const projectPath = selectedPaths[0] || "";
  const projectPathRef = useRef(projectPath);
  projectPathRef.current = projectPath;
  const [config, setConfig] = useState<EditorConfig | null>(null);
  const configRef = useRef<EditorConfig | null>(null);
  configRef.current = config;
  const [draft, setDraft] = useState<YoutubeDraft | null>(null);
  const [previewKey, setPreviewKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [renderJobId, setRenderJobId] = useState<number | null>(null);
  const [renderEncoding, setRenderEncoding] = useState(false);
  const [renderProgress, setRenderProgress] = useState("");
  // 스타일 프리셋 (곡별)
  const [presets, setPresets] = useState<{ id: string; name: string; created_at: string }[]>([]);
  const [presetId, setPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  // 채널 브랜드 (표시용 읽기 전용 — 편집은 사용자 설정 페이지)
  const [brand, setBrand] = useState<ChannelBrand | null>(null);
  const [privacy, setPrivacy] = useState<"private" | "unlisted" | "public">("private");
  const [uploadUrl, setUploadUrl] = useState("");
  const [uploadFile, setUploadFile] = useState<NonNullable<YoutubeProjectMeta["upload_file"]> | null>(null);
  const [uploadJob, setUploadJob] = useState<YoutubeUploadJob | null>(null);
  const [fingerprintOk, setFingerprintOk] = useState<boolean | null>(null);
  const [imagePaths, setImagePaths] = useState<string[]>([]);
  const [albumImages, setAlbumImages] = useState<NonNullable<EditorConfigResponse["assets"]["album_images"]>>([]);
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [serverPreviewUrl, setServerPreviewUrl] = useState<string>("");
  const [serverPreviewKey, setServerPreviewKey] = useState(0);
  const [videoFailed, setVideoFailed] = useState(false);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [videoPlaying, setVideoPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewEncoding, setPreviewEncoding] = useState(false);
  const previewVideoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    return () => {
      if (serverPreviewUrl.startsWith("blob:")) URL.revokeObjectURL(serverPreviewUrl);
    };
  }, [serverPreviewUrl]);

  const persistSession = (paths: string[], n: number) => {
    writeEditorSession(paths, n);
    const first = paths[0];
    if (!first) return;
    api.saveEditorConfig(first, { last_step: n, project_paths: paths }).catch(() => {});
  };

  const syncSelectionParams = (paths: string[], stepOverride?: number) => {
    const p = new URLSearchParams(searchParams);
    const nextStep = stepOverride ?? step;
    p.set("step", String(nextStep));
    if (paths.length === 0) {
      p.delete("path");
      p.delete("paths");
    } else {
      p.set("path", paths[0]);
      if (paths.length > 1) p.set("paths", paths.join("|"));
      else p.delete("paths");
    }
    setSearchParams(p);
    persistSession(paths, nextStep);
  };

  const goStep = (n: number) => {
    const next = clampEditorStep(n);
    setStep(next);
    syncSelectionParams(selectedPaths, next);
  };

  const loadBrowse = useCallback(async (path: string) => {
    const data = await api.browsePipeline(path);
    setBrowsePath(data.path);
    setEntries(data.entries);
  }, []);

  const loadProject = useCallback(async (path: string, attempt = 0) => {
    if (!path) return;
    let ed: Awaited<ReturnType<typeof api.getEditorConfig>>;
    try {
      const [edRes, ytDraft] = await Promise.all([
        api.getEditorConfig(path),
        api.getYoutubeDraft(path),
      ]);
      // 응답을 기다리는 사이 사용자가 다른 곡을 선택했으면 폐기
      // (재시도 응답이 새 곡 화면을 옛 데이터로 덮어쓰는 것 방지)
      if (projectPathRef.current !== path && projectPathRef.current) return;
      ed = edRes;
      setConfig(ed.config);
      setDraft(ytDraft);
      setImagePaths(ed.assets.image_paths || []);
      setAlbumImages(ed.assets.album_images || []);
    } catch (err) {
      if (projectPathRef.current && projectPathRef.current !== path) return; // 이미 다른 곳으로 이동
      if (isStaleProjectError(err)) {
        // 폴더명 변경/삭제 등 실제로 폴더가 사라진 경우 → 선택에서 제외하고 안내
        setConfig(null);
        setSelectedPaths((prev) => {
          const next = prev.filter((p) => p !== path);
          syncSelectionParams(next);
          return next;
        });
        setMessage(
          `폴더를 불러올 수 없습니다: ${path.split(/[\\/]/).pop()} — 1단계에서 곡을 다시 선택하세요 (이름이 바뀐 폴더일 수 있습니다)`,
        );
        return;
      }
      // 서버 재시작 등 일시적 오류 → 선택을 유지하고 자동 재시도
      if (attempt < 4) {
        setMessage(
          `백엔드 서버가 준비 중입니다 — 잠시 후 자동으로 다시 시도합니다 (${attempt + 1}/4)...`,
        );
        setTimeout(() => {
          // 재시도 시점에도 사용자가 이 경로를 선택 중일 때만
          if (projectPathRef.current === path) void loadProject(path, attempt + 1);
        }, 1500);
        return;
      }
      setMessage(
        "서버에 연결할 수 없습니다. 백엔드 실행 상태를 확인한 뒤 페이지를 새로고침하세요. (곡 선택은 유지되었습니다)",
      );
      return;
    }
    setPreviewKey((k) => k + 1);
    setVideoFailed(false);
    setPreviewPlaying(false);
    setPreviewReady(false);
    setPreviewEncoding(false);
    const fp = await api.getEditorFingerprintCheck(path).catch(() => null);
    setFingerprintOk(fp?.ok ?? null);
    if (!urlHadStep) {
      const sameSession = restored.current?.paths[0] === path;
      if (!sameSession) {
        const saved = clampEditorStep(Number(ed.config.last_step) || 1);
        if (saved > 1) {
          setStep(saved);
          persistSession(ed.config.project_paths?.length ? ed.config.project_paths : [path], saved);
        }
      }
    }
    // syncSelectionParams/loadProject는 안정적인 래퍼 — 실패 시 선택 정리에 사용
  }, [urlHadStep, syncSelectionParams]);

  // loadBrowse는 안정적(의존성 없음). loadProject는 ref로 접근해
  // 재생성과 무관하게 최신 로직을 사용한다.
  const loadProjectRef = useRef(loadProject);
  loadProjectRef.current = loadProject;

  useEffect(() => {
    if (projectPath) loadProjectRef.current(projectPath);
    // projectPath가 실제로 바뀔 때만 프로젝트를 다시 로드.
    // loadProject를 의존성에 넣으면 매 렌더링마다 재실행되어
    // 6단계에서 입력 중인 유튜브 설명이 서버 값으로 덮어써진다.
  }, [projectPath]);

  // work_root 로드 + 초기 브라우징
  useEffect(() => {
    api.getPipelineStages().then((s) => {
      setWorkRoot(s.work_root);
      loadBrowse("");
    });
  }, [loadBrowse]);

  // 곡 로드 시 그 곡에 할당된 프리셋을 드롭다운에 반영
  useEffect(() => {
    setPresetId(config?.style_preset_id ?? "");
  }, [config?.style_preset_id, projectPath]);

  useEffect(() => {
    if (step !== 7 || !projectPath) return;
    const rel = workRoot ? relPath(workRoot, projectPath) : projectPath;
    api.getYoutubeProjectMeta(rel).then((m) => {
      setUploadFile(m.upload_file ?? null);
      if (m.meta?.url) setUploadUrl(m.meta.url);
    }).catch(() => setUploadFile(null));
  }, [step, projectPath, workRoot]);

  useEffect(() => {
    if (selectedPaths.length && !searchParams.get("path")) {
      syncSelectionParams(selectedPaths, step);
    }
    // 최초 진입 시 저장된 세션을 주소에 반영
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ===== 스타일 프리셋 (곡별) =====
  const refreshPresets = useCallback(async () => {
    try {
      const res = await api.listStylePresets();
      setPresets(res.presets || []);
    } catch {
      /* 프리셋 목록 실패는 치명적이지 않음 */
    }
  }, []);

  // 채널 브랜드 로드 (표시용 — 편집은 사용자 설정 페이지에서)
  const refreshBrand = useCallback(async () => {
    try {
      setBrand(await api.getBrand());
    } catch {
      /* 브랜드 로드 실패 시 기본값으로 표시 */
    }
  }, []);

  // 프리셋 목록 로드 (정의 후 실행)
  useEffect(() => {
    void refreshPresets();
  }, [refreshPresets]);

  // 브랜드 로드
  useEffect(() => {
    void refreshBrand();
  }, [refreshBrand]);

  const savePreset = async () => {
    if (!projectPath || !configRef.current || !presetName.trim()) return;
    try {
      await api.createStylePreset(projectPath, presetName.trim(), configRef.current);
      setPresetName("");
      await refreshPresets();
      setMessage(`프리셋 "${presetName.trim()}" 저장됨`);
    } catch (e) {
      setMessage(String(e));
    }
  };

  const applyPreset = async (id: string) => {
    setPresetId(id);
    if (!projectPath) return;
    if (!id) {
      // 기본 스타일(전역)로 되돌리기 — 곡에 저장된 프리셋 할당을 제거해야
      // 재진입 시 이전 프리셋이 자동 재적용되지 않는다.
      try {
        await api.saveEditorConfig(projectPath, { style_preset_id: "" });
        setConfig((c) => (c ? { ...c, style_preset_id: undefined } : c));
        setMessage("곡 프리셋 해제 — 전역 스타일을 따릅니다.");
      } catch (e) {
        setMessage(String(e));
      }
      return;
    }
    try {
      const res = await api.applyStylePreset(projectPath, id);
      setConfig(res.config);
      setMessage("프리셋 적용됨 — 저장을 눌러 확정하세요");
    } catch (e) {
      setMessage(String(e));
    }
  };
  // ===== /스타일 프리셋 =====

  const startFresh = () => {
    writeEditorSession([], 1);
    setSelectedPaths([]);
    setConfig(null);
    setDraft(null);
    setStep(1);
    setMessage("");
    setSearchParams(new URLSearchParams());
  };

  const thumbCanvas = (): ThumbCanvasState | null => {
    if (!config?.thumbnail?.boxes) return null;
    const t = config.thumbnail;
    const fallbackImg = albumImages[0]?.path || imagePaths[0] || "";
    return {
      layout: "canvas",
      template_id: t.template_id,
      background: t.background ?? { image: fallbackImg, mode: "modern", dim: 0.25 },
      boxes: t.boxes,
      title: t.title,
      subtitle: t.subtitle,
    };
  };

  const thumbImageOptions = () => {
    if (albumImages.length) return albumImages;
    return imagePaths.map((p) => {
      const name = p.split(/[/\\]/).pop() || p;
      return { path: p, label: name, folder: "현재 곡", name, rel: name };
    });
  };

  const thumbImageGroups = () => {
    const opts = thumbImageOptions();
    const groups: { folder: string; items: typeof opts }[] = [];
    const index = new Map<string, number>();
    for (const it of opts) {
      const i = index.get(it.folder);
      if (i == null) {
        index.set(it.folder, groups.length);
        groups.push({ folder: it.folder, items: [it] });
      } else {
        groups[i].items.push(it);
      }
    }
    return groups;
  };

  const matchThumbImage = (image: string) => {
    const options = thumbImageOptions();
    const key = (image || "").replace(/\\/g, "/").toLowerCase();
    return (
      options.find((o) => {
        const path = o.path.replace(/\\/g, "/").toLowerCase();
        const rel = (o.rel || "").replace(/\\/g, "/").toLowerCase();
        return path === key || rel === key || o.name.toLowerCase() === key;
      }) || null
    );
  };

  const setThumbCanvas = (canvas: ThumbCanvasState) => {
    setConfig((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        thumbnail: {
          ...prev.thumbnail,
          layout: "canvas",
          template_id: canvas.template_id,
          background: canvas.background,
          boxes: canvas.boxes,
          title: canvas.title,
          subtitle: canvas.subtitle,
        },
      };
    });
  };

  const thumbnailPayload = (): EditorConfig["thumbnail"] | null => {
    const cfg = configRef.current;
    if (!cfg?.thumbnail?.boxes?.length) return null;
    const t = cfg.thumbnail;
    return {
      ...t,
      layout: "canvas",
      template_id: t.template_id,
      background: t.background,
      boxes: t.boxes,
      title: t.title,
      subtitle: t.subtitle,
    };
  };

  const saveConfig = async (patch: Partial<EditorConfig>): Promise<boolean> => {
    if (!projectPath || !config) return false;
    setBusy(true);
    try {
      const res = await api.saveEditorConfig(projectPath, {
        ...patch,
        project_paths: selectedPaths,
        last_step: step,
      });
      persistSession(selectedPaths, step);
      setConfig(res.config);
      setMessage("저장됨");
      return true;
    } catch (e) {
      setMessage(String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveThumbnail = async () => {
    if (!projectPath) {
      setMessage("먼저 곡을 선택하세요.");
      return;
    }
    const thumbnail = thumbnailPayload();
    if (!thumbnail) {
      setMessage("저장할 썸네일이 없습니다.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.saveEditorThumbnail(projectPath, thumbnail);
      const blob = await api.renderEditorThumbnail(projectPath, thumbnail);
      if (serverPreviewUrl.startsWith("blob:")) URL.revokeObjectURL(serverPreviewUrl);
      setServerPreviewUrl(URL.createObjectURL(blob));
      setServerPreviewKey((k) => k + 1);
      setMessage(`썸네일 저장됨 → ${res.path.split(/[/\\]/).pop()}`);
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const refreshThumbPreview = async () => {
    if (!projectPath) return;
    const thumbnail = thumbnailPayload();
    if (!thumbnail) return;
    setBusy(true);
    const t0 = performance.now();
    try {
      const blob = await api.renderEditorThumbnail(projectPath, thumbnail);
      if (serverPreviewUrl.startsWith("blob:")) URL.revokeObjectURL(serverPreviewUrl);
      setServerPreviewUrl(URL.createObjectURL(blob));
      setServerPreviewKey((k) => k + 1);
      const sec = ((performance.now() - t0) / 1000).toFixed(1);
      setMessage(`서버 미리보기 갱신 (${sec}초)`);
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggleProject = (path: string, checked: boolean) => {
    const next = checked
      ? selectedPaths.includes(path) ? selectedPaths : [...selectedPaths, path]
      : selectedPaths.filter((p) => p !== path);
    setSelectedPaths(next);
    syncSelectionParams(next);
  };

  const folderProjects = () =>
    entries.filter((e) => e.is_dir && e.kind === "project").map((e) => e.path);

  const selectAllInFolder = () => {
    const paths = folderProjects();
    if (!paths.length) return;
    const next = [...selectedPaths];
    for (const p of paths) {
      if (!next.includes(p)) next.push(p);
    }
    setSelectedPaths(next);
    syncSelectionParams(next);
  };

  const deselectAllInFolder = () => {
    const inFolder = new Set(folderProjects());
    if (!inFolder.size) return;
    const next = selectedPaths.filter((p) => !inFolder.has(p));
    setSelectedPaths(next);
    syncSelectionParams(next);
  };

  const applyThumbTemplate = (templateId: ThumbTemplateId) => {
    const canvas = thumbCanvas();
    if (!canvas) return;
    const names = trackNamesFromPaths(selectedPaths);
    // 여러 곡이면 앨범명(상위 폴더)을 제목으로
    let title = canvas.title || "";
    if (selectedPaths.length > 1) {
      const parts = selectedPaths[0].split(/[/\\]/);
      const album = parts.length >= 2 ? parts[parts.length - 2] : "";
      if (album) title = album.replace(/^\d+[\s._-]+/, "").trim() || album;
    }
    // 생성본 thumbnail.jpg를 배경으로 쓰지 않음
    let imageName = canvas.background.image;
    const opts = thumbImageOptions();
    if (!imageName || imageName.toLowerCase().endsWith("thumbnail.jpg")) {
      const cover =
        opts.find((o) => !o.name.toLowerCase().endsWith("thumbnail.jpg")) || opts[0];
      if (cover) imageName = cover.path;
    } else {
      imageName = matchThumbImage(imageName)?.path || imageName;
    }
    const next = applyTemplate(
      { ...canvas, title, background: { ...canvas.background, image: imageName } },
      templateId,
      selectedPaths.length || 1,
      names,
      undefined,
      brand?.copyright_line || "",
    );
    setThumbCanvas(next);
    setSelectedBoxId(null);
    setMessage(`${THUMB_TEMPLATE_LABELS[templateId]} 적용`);
  };

  const selectedBox = config?.thumbnail.boxes.find((b) => b.id === selectedBoxId) ?? null;

  const renderPreviewVideo = async () => {
    if (!projectPath || !config) return;
    setPreviewEncoding(true);
    setPreviewReady(false);
    setPreviewPlaying(false);
    setMessage("30초 미리보기 인코딩 중...");
    try {
      await api.saveEditorConfig(projectPath, {
        subtitle: config.subtitle,
        overlay: { ...DEFAULT_OVERLAY, ...(config.overlay || {}) },
      });
      await api.renderEditorPreviewVideo(projectPath);
      setPreviewKey((k) => k + 1);
      setPreviewReady(true);
      setMessage("인코딩 완료. 30초 미리보기 재생을 누르세요.");
    } catch (e) {
      setPreviewReady(false);
      setMessage(String(e));
    } finally {
      setPreviewEncoding(false);
    }
  };

  const renderVideo = async () => {
    if (!projectPath || renderEncoding) return;
    setRenderEncoding(true);
    setVideoFailed(false);
    setRenderProgress("큐 등록 중...");
    setMessage("전체 영상 렌더 큐 등록 중...");
    try {
      const cfg = configRef.current;
      if (cfg) {
        const saved = await api.saveEditorConfig(projectPath, {
          ...cfg,
          project_paths: selectedPaths,
        });
        setConfig(saved.config);
      }
      const rel = workRoot ? relPath(workRoot, projectPath) : projectPath;
      const many = selectedPaths.length > 1;
      const res = many
        ? await api.runPlaylistPipeline({
            project_paths: selectedPaths,
            title:
              albumNameFromPath(selectedPaths[0]) ||
              configRef.current?.youtube?.title ||
              configRef.current?.thumbnail?.title ||
              "",
            subtitle: configRef.current?.thumbnail?.subtitle || "",
            target_stage: "review",
          })
        : await api.runPipeline(rel, "review", undefined, selectedPaths);
      setRenderJobId(res.job_id);
      setRenderProgress(`작업 #${res.job_id} 시작...`);
      setMessage(
        many
          ? `${selectedPaths.length}곡 합본 렌더 #${res.job_id} 진행 중...`
          : `렌더 작업 #${res.job_id} 진행 중...`,
      );

      for (let i = 0; i < 900; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await api.getQueueJob(res.job_id).catch(() => null);
        if (!job) break;
        const prog =
          job.total > 0
            ? `${job.message || "진행 중"} · ${job.progress}/${job.total}`
            : job.message || "진행 중";
        setRenderProgress(`작업 #${res.job_id}: ${prog}`);
        setMessage(`영상 인코딩: ${prog}`);
        if (job.status === "completed") {
          setRenderProgress("완료");
          setMessage("영상 인코딩 완료 — 미리보기를 불러옵니다.");
          setVideoFailed(false);
          setPreviewKey((k) => k + 1);
          persistSession(selectedPaths, 5);
          break;
        }
        if (job.status === "failed") {
          setRenderProgress("실패");
          setMessage(`영상 인코딩 실패: ${job.message || "알 수 없는 오류"}`);
          break;
        }
      }
    } catch (e) {
      setRenderProgress("");
      setMessage(String(e));
    } finally {
      setRenderEncoding(false);
    }
  };

  const saveYoutubeDesc = async (keepPreview = false) => {
    if (!projectPath || !draft) return;
    setBusy(true);
    try {
      const autoBlock = (draft.auto_block || "").trim();
      let next: YoutubeDraft = {
        ...draft,
        mode: selectedPaths.length > 1 ? "playlist" : "single",
        description_locked: keepPreview,
      };
      if (!keepPreview && selectedPaths.length > 1) {
        const ch = await api.regenerateYoutubeChapters(projectPath, selectedPaths);
        next = { ...next, tracks: ch.tracks, description_locked: false };
        // 트랙 재생성 시 사용자가 편집한 자동 블록 유지 (비어있으면 서버가 자동 생성)
        next.auto_block = autoBlock;
      }
      const res = await api.saveYoutubeDraft(projectPath, next);
      setDraft({
        ...next,
        description_preview: res.description,
        auto_block: res.auto_block ?? next.auto_block,
        char_count: res.char_count,
        description_locked: keepPreview,
      });
      persistSession(selectedPaths, 6);
      setMessage("설명 저장됨 — 업로드 단계에서 그대로 배포됩니다.");
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  /** 왼쪽 입력(제목·소개·자동블록)을 즉시 오른쪽 미리보기에 반영 (서버 왕복 없음) */
  const composePreviewLocal = (d: YoutubeDraft, single: boolean): string => {
    const introParts: string[] = [];
    const en = (d.description_en || "").trim();
    const ko = (d.description_ko || "").trim();
    if (en) introParts.push(en);
    if (ko && ko !== en) introParts.push(ko);
    const intro = introParts.join("\n\n");
    const autoBlock = (d.auto_block || "").trim();
    const parts: string[] = [];
    if (intro) parts.push(intro, "");
    if (autoBlock) {
      parts.push(autoBlock);
    } else if (!single) {
      // 자동 블록이 비었고 재생목록이면 트랙 목록이라도 즉시 반영
      const tl = (d.tracks || [])
        .map((t) => {
          const sec = Number(t.start_sec || 0);
          const m = Math.floor(sec / 60);
          const s = Math.floor(sec % 60);
          return `${m}:${String(s).padStart(2, "0")} ${t.title}`;
        })
        .join("\n");
      if (tl) parts.push("🎵 Tracklist", tl);
    }
    const heading = !intro && (d.title || "").trim() ? (single ? d.title.trim() : "") : "";
    if (heading) parts.unshift(heading, "");
    return parts.join("\n").replace(/^\n+/, "").slice(0, 4900);
  };

  const uploadYoutube = async () => {
    if (!projectPath || !draft) return;
    setBusy(true);
    setUploadJob(null);
    try {
      await api.saveYoutubeDraft(projectPath, draft);
      const rel = workRoot ? relPath(workRoot, projectPath) : projectPath;
      const res = await api.uploadToYoutube(
        rel,
        {
          privacyStatus: privacy,
          title: draft.title,
          description: draft.description_preview,
          tags: draft.tags,
        },
        setUploadJob
      );
      setUploadUrl(res.url);
      const size = res.file_size_mb ? `${res.file_size_mb} MB` : "";
      const dur = fmtDuration(res.duration_sec);
      let msg = `업로드 완료${size ? ` · ${size}` : ""}${dur ? ` · ${dur}` : ""}: ${res.url}`;
      if (res.thumbnail_error) {
        msg += `\n(⚠ 썸네일 설정 실패: ${res.thumbnail_error})`;
      }
      setMessage(msg);
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const renderStep = () => {
    if (!projectPath && step > 1) {
      return <p className="editor-hint">먼저 1단계에서 곡을 선택하세요.</p>;
    }

    switch (step) {
      case 1:
        return (
          <div className="editor-step">
            <p className="editor-hint">
              앨범 → 곡을 체크한 뒤 다음을 누르세요.
              {selectedPaths.length > 0 && ` (선택 ${selectedPaths.length}곡)`}
            </p>
            <div className="editor-browse">
              <div className="editor-browse-toolbar">
                {browsePath && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => {
                    const parent = browsePath.replace(/[/\\][^/\\]+$/, "");
                    loadBrowse(parent || "");
                  }}>
                    ↑ 상위
                  </button>
                )}
                {entries.some((e) => e.is_dir && e.kind === "project") && (
                  <div className="editor-browse-actions">
                    <button type="button" className="btn btn-secondary btn-sm" onClick={selectAllInFolder}>
                      전체선택
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={deselectAllInFolder}>
                      선택해제
                    </button>
                  </div>
                )}
              </div>
              <ul className="editor-browse-list">
                {entries.map((e) => {
                  const checked = selectedPaths.includes(e.path);
                  const order = checked ? selectedPaths.indexOf(e.path) + 1 : 0;
                  return (
                  <li key={e.path} className={checked ? "is-checked" : ""}>
                    {e.is_dir ? (
                      <>
                        {e.kind === "project" && (
                          <label className="editor-song-check-wrap">
                            <input
                              type="checkbox"
                              className="editor-song-check"
                              checked={checked}
                              onChange={(ev) => toggleProject(e.path, ev.target.checked)}
                              aria-label={`${e.name} 선택`}
                            />
                            {order > 0 && <span className="editor-song-order">{order}</span>}
                          </label>
                        )}
                        <button type="button" className="editor-browse-dir" onClick={() => loadBrowse(e.path)}>
                          {e.name}
                        </button>
                      </>
                    ) : (
                      <span className="editor-browse-file">{e.name}</span>
                    )}
                  </li>
                  );
                })}
              </ul>
            </div>
          </div>
        );

      case 2: {
        const canvas = thumbCanvas();
        return canvas && config ? (
          <div className="editor-step editor-thumb-ppt editor-compact">
            <div className="editor-panel editor-panel-narrow">
              <h3 className="editor-panel-title">템플릿</h3>
              <div className="thumb-template-grid">
                {THUMB_TEMPLATE_IDS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={`thumb-template-btn ${currentTemplateId(canvas) === id ? "active" : ""}`}
                    title={THUMB_TEMPLATE_LABELS[id]}
                    onClick={() => applyThumbTemplate(id)}
                  >
                    <span className={`thumb-template-preview thumb-tpl-${id.replace("tpl-", "")}`} />
                    <span className="thumb-template-label">{THUMB_TEMPLATE_LABELS[id]}</span>
                  </button>
                ))}
              </div>

              <h3 className="editor-panel-title">배경</h3>
              <label>배경 이미지</label>
              <select
                value={matchThumbImage(canvas.background.image)?.path || canvas.background.image}
                onChange={(e) =>
                  setThumbCanvas({
                    ...canvas,
                    background: { ...canvas.background, image: e.target.value },
                  })
                }
              >
                {thumbImageGroups().map(({ folder, items }) => (
                  <optgroup key={folder} label={folder}>
                    {items.map((it) => (
                      <option key={it.path} value={it.path}>
                        {it.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <label>어둡기 {Math.round(canvas.background.dim * 100)}%</label>
              <input
                type="range"
                min={0}
                max={0.7}
                step={0.05}
                value={canvas.background.dim}
                onChange={(e) =>
                  setThumbCanvas({
                    ...canvas,
                    background: { ...canvas.background, dim: Number(e.target.value) },
                  })
                }
              />

              <h3 className="editor-panel-title">글상자</h3>
              {selectedBox ? (
                <>
                  <label>글자 크기 {selectedBox.font_size}</label>
                  <input
                    type="range"
                    min={14}
                    max={96}
                    step={1}
                    value={selectedBox.font_size}
                    onChange={(e) =>
                      setThumbCanvas({
                        ...canvas,
                        boxes: canvas.boxes.map((b) =>
                          b.id === selectedBox.id ? { ...b, font_size: Number(e.target.value) } : b
                        ),
                      })
                    }
                  />
                  <label>정렬</label>
                  <select
                    value={selectedBox.align}
                    onChange={(e) =>
                      setThumbCanvas({
                        ...canvas,
                        boxes: canvas.boxes.map((b) =>
                          b.id === selectedBox.id
                            ? { ...b, align: e.target.value as "left" | "center" | "right" }
                            : b
                        ),
                      })
                    }
                  >
                    <option value="left">왼쪽</option>
                    <option value="center">가운데</option>
                    <option value="right">오른쪽</option>
                  </select>
                  <label>글자 색</label>
                  <div className="thumb-color-presets">
                    {THUMB_COLOR_PRESETS.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`thumb-color-swatch ${selectedBox.color.toUpperCase() === p.color.toUpperCase() ? "active" : ""}`}
                        style={{ background: p.color }}
                        title={p.label}
                        onClick={() =>
                          setThumbCanvas({
                            ...canvas,
                            boxes: canvas.boxes.map((b) =>
                              b.id === selectedBox.id ? { ...b, color: p.color } : b
                            ),
                          })
                        }
                      />
                    ))}
                  </div>
                  <label className="thumb-color-custom">
                    <span className="thumb-color-custom-label">사용자 선택</span>
                    <input
                      type="color"
                      className="thumb-color-picker"
                      value={selectedBox.color}
                      onChange={(e) =>
                        setThumbCanvas({
                          ...canvas,
                          boxes: canvas.boxes.map((b) =>
                            b.id === selectedBox.id ? { ...b, color: e.target.value } : b
                          ),
                        })
                      }
                    />
                  </label>
                  <div className="thumb-field-row">
                    <span className="thumb-field-label">굵게</span>
                    <input
                      type="checkbox"
                      className="thumb-check"
                      checked={selectedBox.bold}
                      onChange={(e) =>
                        setThumbCanvas({
                          ...canvas,
                          boxes: canvas.boxes.map((b) =>
                            b.id === selectedBox.id ? { ...b, bold: e.target.checked } : b
                          ),
                        })
                      }
                    />
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setThumbCanvas({
                        ...canvas,
                        boxes: canvas.boxes.filter((b) => b.id !== selectedBox.id),
                      });
                      setSelectedBoxId(null);
                    }}
                  >
                    글상자 삭제
                  </button>
                </>
              ) : (
                <p className="editor-hint">캔버스에서 글상자를 클릭하세요.</p>
              )}
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  const nb = newTextBox(500, 300);
                  setThumbCanvas({ ...canvas, boxes: [...canvas.boxes, nb] });
                  setSelectedBoxId(nb.id);
                }}
              >
                + 글상자 추가
              </button>

              <div className="editor-actions">
                <button type="button" className="btn btn-secondary" disabled={busy} onClick={refreshThumbPreview}>
                  서버 미리보기
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy}
                  onClick={() => void saveThumbnail()}
                >
                  썸네일 저장
                </button>
              </div>
            </div>
            <div className="editor-preview editor-preview-wide">
              <ThumbnailCanvasEditor
                canvas={canvas}
                imageOptions={thumbImageOptions().map((it) => ({
                  path: it.path,
                  name: it.name,
                  label: it.label,
                  rel: it.rel,
                }))}
                mediaUrl={(p) => api.pipelineMediaUrl(p)}
                selectedId={selectedBoxId}
                onSelectId={setSelectedBoxId}
                onChange={setThumbCanvas}
              />
              <p className="editor-hint">최종 렌더</p>
              <img
                className="ppt-server-preview"
                src={
                  serverPreviewUrl ||
                  api.editorThumbnailPreviewUrl(projectPath) + `&k=${serverPreviewKey}`
                }
                alt="서버 렌더 미리보기"
              />
            </div>
          </div>
        ) : null;
      }

      case 3: {
        if (!config) return null;
        const sub = {
          ...config.subtitle,
          font_size_en: config.subtitle.font_size_en ?? 68,
          font_size_ko: config.subtitle.font_size_ko ?? 68,
          font_size_title: config.subtitle.font_size_title ?? 42,
          track_header_enabled: config.subtitle.track_header_enabled ?? true,
          track_header_y: config.subtitle.track_header_y ?? 70,
          title_color: config.subtitle.title_color ?? "#FFFFFF",
        };
        const ov = { ...DEFAULT_OVERLAY, ...(config.overlay || {}) };
        const showEn = sub.mode === "en" || sub.mode === "both";
        const showKo = sub.mode === "ko" || sub.mode === "both";
        const cover = imagePaths.find((p) => !p.toLowerCase().endsWith("thumbnail.jpg")) || imagePaths[0];
        const coverUrl = cover ? api.pipelineMediaUrl(cover) : "";
        const eqStyleId =
          ov.eq_bar_style === "none" || ov.eq_bar_enabled === false ? "none" : ov.eq_bar_style;
        const eqOn = eqStyleId !== "none";
        const eqStyle = EQ_STYLES.find((s) => s.id === eqStyleId) || EQ_STYLES[0];
        const setOverlay = (patch: Partial<typeof ov>) =>
          setConfig({ ...config, overlay: { ...ov, ...patch } });
        const eqBottomCenter = (w = ov.eq_bar_w, h = ov.eq_bar_h) => ({
          eq_bar_align: "bottom_center" as const,
          eq_bar_x: Math.round((VIDEO_W - w) / 2),
          eq_bar_y: Math.round(VIDEO_H - h - 24),
        });
        const snapEqBottom = () => setOverlay(eqBottomCenter());
        const eqBox =
          (ov.eq_bar_align || "bottom_center") === "bottom_center"
            ? eqBottomCenter(ov.eq_bar_w, ov.eq_bar_h)
            : { eq_bar_x: ov.eq_bar_x, eq_bar_y: ov.eq_bar_y };
        return (
          <div className="editor-step editor-sub-layout editor-compact">
            <div className="editor-panel editor-panel-narrow">
              <section className="editor-section">
                <h3 className="editor-section-title">스타일 프리셋 (곡별)</h3>
                <div className="editor-preset-row">
                  <select
                    value={presetId}
                    onChange={(e) => void applyPreset(e.target.value)}
                  >
                    <option value="">— 기본 스타일 (전역) —</option>
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="새 프리셋 이름"
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={!presetName.trim()}
                    onClick={() => void savePreset()}
                  >
                    이 곡 스타일 저장
                  </button>
                </div>
                <p className="editor-hint">
                  프리셋을 선택하면 이 곡에만 그 스타일(자막·EQ·리마스터·썸네일)이 적용됩니다.
                  다른 곡에도 같은 프리셋을 쓰려면 각 곡에서 선택하세요.
                </p>
              </section>

              <section className="editor-section">
                <div className="editor-section-head">
                  <h3 className="editor-section-title">트랙 제목</h3>
                  <label className="editor-check">
                    <input
                      type="checkbox"
                      checked={sub.track_header_enabled}
                      onChange={(e) =>
                        setConfig({ ...config, subtitle: { ...sub, track_header_enabled: e.target.checked } })
                      }
                    />
                    <span className="editor-check-label">상단에 표시</span>
                  </label>
                </div>
                {sub.track_header_enabled && (
                  <>
                    <div className="editor-compact-sliders">
                      <label>위쪽 {sub.track_header_y}px</label>
                      <input
                        type="range"
                        min={20}
                        max={400}
                        step={2}
                        value={sub.track_header_y}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, track_header_y: Number(e.target.value) } })
                        }
                      />
                      <label>크기 {sub.font_size_title}px</label>
                      <input
                        type="range"
                        min={22}
                        max={90}
                        step={1}
                        value={sub.font_size_title}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, font_size_title: Number(e.target.value) } })
                        }
                      />
                    </div>
                    <label>글자 색</label>
                    <div className="thumb-color-presets">
                      {THUMB_COLOR_PRESETS.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          className={`thumb-color-swatch ${sub.title_color.toUpperCase() === p.color.toUpperCase() ? "active" : ""}`}
                          style={{ background: p.color }}
                          title={p.label}
                          onClick={() =>
                            setConfig({ ...config, subtitle: { ...sub, title_color: p.color } })
                          }
                        />
                      ))}
                    </div>
                    <label className="thumb-color-custom">
                      <span className="thumb-color-custom-label">사용자 선택</span>
                      <input
                        type="color"
                        className="thumb-color-picker"
                        value={sub.title_color}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, title_color: e.target.value } })
                        }
                      />
                    </label>
                  </>
                )}
              </section>

              <section className="editor-section">
                <label>자막 언어</label>
                <select
                  value={sub.mode}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      subtitle: { ...sub, mode: e.target.value as typeof sub.mode },
                    })
                  }
                >
                  {(["ko", "en", "both"] as const).map((m) => (
                    <option key={m} value={m}>
                      {SUB_MODE_LABELS[m]}
                    </option>
                  ))}
                </select>
                <div className="editor-compact-sliders">
                  {showEn && (
                    <>
                      <label>영어 아래여백 {sub.margin_v_en}px</label>
                      <input
                        type="range"
                        min={80}
                        max={400}
                        step={2}
                        value={sub.margin_v_en}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, margin_v_en: Number(e.target.value) } })
                        }
                      />
                      <label>영어 크기 {sub.font_size_en}px</label>
                      <input
                        type="range"
                        min={36}
                        max={120}
                        step={2}
                        value={sub.font_size_en}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, font_size_en: Number(e.target.value) } })
                        }
                      />
                    </>
                  )}
                  {showKo && (
                    <>
                      <label>한글 아래여백 {sub.margin_v_ko}px</label>
                      <input
                        type="range"
                        min={40}
                        max={280}
                        step={2}
                        value={sub.margin_v_ko}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, margin_v_ko: Number(e.target.value) } })
                        }
                      />
                      <label>한글 크기 {sub.font_size_ko}px</label>
                      <input
                        type="range"
                        min={36}
                        max={120}
                        step={2}
                        value={sub.font_size_ko}
                        onChange={(e) =>
                          setConfig({ ...config, subtitle: { ...sub, font_size_ko: Number(e.target.value) } })
                        }
                      />
                    </>
                  )}
                </div>
              </section>

              <section className="editor-section">
                <label>스펙트럼 종류</label>
                <select
                  value={eqStyleId}
                  onChange={(e) => {
                    const id = e.target.value as typeof ov.eq_bar_style;
                    const enabled = id !== "none";
                    const w = ov.eq_bar_w;
                    const h = ov.eq_bar_h;
                    setOverlay({
                      eq_bar_style: id,
                      eq_bar_enabled: enabled,
                      ...(enabled ? eqBottomCenter(w, h) : {}),
                    });
                  }}
                >
                  {EQ_STYLES.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>
                {eqOn && (
                  <>
                    <div className="editor-compact-sliders">
                      <label>너비 {ov.eq_bar_w}px</label>
                      <input
                        type="range"
                        min={80}
                        max={1920}
                        step={4}
                        value={ov.eq_bar_w}
                        onChange={(e) => {
                          const w = Number(e.target.value);
                          setOverlay({ eq_bar_w: w, ...eqBottomCenter(w, ov.eq_bar_h) });
                        }}
                      />
                      <label>높이 {ov.eq_bar_h}px</label>
                      <input
                        type="range"
                        min={8}
                        max={400}
                        step={2}
                        value={ov.eq_bar_h}
                        onChange={(e) => {
                          const h = Number(e.target.value);
                          setOverlay({ eq_bar_h: h, ...eqBottomCenter(ov.eq_bar_w, h) });
                        }}
                      />
                      <label>가로 {ov.eq_bar_x}</label>
                      <input
                        type="range"
                        min={0}
                        max={Math.max(0, VIDEO_W - ov.eq_bar_w)}
                        step={4}
                        value={Math.min(ov.eq_bar_x, VIDEO_W - ov.eq_bar_w)}
                        onChange={(e) =>
                          setOverlay({
                            eq_bar_align: "custom",
                            eq_bar_x: Number(e.target.value),
                          })
                        }
                      />
                      <label>세로 {ov.eq_bar_y}</label>
                      <input
                        type="range"
                        min={0}
                        max={Math.max(0, VIDEO_H - ov.eq_bar_h)}
                        step={4}
                        value={Math.min(ov.eq_bar_y, VIDEO_H - ov.eq_bar_h)}
                        onChange={(e) =>
                          setOverlay({
                            eq_bar_align: "custom",
                            eq_bar_y: Number(e.target.value),
                          })
                        }
                      />
                    </div>
                    <label>막대 색</label>
                    <div className="thumb-color-presets">
                      {THUMB_COLOR_PRESETS.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          className={`thumb-color-swatch ${(ov.eq_bar_color || "#FFFFFF").toUpperCase() === p.color.toUpperCase() ? "active" : ""}`}
                          style={{ background: p.color }}
                          title={p.label}
                          onClick={() => setOverlay({ eq_bar_color: p.color })}
                        />
                      ))}
                    </div>
                    <label className="thumb-color-custom">
                      <span className="thumb-color-custom-label">사용자 선택</span>
                      <input
                        type="color"
                        className="thumb-color-picker"
                        value={ov.eq_bar_color || "#FFFFFF"}
                        onChange={(e) => setOverlay({ eq_bar_color: e.target.value })}
                      />
                    </label>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={snapEqBottom}>
                      하단 중앙에 맞춤
                    </button>
                  </>
                )}
              </section>

              <div className="editor-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy}
                  onClick={() => saveConfig({ subtitle: sub, overlay: ov })}
                >
                  저장
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={previewEncoding}
                  onClick={renderPreviewVideo}
                >
                  {previewEncoding ? "인코딩 중..." : "30초 미리보기 렌더"}
                </button>
              </div>
              <p className="editor-hint">멈추면 샘플 화면으로 돌아옵니다.</p>
            </div>

            <div className="editor-preview editor-preview-wide">
              <div className="sub-live-preview">
                {previewReady && (
                <video
                  ref={previewVideoRef}
                  key={`pv-${previewKey}`}
                  className={`sub-live-media${previewPlaying ? "" : " is-parked"}`}
                  controls={previewPlaying}
                  src={api.editorVideoUrl(projectPath, true) + `&k=${previewKey}`}
                  onPlay={() => setPreviewPlaying(true)}
                  onPause={() => setPreviewPlaying(false)}
                  onEnded={() => setPreviewPlaying(false)}
                  onError={() => {
                    setPreviewReady(false);
                    setPreviewPlaying(false);
                  }}
                />
                )}
                {!previewPlaying && (
                  <>
                    {projectPath ? (
                      <img
                        className="sub-live-frame"
                        src={api.editorCoverFrameUrl(projectPath)}
                        alt=""
                      />
                    ) : coverUrl ? (
                      <>
                        <img className="sub-live-bg" src={coverUrl} alt="" />
                        <img className="sub-live-art" src={coverUrl} alt="" />
                      </>
                    ) : (
                      <div className="sub-live-media sub-live-empty">커버 이미지가 없습니다.</div>
                    )}
                    {sub.track_header_enabled && (
                      <div
                        className="sub-overlay-line sub-overlay-title"
                        style={{
                          ...assOverlayBox(),
                          top: `${(sub.track_header_y / ASS_PLAY_H) * 100}%`,
                          bottom: "auto",
                          fontSize: assFontCqh(sub.font_size_title),
                          color: sub.title_color,
                        }}
                      >
                        {trackHeaderSample(projectPath)}
                      </div>
                    )}
                    {showEn && (
                      <div
                        className="sub-overlay-line sub-overlay-en"
                        style={{
                          ...assOverlayBox(),
                          bottom: `${(sub.margin_v_en / ASS_PLAY_H) * 100}%`,
                          fontSize: assFontCqh(sub.font_size_en),
                        }}
                      >
                        Sample lyric line in English
                      </div>
                    )}
                    {showKo && (
                      <div
                        className="sub-overlay-line sub-overlay-ko"
                        style={{
                          ...assOverlayBox(),
                          bottom: `${(sub.margin_v_ko / ASS_PLAY_H) * 100}%`,
                          fontSize: assFontCqh(sub.font_size_ko),
                          fontWeight: 700,
                        }}
                      >
                        샘플 가사 한 줄
                      </div>
                    )}
                    {previewEncoding && (
                      <div className="sub-live-encoding">저화질 인코딩 중… 끝나면 재생할 수 있습니다.</div>
                    )}
                    <button
                      type="button"
                      className="sub-live-resume"
                      disabled={!previewReady || previewEncoding}
                      onClick={() => void previewVideoRef.current?.play()}
                    >
                      30초 미리보기 재생
                    </button>
                  </>
                )}
                {!previewPlaying && (brand?.watermark_enabled !== false && (brand?.watermark_label || brand?.channel_name) ? (
                  <div className="wm-live" aria-hidden>
                    <img src={whickMark} alt="" />
                    <span>{brand?.watermark_label || brand?.channel_name}</span>
                  </div>
                ) : null)}
                {eqOn && !previewPlaying && (
                  <div
                    className={`eq-overlay eq-style-${eqStyleId}`}
                    style={{
                      left: `${(eqBox.eq_bar_x / VIDEO_W) * 100}%`,
                      top: `${(eqBox.eq_bar_y / VIDEO_H) * 100}%`,
                      width: `${(ov.eq_bar_w / VIDEO_W) * 100}%`,
                      height: `${(ov.eq_bar_h / VIDEO_H) * 100}%`,
                      ["--eq-color" as string]: ov.eq_bar_color || "#FFFFFF",
                    }}
                  >
                    {Array.from({ length: Math.max(eqStyle.n, 8) }, (_, i) => (
                      <span
                        key={i}
                        className="eq-overlay-item"
                        style={{
                          animationDelay: `${(i % 12) * 0.08}s`,
                          background: ov.eq_bar_color || "#FFFFFF",
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
              {!previewPlaying && (
                <p className="editor-hint">멈추면 샘플로 돌아와 위치를 다시 맞출 수 있습니다.</p>
              )}
            </div>
          </div>
        );
      }

      case 4:
        return config ? (
          <div className="editor-step editor-split">
            <div className="editor-panel">
              <h3 className="editor-panel-title">리마스터 (음성)</h3>
              <p className="editor-hint">
                음원만 마스터링합니다. 설정·미리듣기를 확인한 뒤 다음 단계에서 영상을 입힙니다.
              </p>
              <label>저음 강조 (dB) {config.remaster.low_db.toFixed(1)}</label>
              <input
                type="range"
                min={-3}
                max={3}
                step={0.1}
                value={config.remaster.low_db}
                onChange={(e) =>
                  setConfig({ ...config, remaster: { ...config.remaster, low_db: Number(e.target.value) } })
                }
              />
              <label>고음 강조 (dB) {config.remaster.high_db.toFixed(1)}</label>
              <input
                type="range"
                min={-2}
                max={2}
                step={0.1}
                value={config.remaster.high_db}
                onChange={(e) =>
                  setConfig({ ...config, remaster: { ...config.remaster, high_db: Number(e.target.value) } })
                }
              />
              <label>좌우 분리 {config.remaster.stereo_width.toFixed(1)}</label>
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={config.remaster.stereo_width}
                onChange={(e) =>
                  setConfig({ ...config, remaster: { ...config.remaster, stereo_width: Number(e.target.value) } })
                }
              />
              <label className="editor-check">
                <input
                  type="checkbox"
                  checked={config.remaster.strip_fingerprint}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      remaster: { ...config.remaster, strip_fingerprint: e.target.checked },
                    })
                  }
                />
                Suno 지문 제거 (메타 삭제 + 재인코딩)
              </label>
              <div className="editor-actions">
                <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => saveConfig({ remaster: config.remaster })}>
                  저장
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy}
                  onClick={async () => {
                    await saveConfig({ remaster: config.remaster });
                    setPreviewKey((k) => k + 1);
                  }}
                >
                  미리듣기 갱신
                </button>
              </div>
              {fingerprintOk === false && (
                <p className="editor-warn">⚠ Suno 지문이 감지되었습니다. 설정을 저장한 뒤 영상 인코딩을 실행하세요.</p>
              )}
              {fingerprintOk === true && <p className="editor-ok">✓ 지문 검사 통과</p>}
            </div>
            <div className="editor-preview">
              <p>리마스터 미리듣기 (30초)</p>
              <audio controls src={api.editorAudioPreviewUrl(projectPath) + `&k=${previewKey}`} />
            </div>
          </div>
        ) : null;

      case 5: {
        if (!config) return null;
        return (
          <div className="editor-step editor-sub-layout">
            <div className="editor-panel editor-panel-narrow">
              <h3 className="editor-panel-title">전체 영상 인코딩</h3>
              <p className="editor-hint">
                {selectedPaths.length > 1
                  ? `${selectedPaths.length}곡을 한 영상으로 합칩니다. 곡마다 해당 커버가 나오고, 저장한 앨범 썸네일은 유튜브 목록용입니다.`
                  : "앞 단계의 리마스터·자막·스펙트럼 설정을 반영해 영상으로 합칩니다. 시간이 걸릴 수 있습니다."}
              </p>
              <div className="editor-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy || renderEncoding}
                  onClick={renderVideo}
                >
                  {renderEncoding ? "인코딩 중..." : "전체 영상 렌더"}
                </button>
              </div>
              {(renderEncoding || renderProgress) && (
                <p className={`editor-hint ${renderEncoding ? "editor-encoding-status" : ""}`}>
                  {renderEncoding ? "⏳ " : renderProgress === "완료" ? "✓ " : ""}
                  {renderProgress || "대기 중..."}
                </p>
              )}
              {renderJobId && !renderEncoding && renderProgress !== "완료" && renderProgress !== "실패" && (
                <p className="editor-hint">작업 #{renderJobId}</p>
              )}
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={renderEncoding}
                onClick={() => {
                  setPreviewKey((k) => k + 1);
                  setVideoFailed(false);
                }}
              >
                영상 새로고침
              </button>
            </div>
            <div className="editor-preview editor-preview-wide">
              <p className="editor-hint">전체 인코딩 결과</p>
              {renderEncoding ? (
                <div className="sub-live-media sub-live-empty">인코딩 중… 끝나면 여기에 재생됩니다.</div>
              ) : !videoFailed ? (
                <div className="yt-style-player">
                  {!videoPlaying && (
                    <button
                      type="button"
                      className="yt-thumb-cover"
                      onClick={() => {
                        videoRef.current?.load();
                        void videoRef.current?.play();
                        setVideoPlaying(true);
                      }}
                      aria-label="재생"
                    >
                      <img
                        src={api.editorThumbnailPreviewUrl(projectPath) + `&k=${previewKey}`}
                        alt="썸네일"
                      />
                      <span className="yt-thumb-play">▶</span>
                    </button>
                  )}
                  <video
                    ref={videoRef}
                    key={`fv-${previewKey}`}
                    className="sub-live-media"
                    controls={videoPlaying}
                    src={api.editorVideoUrl(projectPath) + `&k=${previewKey}`}
                    onPlay={() => setVideoPlaying(true)}
                    onPause={() => setVideoPlaying(false)}
                    onEnded={() => setVideoPlaying(false)}
                    onError={() => setVideoFailed(true)}
                  />
                </div>
              ) : (
                <div className="sub-live-media sub-live-empty">전체 영상이 없습니다. 렌더를 실행하세요.</div>
              )}
            </div>
          </div>
        );
      }

      case 6:
        return draft ? (
          <div className="editor-step editor-yt">
            <div className="editor-yt-fields">
              <div className="editor-panel">
                <h3 className="editor-panel-title">직접 입력</h3>
                <p className="editor-hint">아래 미리보기의 줄바꿈·칸 띄우기가 그대로 저장됩니다. 왼쪽만 고치면 미리보기를 다시 만듭니다.</p>
                <label>업로드 제목</label>
                <input
                  value={draft.title}
                  onChange={(e) => {
                    const next = { ...draft, title: e.target.value, description_locked: false };
                    setDraft({ ...next, description_preview: composePreviewLocal(next, selectedPaths.length <= 1) });
                  }}
                />
                <label>영어 소개</label>
                <textarea
                  rows={6}
                  value={draft.description_en}
                  onChange={(e) => {
                    const next = { ...draft, description_en: e.target.value, description_locked: false };
                    setDraft({ ...next, description_preview: composePreviewLocal(next, selectedPaths.length <= 1) });
                  }}
                />
                <label>한글 소개</label>
                <textarea
                  rows={6}
                  value={draft.description_ko}
                  onChange={(e) => {
                    const next = { ...draft, description_ko: e.target.value, description_locked: false };
                    setDraft({ ...next, description_preview: composePreviewLocal(next, selectedPaths.length <= 1) });
                  }}
                />
                <div className="editor-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={() => saveYoutubeDesc(draft.description_locked)}
                  >
                    저장
                  </button>
                  <button type="button" className="btn" onClick={() => navigate("/settings")}>
                    채널 브랜드 · 설명 구성 설정
                  </button>
                </div>
              </div>
              <div className="editor-panel">
                <h3 className="editor-panel-title">자동 (트랙리스트·스펙·태그)</h3>
                <p className="editor-hint">블록 구성은 사용자 설정 → 「유튜브 설명 위젯」에서, 내용은 여기서 직접 고칠 수 있습니다.</p>
                <textarea
                  className="yt-auto-block"
                  rows={Math.max(8, (draft.auto_block || "").split("\n").length + 2)}
                  value={draft.auto_block || ""}
                  placeholder="저장하면 트랙 시작 시각과 재생시간이 채워집니다."
                  onChange={(e) => {
                    const next = { ...draft, auto_block: e.target.value, description_locked: false };
                    setDraft({ ...next, description_preview: composePreviewLocal(next, selectedPaths.length <= 1) });
                  }}
                />
                <div className="editor-actions">
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    onClick={() => {
                      // 편집한 자동 블록을 해제 — 저장 시 자동 재생성
                      const next = { ...draft, auto_block: "", description_locked: false };
                      setDraft({ ...next, description_preview: composePreviewLocal(next, selectedPaths.length <= 1) });
                    }}
                  >
                    자동 블록 초기화
                  </button>
                </div>
              </div>
            </div>
            <div className="yt-watch">
              <div className="yt-watch-kicker">유튜브 설명 미리보기 · 여기서 고친 뒤 저장하면 배포에 쓰입니다</div>
              <h2 className="yt-watch-title">{draft.title || "제목"}</h2>
              <p className="yt-watch-meta">{brand?.channel_name || "채널"} · {draft.char_count} / 5000</p>
              <textarea
                className="yt-watch-desc"
                rows={Math.max(18, draft.description_preview.split("\n").length + 2)}
                value={draft.description_preview}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    description_preview: e.target.value,
                    description_locked: true,
                    char_count: e.target.value.length,
                  })
                }
              />
            </div>
          </div>
        ) : null;

      case 7:
        return (
          <div className="editor-step">
            <p className="editor-hint">설정 → OAuth(사용자 설정) 확인 후 비공개 업로드합니다. 완성 영상만 올리며, 미리보기 mp4는 제외합니다.</p>
            {uploadFile ? (
              <p className="editor-ok">
                올릴 파일: {uploadFile.name} · {uploadFile.size_mb} MB
                {fmtDuration(uploadFile.duration_sec) ? ` · ${fmtDuration(uploadFile.duration_sec)}` : ""}
              </p>
            ) : (
              <p className="editor-warn">완성 영상을 찾지 못했습니다. 5단계에서 전체 인코딩을 먼저 하세요.</p>
            )}
            <label>공개 범위</label>
            <select value={privacy} onChange={(e) => setPrivacy(e.target.value as typeof privacy)}>
              <option value="private">비공개</option>
              <option value="unlisted">일부 공개</option>
              <option value="public">공개</option>
            </select>
            <button type="button" className="btn btn-primary" disabled={busy || !draft || !uploadFile} onClick={uploadYoutube}>
              {busy ? "업로드 중..." : "유튜브 업로드"}
            </button>
            {uploadJob && (
              <div className="yt-upload-progress">
                <div className="yt-upload-progress-meta">
                  <strong>{uploadJob.percent}%</strong>
                  <span>
                    {(uploadJob.bytes_sent / (1024 * 1024)).toFixed(1)} /{" "}
                    {(uploadJob.size_bytes / (1024 * 1024)).toFixed(1)} MB
                    {uploadJob.status === "running" ? " 전송 중" : uploadJob.status === "completed" ? " 완료" : ""}
                  </span>
                </div>
                <div className="yt-upload-bar">
                  <div className="yt-upload-bar-fill" style={{ width: `${uploadJob.percent}%` }} />
                </div>
              </div>
            )}
            {uploadUrl && (
              <p>
                <a href={uploadUrl} target="_blank" rel="noreferrer">
                  {uploadUrl}
                </a>
              </p>
            )}
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="editor-page">
      <header className="editor-header">
        <div>
          <h1>유튜브 스튜디오</h1>
          <p className="editor-sub">
            {selectedPaths.length > 1
              ? `${selectedPaths.length}곡 선택 · ${projectPath.split(/[/\\]/).slice(-2).join(" / ")}`
              : projectPath
                ? projectPath.split(/[/\\]/).slice(-2).join(" / ")
                : "곡을 선택하세요"}
          </p>
        </div>
        <div className="editor-header-actions">
          {projectPath ? (
            <button type="button" className="btn btn-secondary" onClick={startFresh}>
              새로 시작
            </button>
          ) : null}
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/studio")}>
            클래식 스튜디오
          </button>
        </div>
      </header>

      <nav className="editor-steps">
        {STEPS.map((label, i) => (
          <button
            key={label}
            type="button"
            className={`editor-step-btn ${step === i + 1 ? "active" : ""} ${projectPath || i === 0 ? "" : "disabled"}`}
            onClick={() => (projectPath || i === 0) && goStep(i + 1)}
          >
            <span className="editor-step-num">{i + 1}</span>
            {label}
          </button>
        ))}
      </nav>

      {message && <div className="editor-message">{message}</div>}

      <section className="editor-body">{renderStep()}</section>

      <footer className="editor-footer">
        <button type="button" className="btn btn-secondary" disabled={step <= 1} onClick={() => goStep(step - 1)}>
          이전
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={step >= STEPS.length || (!projectPath && step >= 1)}
          onClick={() => goStep(step + 1)}
        >
          다음
        </button>
      </footer>
    </div>
  );
}
