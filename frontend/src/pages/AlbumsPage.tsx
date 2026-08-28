import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { Album, MusicProfile, api } from "../api";

import Modal from "../components/Modal";



export default function AlbumsPage() {
  const [albums, setAlbums] = useState<Album[]>([]);

  const [profiles, setProfiles] = useState<MusicProfile[]>([]);

  const [loading, setLoading] = useState(true);

  const [showCreate, setShowCreate] = useState(false);

  const [form, setForm] = useState({

    title: "",

    concept: "",

    mood: "",

    target_duration_min: 40,

    track_count: 10,

    music_profile_id: undefined as number | undefined,

  });

  const [error, setError] = useState("");



  const load = () => {

    Promise.all([api.listAlbums(), api.listProfiles()])

      .then(([a, p]) => {

        setAlbums(a);

        setProfiles(p);

      })

      .finally(() => setLoading(false));

  };



  useEffect(load, []);



  const openCreate = async () => {

    const active = await api.getActiveProfile();

    setForm({

      title: "",

      concept: "",

      mood: "",

      target_duration_min: 40,

      track_count: 10,

      music_profile_id: active?.id,

    });

    setShowCreate(true);

  };



  const handleCreate = async () => {

    if (!form.title.trim()) {

      setError("앨범 제목을 입력하세요");

      return;

    }

    try {

      await api.createAlbum(form);

      setShowCreate(false);

      setForm({

        title: "",

        concept: "",

        mood: "",

        target_duration_min: 40,

        track_count: 10,

        music_profile_id: undefined,

      });

      load();

    } catch (e) {

      setError(e instanceof Error ? e.message : "생성 실패");

    }

  };



  const handleDelete = async (album: Album, e: React.MouseEvent) => {

    e.preventDefault();

    e.stopPropagation();

    if (!confirm(`「${album.title}」 앨범을 삭제하시겠습니까?`)) return;

    try {

      await api.deleteAlbum(album.id);

      load();

    } catch (err) {

      setError(err instanceof Error ? err.message : "삭제 실패");

    }

  };



  return (

    <div>

      <div className="page-header">

        <div>

          <h2>앨범</h2>

          <p>앨범 단위로 기획하고 곡을 관리하세요</p>

        </div>

        <button className="btn btn-primary" onClick={openCreate}>

          + 새 앨범

        </button>

      </div>



      {error && <div className="error">{error}</div>}



      {loading ? (

        <div className="loading">불러오는 중...</div>

      ) : albums.length === 0 ? (

        <div className="empty-state">

          <h3>앨범이 없습니다</h3>

          <p>새 앨범을 만들어 프로젝트를 시작하세요</p>

        </div>

      ) : (

        <div className="album-grid">

          {albums.map((album) => (

            <div key={album.id} className="album-card-wrap">

              <Link to={`/albums/${album.id}`} className="album-card">

                <h3>{album.title}</h3>

                {album.mood && <span className="badge">{album.mood}</span>}

                {album.concept && (

                  <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>

                    {album.concept.slice(0, 80)}

                    {album.concept.length > 80 ? "..." : ""}

                  </p>

                )}

                <p className="meta" style={{ marginTop: "0.5rem" }}>

                  {album.track_count}곡

                  {album.target_duration_min && ` · 목표 ${album.target_duration_min}분`}

                </p>

              </Link>

              <button

                type="button"

                className="btn btn-danger btn-sm album-card-delete"

                onClick={(e) => handleDelete(album, e)}

              >

                삭제

              </button>

            </div>

          ))}

        </div>

      )}



      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="새 앨범 만들기">

        {error && <div className="error">{error}</div>}

        <div className="form-group">

          <label>앨범 제목 *</label>

          <input

            value={form.title}

            onChange={(e) => setForm({ ...form, title: e.target.value })}

            placeholder="예: Midnight Dreams"

          />

        </div>

        <div className="form-group">

          <label>기획 목표 / 컨셉</label>

          <textarea

            value={form.concept}

            onChange={(e) => setForm({ ...form, concept: e.target.value })}

            placeholder="이 앨범이 전달하고 싶은 이야기, 테마..."

            rows={3}

            style={{ fontFamily: "var(--font)" }}

          />

        </div>

        <div className="form-group">

          <label>앨범 분위기</label>

          <input

            value={form.mood}

            onChange={(e) => setForm({ ...form, mood: e.target.value })}

            placeholder="예: 몽환적, 우울한, 희망적"

          />

        </div>

        <div className="form-row">

          <div className="form-group">

            <label>곡 수</label>

            <input

              type="number"

              min={1}

              max={30}

              value={form.track_count}

              onChange={(e) => setForm({ ...form, track_count: Number(e.target.value) })}

            />

          </div>

          <div className="form-group">

            <label>목표 시간 (분)</label>

            <input

              type="number"

              min={1}

              value={form.target_duration_min}

              onChange={(e) =>

                setForm({ ...form, target_duration_min: Number(e.target.value) })

              }

            />

          </div>

        </div>

        <div className="form-group">

          <label>스타일 프리셋</label>

          <select

            value={form.music_profile_id ?? ""}

            onChange={(e) =>

              setForm({

                ...form,

                music_profile_id: e.target.value ? Number(e.target.value) : undefined,

              })

            }

          >

            <option value="">현재 스타일 없음</option>

            {profiles.map((p) => (

              <option key={p.id} value={p.id}>

                {p.emoji || "🎵"} {p.name}

              </option>

            ))}

          </select>

        </div>

        <div className="modal-actions">

          <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>

            취소

          </button>

          <button className="btn btn-primary" onClick={handleCreate}>

            만들기

          </button>

        </div>

      </Modal>

    </div>

  );

}


