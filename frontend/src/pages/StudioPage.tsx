import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [config, setConfig] = useState<PipelineConfig | null>(null);
  const [stages, setStages] = useState<WorkflowStage[]>([]);
  const [workRoot, setWorkRoot] = useState("");
  const [browsePath, setBrowsePath] = useState("");
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  /** 다중 선택 (Ctrl/Shift). 순서는 선택 순서 유지 */
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]);
  const lastIndexRef = useRef<number | null>(null);
  const [assets, setAssets] = useState<ProjectAssets | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [moveTarget, setMoveTarget] = useState("review");
  const [pipelineTarget, setPipelineTarget] = useState("review");
  const [playlistTitle, setPlaylistTitle] = useState("");
  const [playlistSubtitle, setPlaylistSubtitle] = useState("");
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

  const isProjectEntry = (entry: BrowseEntry) =>
    entry.is_dir && entry.kind === "project";

  const openStage = (stage: WorkflowStage) => {
    loadBrowse(stage.folder);
    setSelectedProject(null);
    setSelectedProjects([]);
    lastIndexRef.current = null;
  };

  const applySingleSelect = (path: string) => {
    setSelectedProjects([path]);
    setSelectedProject(path);
  };

  const handleProjectClick = (e: MouseEvent, entry: BrowseEntry, index: number) => {
    e.preventDefault();
    e.stopPropagation();
    const path = entry.path;

    if (e.ctrlKey || e.metaKey) {
      setSelectedProjects((prev) => {
        const exists = prev.includes(path);
        const next = exists ? prev.filter((p) => p !== path) : [...prev, path];
        setSelectedProject(next.length ? next[next.length - 1] : null);
        return next;
      });
      lastIndexRef.current = index;
      return;
    }

    if (e.shiftKey && lastIndexRef.current != null) {
      const from = Math.min(lastIndexRef.current, index);
      const to = Math.max(lastIndexRef.current, index);
      const range = entries
        .slice(from, to + 1)
        .filter((en) => isProjectEntry(en))
        .map((en) => en.path);
      setSelectedProjects(range);
      setSelectedProject(path);
      return;
    }

    applySingleSelect(path);
    lastIndexRef.current = index;
  };

  const openEntry = (entry: BrowseEntry) => {
    if (entry.is_dir) {
      if (isProjectEntry(entry)) {
        // 프로젝트는 클릭으로 선택만 (더블클릭으로 진입)
        return;
      }
      loadBrowse(relPath(workRoot, entry.path));
      setSelectedProject(null);
      setSelectedProjects([]);
      lastIndexRef.current = null;
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
    setSelectedProjects([]);
    lastIndexRef.current = null;
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
      // 완료/실패까지 폴링 (상단 배너와 메시지 동기화)
      const jobId = res.job_id;
      for (let i = 0; i < 180; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await api.getQueueJob(jobId).catch(() => null);
        if (!job) break;
        if (job.message) {
          setMessage(`영상 파이프라인: ${job.message}${job.total ? ` · ${job.progress}/${job.total}` : ""}`);
        }
        if (job.status === "completed") {
          setMessage(`영상 생성 완료 — 검수대기 폴더를 확인하세요`);
          await refresh();
          const stage = stages.find((s) => s.id === pipelineTarget);
          if (stage) await loadBrowse(stage.folder);
          break;
        }
        if (job.status === "failed") {
          setMessage(`영상 생성 실패: ${job.message || "알 수 없는 오류"}`);
          break;
        }
      }
    } catch (e) {
      setMessage(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRunPlaylist = async () => {
    if (selectedProjects.length < 2) {
      setMessage("합본 영상은 Ctrl/Shift로 프로젝트를 2개 이상 선택하세요.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const paths = selectedProjects.map((p) => relPath(workRoot, p));
      const res = await api.runPlaylistPipeline({
        project_paths: paths,
        title: playlistTitle.trim() || undefined,
        subtitle: playlistSubtitle.trim() || undefined,
        target_stage: pipelineTarget,
      });
      setMessage(res.message);
      setSelectedProjects([res.path]);
      setSelectedProject(res.path);
      await refresh();
      const stage = stages.find((s) => s.id === pipelineTarget);
      if (stage) await loadBrowse(stage.folder);
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
      setSelectedProjects([res.path]);
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
      const res = await api.uploadToYoutube(rel, { privacyStatus: "private" }, (job) => {
        setMessage(`유튜브 업로드 ${job.percent}% · ${(job.bytes_sent / (1024 * 1024)).toFixed(1)} MB`);
      });
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

  const clearMultiSelect = () => {
    setSelectedProjects([]);
    setSelectedProject(null);
    lastIndexRef.current = null;
  };

  if (loading) return <div className="loading">스튜디오 불러오는 중...</div>;

  const multiCount = selectedProjects.length;

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
        {multiCount > 0 && (
          <span className="badge badge-ok">선택 {multiCount}개</span>
        )}
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
            {multiCount > 0 && (
              <button type="button" className="btn btn-secondary btn-sm" onClick={clearMultiSelect}>
                선택 해제
              </button>
            )}
          </div>
          <p className="studio-multiselect-hint meta">
            단계 → 앨범 폴더 → 곡(01~) · 곡은 Ctrl(⌘)/Shift 다중선택 · 더블클릭으로 폴더 열기
          </p>
          <ul className="studio-file-list">
            {entries.length === 0 && <li className="empty">비어 있음</li>}
            {entries.map((entry, index) => {
              const selected = selectedProjects.includes(entry.path);
              const order = selected ? selectedProjects.indexOf(entry.path) + 1 : 0;
              return (
                <li key={entry.path}>
                  <button
                    type="button"
                    className={`studio-file-item ${selected ? "selected" : ""}`}
                    onClick={(e) => {
                      if (isProjectEntry(entry)) {
                        handleProjectClick(e, entry, index);
                      } else {
                        openEntry(entry);
                      }
                    }}
                    onDoubleClick={() => {
                      if (entry.is_dir) {
                        loadBrowse(relPath(workRoot, entry.path));
                      }
                    }}
                  >
                    <span className="file-icon">
                      {entry.kind === "album"
                        ? "💿"
                        : entry.kind === "project"
                          ? "🎵"
                          : entry.is_dir
                            ? "📁"
                            : entry.kind === "audio"
                              ? "🎵"
                              : entry.kind === "image"
                                ? "🖼"
                                : "📄"}
                    </span>
                    {order > 0 && <span className="file-order">{order}</span>}
                    <span className="file-name">{entry.name}</span>
                    <span className="file-meta">{formatSize(entry.size)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="card studio-detail">
          {multiCount >= 2 ? (
            <>
              <div className="card-title">합본 플레이리스트 ({multiCount}곡)</div>
              <p className="meta">
                WHICK 서버 playlist 파이프라인과 동일: 음원 연결 · EN/KO 자막 · 챕터 설명 · 썸네일
              </p>
              <ol className="studio-playlist-order">
                {selectedProjects.map((p) => (
                  <li key={p}>{p.split(/[/\\]/).pop()}</li>
                ))}
              </ol>
              <div className="form-group">
                <label>플레이리스트 제목</label>
                <input
                  value={playlistTitle}
                  onChange={(e) => setPlaylistTitle(e.target.value)}
                  placeholder="예: Midnight Dreams Full Album"
                />
              </div>
              <div className="form-group">
                <label>부제 (선택)</label>
                <input
                  value={playlistSubtitle}
                  onChange={(e) => setPlaylistSubtitle(e.target.value)}
                  placeholder="예: Soft Pop Collection"
                />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>출력 단계</label>
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
                  onClick={handleRunPlaylist}
                  disabled={busy || !status?.ffmpeg_available}
                >
                  {busy ? "합본 생성 중..." : `${multiCount}곡 → 영상 하나 만들기`}
                </button>
              </div>
            </>
          ) : !selectedProject ? (
            <div className="empty-state">
              <h3>프로젝트 선택</h3>
              <p>앨범 폴더를 연 뒤 곡(01…)을 클릭하세요</p>
              <p className="meta" style={{ marginTop: "1rem" }}>
                여러 곡을 Ctrl/Shift로 고른 뒤 합본 영상 하나로 만들 수 있습니다.
              </p>
              <p className="meta" style={{ marginTop: "0.5rem" }}>
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
                  <button
                    className="btn btn-secondary"
                    type="button"
                    onClick={() => {
                      const rel = relPath(workRoot, selectedProject!);
                      navigate(`/editor?path=${encodeURIComponent(rel)}&step=2`);
                    }}
                  >
                    8단계 편집기
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
