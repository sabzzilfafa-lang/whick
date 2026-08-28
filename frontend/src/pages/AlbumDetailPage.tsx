import { useEffect, useRef, useState } from "react";

import { Link, useNavigate, useParams } from "react-router-dom";

import { AlbumDetail, MusicProfile, api } from "../api";

import { notifyStyleChanged } from "../components/ActiveStyleBar";

import Modal from "../components/Modal";

import { cleanTheme } from "../lib/theme";



export default function AlbumDetailPage() {

  const { id } = useParams<{ id: string }>();

  const navigate = useNavigate();

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


