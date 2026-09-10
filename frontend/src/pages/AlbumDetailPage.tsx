import { useEffect, useRef, useState } from "react";

import { Link, useNavigate, useParams } from "react-router-dom";

import { AlbumDetail, MusicProfile, api, albumThumbsApi, songImagesApi } from "../api";
import type { AlbumThumbFile, SongImageStatus } from "../api";

import { notifyStyleChanged } from "../components/ActiveStyleBar";

import Modal from "../components/Modal";

import { cleanTheme } from "../lib/theme";

import { useLang } from "../lib/i18n";



export default function AlbumDetailPage() {

  const { id } = useParams<{ id: string }>();

  const navigate = useNavigate();
  const { t } = useLang();

  const [album, setAlbum] = useState<AlbumDetail | null>(null);

  const [loading, setLoading] = useState(true);

  const [generating, setGenerating] = useState(false);

  const [showSimilar, setShowSimilar] = useState(false);

  const [refSongId, setRefSongId] = useState<number | null>(null);

  const [similarForm, setSimilarForm] = useState({ title: "", theme: "" });

  const [error, setError] = useState("");

  const [doneMsg, setDoneMsg] = useState("");

  const [profiles, setProfiles] = useState<MusicProfile[]>([]);

  const [styleMsg, setStyleMsg] = useState("");

  const [thumbFiles, setThumbFiles] = useState<AlbumThumbFile[]>([]);
  const [thumbBusy, setThumbBusy] = useState(false);
  const [thumbMsg, setThumbMsg] = useState("");
  const [thumbZoom, setThumbZoom] = useState<"A" | "B" | "C" | null>(null);
  const [thumbPrompts, setThumbPrompts] = useState<string[]>([]);
  // 썸네일 제목 표기 방식 — 설정에서 이동: 생성 화면 바로 아래 인라인 선택 (2026-09-10)
  const [thumbTitleMode, setThumbTitleMode] = useState<string>("ai");
  const [titleModeSaving, setTitleModeSaving] = useState(false);
  // 트랙 배경 이미지 (2026-09-10) — 곡별 재생 배경 AI 생성
  const [songImages, setSongImages] = useState<SongImageStatus[]>([]);
  const [songImgBusy, setSongImgBusy] = useState(false);
  const [songImgMsg, setSongImgMsg] = useState("");
  const [songImgZoom, setSongImgZoom] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => {

    if (pollRef.current) {

      clearInterval(pollRef.current);

      pollRef.current = null;

    }

  };



  const load = () => {

    if (!id) return;

    Promise.all([api.getAlbum(Number(id)), api.listProfiles()])

      .then(([a, p]) => {

        setAlbum(a);

        setProfiles(p);

      })

      .catch(() => navigate("/albums"))

      .finally(() => setLoading(false));

  };



  useEffect(() => {
    load();
    return () => stopPoll();
  }, [id]);

  /* --- 앨범 썸네일 3종 (2026-09-09) --- */
  const loadThumbs = () => {
    if (!id) return;
    albumThumbsApi
      .list(Number(id))
      .then((r) => setThumbFiles(r.files || []))
      .catch(() => setThumbFiles([]));
  };

  useEffect(() => {
    loadThumbs();
  }, [id]);

  // 제목 표기 방식 — 현재 설정 로드 (2026-09-10)
  useEffect(() => {
    api.getSettings().then((s) => setThumbTitleMode(String(s.thumbnail_title_mode || "ai"))).catch(() => {});
  }, []);

  // 트랙 배경 이미지 현황 로드 (2026-09-10)
  const loadSongImages = () => {
    if (!id) return;
    songImagesApi.list(Number(id)).then((r) => setSongImages(r.songs || [])).catch(() => setSongImages([]));
  };
  useEffect(() => {
    loadSongImages();
  }, [id]);

  const handleSongImagesGenerate = async (songIds?: number[]) => {
    if (!album) return;
    setSongImgBusy(true);
    setSongImgMsg(
      songIds && songIds.length === 1
        ? "해당 곡 배경 이미지 생성 중... (1~2분)"
        : `트랙 ${album.songs.length}곡 배경 이미지 순차 생성 중... (곡당 수십 초)`,
    );
    try {
      const res = await songImagesApi.generate(album.id, songIds ? { song_ids: songIds } : undefined);
      const gen = res.generated?.length || 0;
      const errs = res.errors || [];
      if (errs.length) {
        // 실패 원인을 바로 볼 수 있게 트랙·메시지 표시 (2026-09-10)
        const detail = errs
          .slice(0, 3)
          .map((x) => `#${x.track ?? "?"}: ${x.error || "unknown"}`)
          .join(" / ");
        setSongImgMsg(`${t("실패")} ${errs.length}곡 — ${detail}${errs.length > 3 ? " …" : ""}`);
      } else {
        setSongImgMsg(`${t("완료")}: ${gen}/${album.songs.length} ${t("곡 생성")}`);
      }
      loadSongImages();
    } catch (e) {
      setSongImgMsg(String(e));
    } finally {
      setSongImgBusy(false);
    }
  };

  const saveThumbTitleMode = async (mode: string) => {
    setThumbTitleMode(mode);
    setTitleModeSaving(true);
    try {
      await api.updateSettings({ thumbnail_title_mode: mode });
    } catch {
      /* 설정 저장 실패는 조용히 무시 — 다음 저장 시 반영 */
    } finally {
      setTitleModeSaving(false);
    }
  };

  const handleThumbGenerate = async () => {
    if (!album) return;
    setThumbBusy(true);
    setThumbMsg("AI 썸네일 3장 생성 중... (1~2분)");
    try {
      const res = await albumThumbsApi.generate(album.id);
      setThumbFiles(res.files || []);
      setThumbPrompts(res.prompts || []);
      setThumbMsg(`생성 완료 — ${res.provider || ""} ${res.model || ""}`);
    } catch (e) {
      setThumbMsg(String(e));
    } finally {
      setThumbBusy(false);
    }
  };

  const handleThumbPreviewPrompts = async () => {
    if (!album) return;
    setThumbBusy(true);
    setThumbMsg("프롬프트 생성 중...");
    try {
      const res = await albumThumbsApi.makePrompts(album.id);
      setThumbPrompts(res.prompts || []);
      setThumbMsg("프롬프트 3개 생성 완료");
    } catch (e) {
      setThumbMsg(String(e));
    } finally {
      setThumbBusy(false);
    }
  };

  const handleThumbApply = async (variant: "A" | "B" | "C") => {
    if (!album) return;
    setThumbBusy(true);
    try {
      /* project_path 미지정 — 백엔드가 앨범 첫 곡 pipeline_path를 자동 선택 */
      await albumThumbsApi.apply(album.id, variant);
      setThumbMsg(`첫 곡 thumbnail.jpg를 ${variant}로 교체했습니다`);
      loadThumbs();
    } catch (e) {
      setThumbMsg(String(e));
    } finally {
      setThumbBusy(false);
    }
  };

  const handleThumbUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!album || !e.target.files?.[0]) return;
    setThumbBusy(true);
    setThumbMsg("");
    try {
      await albumThumbsApi.upload(album.id, e.target.files[0]);
      setThumbMsg("앨범 썸네일을 업로드했습니다 — 「첫 곡에 적용」으로 유튜브 목록 썸네일에 반영하세요");
      loadThumbs();
    } catch (err) {
      setThumbMsg(String(err));
    } finally {
      setThumbBusy(false);
      e.target.value = "";
    }
  };



  const handleGenerateAll = async () => {

    if (!album || !confirm(

      `${album.track_count}곡의 트랙 목록과 테마를 만듭니다.\n가사·악기·프롬프트는 각 곡 페이지에서 생성하세요.`

    ))

      return;

    setGenerating(true);

    setError("");

    setDoneMsg("");

    stopPoll();

    try {

      const job = await api.generateAlbumTracks(album.id);

      pollRef.current = setInterval(async () => {

        try {

          const j = await api.getQueueJob(job.id);

          if (j.status === "completed" || j.status === "failed") {

            stopPoll();

            setGenerating(false);

            setDoneMsg(

              j.status === "completed"

                ? j.message || "트랙 등록 완료!"

                : j.message || "등록 중 오류가 발생했습니다"

            );

            load();

          }

        } catch {

          stopPoll();

          setGenerating(false);

        }

      }, 2500);

    } catch (e) {

      setError(e instanceof Error ? e.message : "생성 실패");

      setGenerating(false);

    }

  };



  const handleRepairLyrics = async () => {
    if (!album) return;
    if (!confirm("첫 곡에 합쳐진 가사를 트랙별로 분리합니다. 계속할까요?")) return;
    setGenerating(true);
    setError("");
    setDoneMsg("");
    try {
      const res = await api.repairAlbumLyrics(album.id);
      setDoneMsg(`${res.recovered_tracks}곡 가사 복구 완료 (${res.updated}/${res.total})`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "가사 복구 실패");
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateAllLyrics = async () => {

    if (!album || !album.songs.length) return;

    if (

      !confirm(

        `${album.songs.length}곡 한글 가사를 5곡씩 나눠 생성합니다.\n2~3분 걸릴 수 있습니다.`

      )

    )

      return;

    setGenerating(true);

    setError("");

    setDoneMsg("");

    try {

      const res = await api.generateAlbumLyrics(album.id);

      setDoneMsg(`${res.updated}/${res.total}곡 가사 생성 완료 (${res.model_used})`);

      load();

    } catch (e) {

      setError(e instanceof Error ? e.message : "가사 일괄 생성 실패");

    } finally {

      setGenerating(false);

    }

  };



  const handleSimilar = async () => {

    if (!refSongId || !album || !similarForm.title.trim()) return;

    setGenerating(true);

    setError("");

    try {

      await api.generateSimilar({

        reference_song_id: refSongId,

        album_id: album.id,

        title: similarForm.title,

        theme: similarForm.theme || undefined,

      });

      setShowSimilar(false);

      setSimilarForm({ title: "", theme: "" });

      load();

    } catch (e) {

      setError(e instanceof Error ? e.message : "생성 실패");

    } finally {

      setGenerating(false);

    }

  };



  const handleDelete = async () => {

    if (!album || !confirm("앨범을 삭제하시겠습니까?")) return;

    await api.deleteAlbum(album.id);

    navigate("/albums");

  };



  const handleChangeStyle = async (profileId: number) => {

    if (!album) return;

    try {

      await api.applyProfileToAlbum(profileId, album.id);

      setStyleMsg("앨범 스타일이 변경되었습니다");

      notifyStyleChanged();

      load();

    } catch (e) {

      setError(e instanceof Error ? e.message : "스타일 변경 실패");

    }

  };



  if (loading) return <div className="loading">불러오는 중...</div>;

  if (!album) return null;



  return (

    <div>

      <div className="page-header album-detail-header">

        <div>

          <Link to="/albums" style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>

            ← 앨범 목록

          </Link>

          <h2 style={{ marginTop: "0.5rem" }}>{album.title}</h2>

          {album.mood && <span className="badge">{album.mood}</span>}

          {album.concept && (

            <p style={{ marginTop: "0.5rem", color: "var(--text-secondary)", fontSize: "0.9rem" }}>

              {album.concept}

            </p>

          )}

          <div className="album-detail-actions">

            <button

              className="btn btn-primary"

              onClick={handleGenerateAll}

              disabled={generating}

            >

              {generating ? "트랙 등록 중..." : "전체 곡 일괄 생성"}

            </button>

            <button

              className="btn btn-secondary"

              onClick={handleGenerateAllLyrics}

              disabled={generating || album.songs.length === 0}

            >

              {generating ? "가사 생성 중..." : "전체 한글 가사 일괄 생성"}

            </button>

            <button

              className="btn btn-secondary"

              onClick={handleRepairLyrics}

              disabled={generating || album.songs.length === 0}

            >

              {generating ? "복구 중..." : "합쳐진 가사 복구"}

            </button>

            <button className="btn btn-danger btn-sm" onClick={handleDelete}>

              삭제

            </button>

          </div>

        </div>

      </div>



      {error && <div className="error">{error}</div>}

      {doneMsg && <div className="success-banner">{doneMsg}</div>}

      {styleMsg && <div className="success-banner">{styleMsg}</div>}



      <div className="card" style={{ marginBottom: "1rem", padding: "1rem" }}>

        <label style={{ fontSize: "0.85rem", marginBottom: "0.35rem", display: "block" }}>

          이 앨범의 스타일 프리셋

        </label>

        <select

          value={album.music_profile_id ?? ""}

          onChange={(e) => handleChangeStyle(Number(e.target.value))}

        >

          <option value="" disabled>프리셋 선택...</option>

          {profiles.map((p) => (

            <option key={p.id} value={p.id}>

              {p.emoji || "🎵"} {p.name}

            </option>

          ))}

        </select>

      </div>

      <div className="card" style={{ marginBottom: "1rem", padding: "1rem" }}>
        <div className="card-title">유튜브 썸네일 3종 (AI 생성)</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", margin: "0.25rem 0 0.75rem" }}>
          앨범 커버와 콘셉트로 썸네일 후보 3장(A/B/C)을 만듭니다.
          유튜브 스튜디오의 「Test &amp; Compare」(썸네일 A/B 테스트)에 3장을 모두 올리면
          유튜브가 가장 클릭률이 높은 썸네일을 자동으로 대표 노출합니다.
        </p>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {(thumbFiles.length
            ? thumbFiles
            : ([
                { variant: "A" },
                { variant: "B" },
                { variant: "C" },
              ] as AlbumThumbFile[])
          ).map((f) => (
            <div
              key={f.variant}
              style={{
                width: 212,
                border: "1px solid var(--border, #ddd)",
                borderRadius: 8,
                overflow: "hidden",
                background: "var(--bg-secondary, #fafafa)",
              }}
            >
              {f.ready && f.variant && thumbFiles.length > 0 ? (
                <img
                  src={albumThumbsApi.thumbnailFileUrl(album.id, f.variant as "A" | "B" | "C")}
                  alt={`썸네일 ${f.variant}`}
                  onClick={() => setThumbZoom(f.variant as "A" | "B" | "C")}
                  style={{ width: "100%", display: "block", aspectRatio: "16/9", objectFit: "cover", cursor: "zoom-in" }}
                  title="클릭하면 큰 이미지로 볼 수 있습니다"
                />
              ) : (
                <div
                  style={{
                    width: "100%",
                    aspectRatio: "16/9",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--text-muted, #999)",
                    fontSize: "0.8rem",
                  }}
                >
                  미생성
                </div>
              )}
              <div
                style={{
                  padding: "0.4rem 0.5rem",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <strong style={{ fontSize: "0.85rem" }}>썸네일 {f.variant}</strong>
                {f.ready && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={thumbBusy}
                    onClick={() => handleThumbApply(f.variant as "A" | "B" | "C")}
                    title="첫 곡의 thumbnail.jpg로 적용"
                  >
                    첫 곡에 적용
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn btn-primary"
            disabled={thumbBusy}
            onClick={() => void handleThumbGenerate()}
          >
            {thumbBusy ? "생성 중..." : "썸네일 3장 AI 생성"}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={thumbBusy}
            onClick={() => void handleThumbPreviewPrompts()}
          >
            프롬프트만 먼저 보기
          </button>
          <label
            className="btn btn-secondary"
            style={{ cursor: "pointer" }}
            title="직접 만든 이미지를 앨범 썸네일로 올립니다 (첫 곡에 적용 가능)"
          >
            썸네일 파일 직접 올리기
            <input type="file" accept="image/*" onChange={handleThumbUpload} hidden />
          </label>
        </div>
        {thumbMsg && (
          <p style={{ fontSize: "0.85rem", marginTop: "0.5rem", color: "var(--text-secondary)" }}>
            {thumbMsg}
          </p>
        )}
        {thumbPrompts.length > 0 && (
          <div style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "var(--text-secondary)" }}>
            {thumbPrompts.map((p, i) => (
              <div key={i} style={{ marginBottom: "0.25rem" }}>
                <strong>{"ABC"[i]}</strong>: {p}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
          <label style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
            {t("제목 표기 방식")}
          </label>
          <select
            value={thumbTitleMode}
            disabled={titleModeSaving}
            onChange={(e) => void saveThumbTitleMode(e.target.value)}
            style={{ fontSize: "0.85rem" }}
          >
            <option value="ai">{t("AI 통합 렌더 (디자인 일체형)")}</option>
            <option value="overlay">{t("하단 바 표기 (글자 정확)")}</option>
          </select>
        </div>
      </div>

      {/* 트랙 배경 이미지 (2026-09-10) — 곡별 재생 배경 AI 생성 */}
      <div className="card" style={{ marginBottom: "1rem", padding: "1rem" }}>
        <div className="card-title">{t("트랙 배경 이미지 (AI 생성)")}</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", margin: "0.25rem 0 0.75rem" }}>
          {t("각 곡 제목·테마에 맞는 재생 배경 이미지를 트랙별로 생성합니다. 곡 재생 화면의 배경으로 사용됩니다.")}
        </p>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          {songImages.map((si) => (
            <div
              key={si.song_id}
              style={{
                width: 132,
                border: "1px solid var(--border, #ddd)",
                borderRadius: 8,
                overflow: "hidden",
                background: "var(--bg-secondary, #fafafa)",
                cursor: si.ready ? "zoom-in" : "default",
              }}
              onClick={() => si.ready && setSongImgZoom(si.song_id)}
              title={si.ready ? t("클릭하면 큰 이미지로 볼 수 있습니다") : t("미생성")}
            >
              {si.ready ? (
                <img
                  src={si.url}
                  alt={`트랙 ${si.track}`}
                  style={{ width: "100%", display: "block", aspectRatio: "16/9", objectFit: "cover" }}
                />
              ) : (
                <div style={{ width: "100%", aspectRatio: "16/9", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted, #999)", fontSize: "0.75rem" }}>
                  {t("미생성")}
                </div>
              )}
              <div style={{ padding: "0.3rem 0.45rem", fontSize: "0.78rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>#{si.track}</strong>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={songImgBusy}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleSongImagesGenerate([si.song_id]);
                  }}
                  style={{ padding: "0.1rem 0.45rem", fontSize: "0.72rem" }}
                >
                  {si.ready ? t("다시 생성") : t("생성")}
                </button>
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn btn-primary"
            disabled={songImgBusy}
            onClick={() => void handleSongImagesGenerate()}
          >
            {songImgBusy ? t("생성 중...") : t("전체 트랙 이미지 생성")}
          </button>
        </div>
        {songImgMsg && (
          <p style={{ fontSize: "0.85rem", marginTop: "0.5rem", color: "var(--text-secondary)" }}>
            {songImgMsg}
          </p>
        )}
      </div>

      {/* 트랙 배경 이미지 크게 보기 (2026-09-10) */}
      {songImgZoom !== null && (
        <div
          onClick={() => setSongImgZoom(null)}
          style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(0,0,0,0.88)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "2.5vh 2.5vw", cursor: "zoom-out",
          }}
        >
          <figure style={{ margin: 0, maxWidth: "95vw", textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
            <img
              src={`/api/songs/${songImgZoom}/cover-image?v=${songImages.find((si) => si.song_id === songImgZoom)?.url?.split("v=")[1] || Date.now()}`}
              alt="트랙 배경"
              style={{
                display: "block", maxWidth: "95vw", maxHeight: "88vh",
                width: "auto", height: "auto", borderRadius: 8,
                boxShadow: "0 8px 60px rgba(0,0,0,0.6)",
              }}
            />
            <div style={{ marginTop: "0.6rem", color: "#ddd", fontSize: "0.95rem" }}>
              {t("클릭하면 닫혀요")}
            </div>
          </figure>
        </div>
      )}

      {/* 썸네일 크게 보기 라이트박스 (2026-09-10, v0.9.37 대형화) */}
      {thumbZoom && (
        <div
          onClick={() => setThumbZoom(null)}
          style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(0,0,0,0.88)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "2.5vh 2.5vw", cursor: "zoom-out",
          }}
        >
          <figure style={{ margin: 0, maxWidth: "95vw", textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
            <img
              src={albumThumbsApi.thumbnailFileUrl(album.id, thumbZoom)}
              alt={`썸네일 ${thumbZoom}`}
              style={{
                display: "block", maxWidth: "95vw", maxHeight: "88vh",
                width: "auto", height: "auto", borderRadius: 8,
                boxShadow: "0 8px 60px rgba(0,0,0,0.6)",
              }}
            />
            <div style={{ marginTop: "0.6rem", color: "#ddd", fontSize: "0.95rem" }}>
              {t("썸네일")} {thumbZoom} — {t("클릭하면 닫혀요")}
            </div>
          </figure>
        </div>
      )}

      <div className="card">

        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1rem" }}>

          <div className="card-title" style={{ margin: 0 }}>

            트랙 리스트 ({album.songs.length}/{album.track_count})

          </div>

        </div>



        {album.songs.length === 0 ? (

          <div className="empty-state">

            <h3>곡이 없습니다</h3>

            <p>「전체 곡 일괄 생성」으로 트랙 테마 목록을 만든 뒤, 각 곡에서 가사·악기·프롬프트를 생성하세요</p>

          </div>

        ) : (

          <ul className="track-list">

            {album.songs.map((song) => (

              <li key={song.id} className="track-item">

                <span className="track-number">{song.track_number}</span>

                <Link to={`/songs/${song.id}`} style={{ flex: 1, color: "inherit" }}>

                  <div className="track-info">

                    <h4>{song.title}</h4>

                    {song.theme && <p>{cleanTheme(song.theme)}</p>}

                  </div>

                </Link>

                <div className="track-status">

                  <span

                    className={`status-dot ${song.lyrics_ko || song.lyrics ? "filled" : ""}`}

                    title="가사 (한글)"

                  />

                  <span

                    className={`status-dot ${song.lyrics_en ? "filled" : ""}`}

                    title="가사 (영어)"

                  />

                  <span

                    className={`status-dot ${song.instrument_settings ? "filled" : ""}`}

                    title="악기"

                  />

                  <span

                    className={`status-dot ${song.suno_prompt ? "filled" : ""}`}

                    title="프롬프트"

                  />

                  <span

                    className={`status-dot ${song.audio_path ? "filled" : ""}`}

                    title="음원"

                  />

                  <span

                    className={`status-dot ${(songImages.find((si) => si.song_id === song.id)?.ready) ? "filled" : ""}`}

                    title="배경 이미지"

                  />

                </div>

                <button

                  className="btn btn-secondary btn-sm"

                  onClick={() => {

                    setRefSongId(song.id);

                    setSimilarForm({ title: `${song.title} (유사)`, theme: "" });

                    setShowSimilar(true);

                  }}

                >

                  유사 곡

                </button>

              </li>

            ))}

          </ul>

        )}

      </div>



      <Modal open={showSimilar} onClose={() => setShowSimilar(false)} title="유사 곡 생성">

        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>

          선택한 곡과 같은 분위기로 가사, 프롬프트, 악기 세팅을 자동 생성합니다.

        </p>

        <div className="form-group">

          <label>새 곡 제목</label>

          <input

            value={similarForm.title}

            onChange={(e) => setSimilarForm({ ...similarForm, title: e.target.value })}

          />

        </div>

        <div className="form-group">

          <label>테마 (선택)</label>

          <input

            value={similarForm.theme}

            onChange={(e) => setSimilarForm({ ...similarForm, theme: e.target.value })}

            placeholder="비우면 참조 곡 분위기를 따릅니다"

          />

        </div>

        <div className="modal-actions">

          <button className="btn btn-secondary" onClick={() => setShowSimilar(false)}>

            취소

          </button>

          <button

            className="btn btn-primary"

            onClick={handleSimilar}

            disabled={generating}

          >

            {generating ? "생성 중..." : "생성"}

          </button>

        </div>

      </Modal>

    </div>

  );

}


