import { useCallback, useEffect, useState } from "react";
import {
  api,
  BrowseEntry,
  PipelineConfig,
  PipelineStatus,
  ProjectAssets,
  WorkflowStage,
} from "../api";

function relPath(workRoot: string, absPath: string): string {
  const root = workRoot.replace(/\\/g, "/").replace(/\/$/, "");
  const p = absPath.replace(/\\/g, "/");
  if (p.toLowerCase().startsWith(root.toLowerCase() + "/")) {
    return p.slice(root.length + 1);
  }
  return absPath;
}

function formatSize(n?: number): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function StudioPage() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [config, setConfig] = useState<PipelineConfig | null>(null);
  const [stages, setStages] = useState<WorkflowStage[]>([]);
  const [workRoot, setWorkRoot] = useState("");
  const [browsePath, setBrowsePath] = useState("");
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [assets, setAssets] = useState<ProjectAssets | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [moveTarget, setMoveTarget] = useState("review");
  const [pipelineTarget, setPipelineTarget] = useState("review");
  const [youtubeMeta, setYoutubeMeta] = useState<{ video_id?: string | null; url?: string } | null>(null);
  const [youtubeConnected, setYoutubeConnected] = useState(false);

  const refresh = useCallback(async () => {
    const [st, cfg, stg] = await Promise.all([
      api.getPipelineStatus(),
      api.getPipelineConfig(),
      api.getPipelineStages(),
    ]);
    setStatus(st);
    setConfig(cfg);
    setStages(stg.stages);
    setWorkRoot(stg.work_root);
    return stg.work_root;
  }, []);

  const loadBrowse = useCallback(async (path: string) => {
    const data = await api.browsePipeline(path);
    setBrowsePath(data.path);
    setEntries(data.entries);
  }, []);

  useEffect(() => {
    refresh()
      .then(() => loadBrowse(""))
      .catch((e) => setMessage(String(e)))
      .finally(() => setLoading(false));
  }, [refresh, loadBrowse]);

  useEffect(() => {
    api.getYoutubeStatus().then((s) => setYoutubeConnected(s.connected)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedProject) {
      setAssets(null);
      setYoutubeMeta(null);
      return;
    }
    const rel = relPath(workRoot, selectedProject);
    api.getProjectAssets(rel).then(setAssets).catch(() => setAssets(null));
    api.getYoutubeProjectMeta(rel).then((m) => {
      setYoutubeMeta({
        video_id: m.video_id,
        url: m.meta?.url,
      });
    }).catch(() => setYoutubeMeta(null));
  }, [selectedProject, workRoot]);

  const openStage = (stage: WorkflowStage) => {
    loadBrowse(stage.folder);
    setSelectedProject(null);
  };

  const openEntry = (entry: BrowseEntry) => {
    if (entry.is_dir) {
      if (entry.kind === "folder") {
        const parentIsStage = stages.some((s) => browsePath.replace(/\\/g, "/").endsWith(s.folder));
        if (parentIsStage || stages.some((s) => entry.path.replace(/\\/g, "/").includes(`/${s.folder}/`))) {
          setSelectedProject(entry.path);
        }
      }
      loadBrowse(relPath(workRoot, entry.path));
    }
  };

  const goUp = () => {
    if (!browsePath || !workRoot) return;
    const rel = relPath(workRoot, browsePath);
    if (!rel) return;
    const parts = rel.split("/").filter(Boolean);
    parts.pop();
    loadBrowse(parts.join("/"));
    setSelectedProject(null);
  };

  const handleInit = async () => {
    setBusy(true);
    setMessage("");
    try {
      const res = await api.initPipelineFolders();
      const parts: string[] = [];
      if (res.created.length) parts.push(`새 폴더 ${res.created.length}개 생성`);
      if (res.migrated.length) parts.push(`프로젝트 ${res.migrated.length}개 이동`);
      if (res.removed_legacy.length) {
        parts.push(`예전 폴더 삭제: ${res.removed_legacy.join(", ")}`);
      }
      if (res.legacy_remaining.length) {
        parts.push(
          `수동 정리 필요: ${res.legacy_remaining.join(", ")} (파일이 남아 있음)`
        );
      }
      setMessage(
        parts.length
          ? `폴더 정리 완료 — ${parts.join(" · ")}`
          : "폴더 정리 완료 — 01_음악작업, 02_검수대기 준비됨"
      );
      await refresh();
      await loadBrowse("");
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRunPipeline = async () => {
    if (!selectedProject) return;
    setBusy(true);
    setMessage("");
    try {
      const rel = relPath(workRoot, selectedProject);
      const res = await api.runPipeline(rel, pipelineTarget);
      setMessage(res.message);
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleMove = async () => {
    if (!selectedProject) return;
    setBusy(true);
    setMessage("");
    try {
      const rel = relPath(workRoot, selectedProject);
      const res = await api.movePipelineStage(rel, moveTarget);
      setMessage(`이동 완료: ${res.path}`);
      setSelectedProject(res.path);
      await refresh();
      const stage = stages.find((s) => s.id === moveTarget);
      if (stage) await loadBrowse(stage.folder);
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleYoutubeUpload = async () => {
    if (!selectedProject) return;
    if (!youtubeConnected) {
      setMessage("설정 > YouTube 연동에서 채널을 먼저 연결하세요.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const rel = relPath(workRoot, selectedProject);
      const res = await api.uploadToYoutube(rel, "private");
      setYoutubeMeta({ video_id: res.video_id, url: res.url });
      setMessage(`유튜브 비공개 업로드 완료: ${res.url}`);
      await refresh();
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleYoutubePublish = async () => {
    if (!selectedProject) return;
    if (!youtubeMeta?.video_id) {
      setMessage("먼저 유튜브에 업로드하세요.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const rel = relPath(workRoot, selectedProject);
      const res = await api.publishOnYoutube(rel, youtubeMeta.video_id);
      setMessage(`유튜브 공개 완료: ${res.url}`);
      await refresh();
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveConfig = async () => {
    if (!config) return;
    setBusy(true);
    try {
      const updated = await api.updatePipelineConfig({
        work_root: config.work_root,
        audio: config.audio,
        video: config.video,
        subtitle: config.subtitle,
      });
      setConfig(updated);
      setWorkRoot(updated.work_root);
      setMessage("파이프라인 설정 저장됨");
      await refresh();
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="loading">스튜디오 불러오는 중...</div>;

  return (
    <div className="studio-page">
      <div className="page-header">
        <div>
          <h2>유튜브 스튜디오</h2>
          <p>로컬 작업 폴더에서 리마스터·자막·영상 파이프라인을 실행합니다</p>
        </div>
        <div className="studio-header-actions">
          <button className="btn btn-secondary" onClick={() => setShowSettings((v) => !v)}>
            {showSettings ? "설정 닫기" : "파이프라인 설정"}
          </button>
          <button className="btn btn-secondary" onClick={() => api.openPipelineFolder(workRoot)}>
            탐색기 열기
          </button>
          <button className="btn btn-primary" onClick={handleInit} disabled={busy}>
            폴더 초기화
          </button>
        </div>
      </div>

      <div className="studio-status-bar">
        <span className={`badge ${status?.ffmpeg_available ? "badge-ok" : "badge-warn"}`}>
          FFmpeg {status?.ffmpeg_available ? "사용 가능" : "없음"}
        </span>
        {status?.detected_encoder && (
          <span className="badge">인코더: {status.detected_encoder}</span>
        )}
        <span className="meta">작업 루트: {workRoot}</span>
      </div>

      {message && <div className="studio-message">{message}</div>}

      {showSettings && config && (
        <div className="card studio-settings">
          <div className="card-title">파이프라인 설정</div>
          <div className="form-group">
            <label>작업 폴더 경로</label>
            <input
              value={config.work_root}
              onChange={(e) => setConfig({ ...config, work_root: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>비디오 인코더</label>
            <select
              value={config.video.encoder}
              onChange={(e) =>
                setConfig({
                  ...config,
                  video: { ...config.video, encoder: e.target.value },
                })
              }
            >
              <option value="auto">자동 (AMD AMF 우선)</option>
              <option value="h264_amf">h264_amf</option>
              <option value="h264_nvenc">h264_nvenc</option>
              <option value="libx264">libx264 (CPU)</option>
            </select>
          </div>
          <div className="form-group">
            <label>마스터 체인 (FFmpeg -af)</label>
            <textarea
              rows={3}
              value={config.audio.master_chain}
              onChange={(e) =>
                setConfig({
                  ...config,
                  audio: { ...config.audio, master_chain: e.target.value },
                })
              }
            />
          </div>
          <button className="btn btn-primary" onClick={saveConfig} disabled={busy}>
            설정 저장
          </button>
        </div>
      )}

      <div className="studio-stages">
        {stages.map((stage) => (
          <button
            key={stage.id}
            type="button"
            className="studio-stage-card"
            onClick={() => openStage(stage)}
            title={stage.description}
          >
            <span className="stage-num">{stage.folder.split("_")[0]}</span>
            <strong>{stage.label}</strong>
            <span className="meta">{stage.project_count ?? 0}개 프로젝트</span>
          </button>
        ))}
      </div>

      <div className="studio-main">
        <div className="card studio-browser">
          <div className="studio-browser-toolbar">
            <button className="btn btn-secondary btn-sm" onClick={goUp} disabled={!relPath(workRoot, browsePath)}>
              ↑ 상위
            </button>
            <span className="studio-path" title={browsePath}>
              {relPath(workRoot, browsePath) || "/"}
            </span>
          </div>
          <ul className="studio-file-list">
            {entries.length === 0 && <li className="empty">비어 있음</li>}
            {entries.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  className={`studio-file-item ${selectedProject === entry.path ? "selected" : ""}`}
                  onClick={() => openEntry(entry)}
                  onDoubleClick={() => entry.is_dir && setSelectedProject(entry.path)}
                >
                  <span className="file-icon">{entry.is_dir ? "📁" : entry.kind === "audio" ? "🎵" : entry.kind === "image" ? "🖼" : "📄"}</span>
                  <span className="file-name">{entry.name}</span>
                  <span className="file-meta">{formatSize(entry.size)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card studio-detail">
          {!selectedProject ? (
            <div className="empty-state">
              <h3>프로젝트 선택</h3>
              <p>단계 폴더 안의 프로젝트 폴더를 클릭하세요</p>
              <p className="meta" style={{ marginTop: "1rem" }}>
                필요 파일: audio.*, thumbnail.* (또는 곡 페이지에서 커버 업로드 후 보내기), lyrics_en.txt
              </p>
            </div>
          ) : (
            <>
              <div className="card-title">{assets?.track_title || selectedProject.split(/[/\\]/).pop()}</div>
              {assets?.audio_paths[0] && (
                <div className="studio-preview">
                  <label>음원 미리듣기</label>
                  <audio controls src={api.pipelineMediaUrl(assets.audio_paths[0])} />
                </div>
              )}
              {assets?.image_paths[0] && (
                <div className="studio-preview">
                  <label>썸네일</label>
                  <img src={api.pipelineMediaUrl(assets.image_paths[0])} alt="thumbnail" />
                </div>
              )}
              {assets?.lyrics_en && (
                <div className="studio-preview">
                  <label>가사 (EN)</label>
                  <pre className="lyrics-preview">{assets.lyrics_en.slice(0, 500)}</pre>
                </div>
              )}
              {youtubeMeta?.url && (
                <div className="studio-preview">
                  <label>YouTube</label>
                  <a href={youtubeMeta.url} target="_blank" rel="noreferrer">{youtubeMeta.url}</a>
                </div>
              )}
              <div className="studio-actions">
                <div className="form-row">
                  <div className="form-group">
                    <label>파이프라인 출력 단계</label>
                    <select value={pipelineTarget} onChange={(e) => setPipelineTarget(e.target.value)}>
                      {stages.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    className="btn btn-primary"
                    onClick={handleRunPipeline}
                    disabled={busy || !status?.ffmpeg_available}
                  >
                    영상 생성 실행
                  </button>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>단계 이동</label>
                    <select value={moveTarget} onChange={(e) => setMoveTarget(e.target.value)}>
                      {stages.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button className="btn btn-secondary" onClick={handleMove} disabled={busy}>
                    폴더 이동
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => api.openPipelineFolder(selectedProject)}
                  >
                    탐색기
                  </button>
                </div>
                <div className="form-row" style={{ marginTop: "0.75rem" }}>
                  <button
                    className="btn btn-primary"
                    onClick={handleYoutubeUpload}
                    disabled={busy || !youtubeConnected}
                    title={!youtubeConnected ? "설정에서 YouTube 채널 연결 필요" : ""}
                  >
                    {busy ? "업로드 중..." : "유튜브 비공개 업로드"}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={handleYoutubePublish}
                    disabled={busy || !youtubeMeta?.video_id}
                  >
                    유튜브 공개
                  </button>
                  {!youtubeConnected && (
                    <span className="meta">설정에서 YouTube 연동 필요</span>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
