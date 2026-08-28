import { useEffect, useState } from "react";
import { api, FavoriteTrack } from "../api";
import Modal from "../components/Modal";

export default function AnalyzePage() {
  const [tracks, setTracks] = useState<FavoriteTrack[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<FavoriteTrack | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [form, setForm] = useState({ title: "", artist: "", lyrics: "", notes: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = () => {
    api.listFavoriteTracks().then(setTracks).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async () => {
    if (!form.title.trim()) {
      setError("곡 제목을 입력하세요");
      return;
    }
    try {
      const track = await api.createFavoriteTrack(form);
      setShowCreate(false);
      setForm({ title: "", artist: "", lyrics: "", notes: "" });
      setSelected(track);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "생성 실패");
    }
  };

  const handleAnalyze = async (track: FavoriteTrack) => {
    setAnalyzing(true);
    setError("");
    setMessage("");
    try {
      const result = await api.analyzeFavoriteTrack(track.id);
      setMessage("분석 완료!");
      setSelected({ ...track, analysis_json: JSON.stringify(result.analysis), suno_prompt: result.suno_prompt });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "분석 실패. 설정에서 API 키를 확인하세요.");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleCreateProfile = async (trackId: number) => {
    try {
      const result = await api.createProfileFromTrack(trackId);
      setMessage(`음악 프로필이 생성되었습니다 (ID: ${result.profile_id})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "프로필 생성 실패");
    }
  };

  const copyPrompt = (prompt: string) => {
    navigator.clipboard.writeText(prompt);
    setMessage("프롬프트가 클립보드에 복사되었습니다.");
  };

  const parsedAnalysis = selected?.analysis_json
    ? JSON.parse(selected.analysis_json)
    : null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>취향 곡 분석</h2>
          <p>좋아하는 곡을 넣으면 AI가 분석해 Suno 프롬프트를 만들어줍니다</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + 곡 추가
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success-banner">{message}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "1.5rem" }}>
        <div className="card">
          <div className="card-title">내 취향 곡</div>
          {loading ? (
            <div className="loading">불러오는 중...</div>
          ) : tracks.length === 0 ? (
            <div className="empty-state">
              <p>곡을 추가하고 분석해보세요</p>
            </div>
          ) : (
            <ul className="track-list">
              {tracks.map((t) => (
                <li
                  key={t.id}
                  className={`track-item ${selected?.id === t.id ? "selected" : ""}`}
                  onClick={() => setSelected(t)}
                >
                  <div className="track-info">
                    <h4>{t.title}</h4>
                    <p>{t.artist || "아티스트 미상"}</p>
                  </div>
                  {t.suno_prompt && <span className="badge">분석됨</span>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          {selected ? (
            <>
              <div className="card-title">
                {selected.title}
                {selected.artist && ` — ${selected.artist}`}
              </div>

              {selected.notes && (
                <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
                  {selected.notes}
                </p>
              )}

              <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
                <button
                  className="btn btn-primary"
                  onClick={() => handleAnalyze(selected)}
                  disabled={analyzing}
                >
                  {analyzing ? "분석 중..." : "AI 분석"}
                </button>
                {selected.suno_prompt && (
                  <>
                    <button
                      className="btn btn-secondary"
                      onClick={() => copyPrompt(selected.suno_prompt!)}
                    >
                      프롬프트 복사
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleCreateProfile(selected.id)}
                    >
                      프로필로 저장
                    </button>
                  </>
                )}
                <label className="btn btn-secondary" style={{ cursor: "pointer" }}>
                  음원 업로드
                  <input
                    type="file"
                    accept="audio/*"
                    hidden
                    onChange={async (e) => {
                      if (e.target.files?.[0]) {
                        await api.uploadFavoriteAudio(selected.id, e.target.files[0]);
                        setMessage("음원 업로드 완료");
                      }
                    }}
                  />
                </label>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={async () => {
                    if (confirm("삭제하시겠습니까?")) {
                      await api.deleteFavoriteTrack(selected.id);
                      setSelected(null);
                      load();
                    }
                  }}
                >
                  삭제
                </button>
              </div>

              {parsedAnalysis && (
                <div style={{ marginBottom: "1rem" }}>
                  <h4 style={{ fontSize: "0.9rem", marginBottom: "0.5rem" }}>분석 결과</h4>
                  <div className="analysis-grid">
                    {parsedAnalysis.genre && <span className="badge">{parsedAnalysis.genre}</span>}
                    {parsedAnalysis.mood && <span className="badge">{parsedAnalysis.mood}</span>}
                    {parsedAnalysis.tempo_bpm && <span className="badge">{parsedAnalysis.tempo_bpm} BPM</span>}
                  </div>
                  {parsedAnalysis.summary && (
                    <p style={{ fontSize: "0.85rem", marginTop: "0.75rem", color: "var(--text-secondary)" }}>
                      {parsedAnalysis.summary}
                    </p>
                  )}
                </div>
              )}

              {selected.suno_prompt && (
                <div>
                  <h4 style={{ fontSize: "0.9rem", marginBottom: "0.5rem" }}>Suno 프롬프트</h4>
                  <textarea value={selected.suno_prompt} readOnly rows={4} />
                </div>
              )}

              {selected.lyrics && (
                <div style={{ marginTop: "1rem" }}>
                  <h4 style={{ fontSize: "0.9rem", marginBottom: "0.5rem" }}>가사</h4>
                  <textarea value={selected.lyrics} readOnly rows={8} />
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <h3>곡을 선택하세요</h3>
              <p>왼쪽에서 곡을 선택하거나 새 곡을 추가하세요</p>
              <p style={{ marginTop: "1rem", fontSize: "0.85rem" }}>
                팁: 곡명, 아티스트, 가사, 느낌 메모를 넣을수록 정확합니다
              </p>
            </div>
          )}
        </div>
      </div>

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="취향 곡 추가">
        {error && <div className="error">{error}</div>}
        <div className="form-group">
          <label>곡 제목 *</label>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <div className="form-group">
          <label>아티스트</label>
          <input value={form.artist} onChange={(e) => setForm({ ...form, artist: e.target.value })} />
        </div>
        <div className="form-group">
          <label>가사 (있으면 더 정확)</label>
          <textarea
            value={form.lyrics}
            onChange={(e) => setForm({ ...form, lyrics: e.target.value })}
            rows={6}
          />
        </div>
        <div className="form-group">
          <label>이 곡의 느낌 / 좋아하는 이유</label>
          <textarea
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={3}
            style={{ fontFamily: "var(--font)" }}
            placeholder="예: 몽환적인 신스 사운드, 여성 보컬의 감성적인 느낌..."
          />
        </div>
        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>취소</button>
          <button className="btn btn-primary" onClick={handleCreate}>추가</button>
        </div>
      </Modal>
    </div>
  );
}
