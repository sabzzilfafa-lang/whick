import { useEffect, useState } from "react";
import { MusicProfile, Preset, api } from "../api";
import ActiveStyleBar, { notifyStyleChanged } from "../components/ActiveStyleBar";
import Modal from "../components/Modal";

const STYLE_TAGS = [
  "재즈", "Lo-fi", "칠합", "하우스", "신스웨이브", "펑크", "트랩", "R&B", "K-Pop", "시티팝",
  "락", "메탈", "시네마틱", "애니", "카페", "공부", "운동", "수면", "감성",
];

const EMPTY_FORM = {
  name: "",
  description: "",
  genre: "",
  mood: "",
  tempo_bpm: 120,
  key_signature: "",
  vocal_style: "",
  instruments: "",
  production_style: "",
  reference_artists: "",
  extra_notes: "",
  tags: "",
  emoji: "🎵",
};

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<MusicProfile[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [tagFilter, setTagFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    const [p, pr, active, cats] = await Promise.all([
      api.listProfiles(),
      api.listPresets(),
      api.getActiveProfile(),
      api.listPresetCategories(),
    ]);
    setProfiles(p);
    setPresets(pr);
    setCategories(cats);
    setActiveId(active?.id ?? null);
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, []);

  const handleLoadBuiltin = async (presetId: string) => {
    try {
      const profile = await api.loadPreset(presetId);
      setMessage(`「${profile.name}」스타일을 불러왔습니다`);
      setActiveId(profile.id);
      notifyStyleChanged();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "불러오기 실패");
    }
  };

  const handleLoadProfile = async (id: number) => {
    try {
      const profile = await api.activateProfile(id);
      setMessage(`「${profile.name}」스타일을 불러왔습니다`);
      setActiveId(profile.id);
      notifyStyleChanged();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "불러오기 실패");
    }
  };

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError("");
    setShowModal(true);
  };

  const openEdit = (p: MusicProfile) => {
    setEditingId(p.id);
    setForm({
      name: p.name,
      description: p.description || "",
      genre: p.genre || "",
      mood: p.mood || "",
      tempo_bpm: p.tempo_bpm || 120,
      key_signature: p.key_signature || "",
      vocal_style: p.vocal_style || "",
      instruments: p.instruments || "",
      production_style: p.production_style || "",
      reference_artists: p.reference_artists || "",
      extra_notes: p.extra_notes || "",
      tags: p.tags || "",
      emoji: p.emoji || "🎵",
    });
    setShowModal(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError("프리셋 이름을 입력하세요");
      return;
    }
    try {
      if (editingId) {
        await api.updateProfile(editingId, form);
        setMessage("프리셋이 수정되었습니다");
      } else {
        const created = await api.createProfile(form);
        await api.activateProfile(created.id);
        setMessage(`「${created.name}」프리셋을 저장하고 불러왔습니다`);
        notifyStyleChanged();
      }
      setShowModal(false);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handleDuplicate = async (id: number) => {
    await api.duplicateProfile(id);
    load();
  };

  const handleDelete = async (id: number) => {
    if (!confirm("이 프리셋을 삭제하시겠습니까?")) return;
    await api.deleteProfile(id);
    load();
  };

  const filteredPresets = presets.filter((p) => {
    if (categoryFilter && p.category !== categoryFilter) return false;
    if (tagFilter && !p.tags?.includes(tagFilter)) return false;
    return true;
  });

  const presetsByCategory = filteredPresets.reduce<Record<string, Preset[]>>((acc, p) => {
    const cat = p.category || "기타";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(p);
    return acc;
  }, {});

  const presetCategoryOrder = categoryFilter
    ? [categoryFilter]
    : categories.length > 0
      ? categories
      : Object.keys(presetsByCategory);

  const filteredProfiles = tagFilter
    ? profiles.filter((p) => p.tags?.includes(tagFilter))
    : profiles;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>스타일 프리셋</h2>
          <p>DAW 프리셋처럼 음악 성향을 저장하고, 그날그날 불러와 사용하세요</p>
        </div>
        <button className="btn btn-primary" onClick={openCreate}>
          + 내 프리셋 저장
        </button>
      </div>

      <ActiveStyleBar />

      {error && <div className="error">{error}</div>}
      {message && <div className="success-banner">{message}</div>}

      <div className="tag-filter">
        <button
          className={`btn btn-sm ${!categoryFilter ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setCategoryFilter("")}
        >
          전체 카테고리
        </button>
        {categories.map((c) => (
          <button
            key={c}
            className={`btn btn-sm ${categoryFilter === c ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setCategoryFilter(c)}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="tag-filter" style={{ marginTop: "0.5rem" }}>
        <button
          className={`btn btn-sm ${!tagFilter ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setTagFilter("")}
        >
          전체 태그
        </button>
        {STYLE_TAGS.map((t) => (
          <button
            key={t}
            className={`btn btn-sm ${tagFilter === t ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setTagFilter(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div className="card-title">기본 프리셋 ({filteredPresets.length}개)</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
          유튜브 플레이리스트처럼 카테고리별로 정리된 스타일 — 클릭하면 즉시 불러옵니다
        </p>
        {filteredPresets.length === 0 ? (
          <div className="empty-state" style={{ padding: "1.5rem" }}>
            <p>조건에 맞는 프리셋이 없습니다</p>
          </div>
        ) : (
          presetCategoryOrder.map((cat) => {
            const items = presetsByCategory[cat];
            if (!items?.length) return null;
            return (
              <div key={cat} className="preset-category-section">
                <h3 className="preset-category-title">{cat}</h3>
                <div className="preset-grid">
                  {items.map((p) => (
                    <button
                      key={p.id}
                      className="preset-card"
                      onClick={() => handleLoadBuiltin(p.id)}
                      title={p.description}
                    >
                      <span className="preset-emoji">{p.emoji || "🎵"}</span>
                      <h4>{p.name}</h4>
                      <p>{p.description}</p>
                      {p.tags && (
                        <div className="preset-tags">
                          {p.tags.split(",").slice(0, 3).map((t) => (
                            <span key={t} className="badge">{t.trim()}</span>
                          ))}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="card-title">내 프리셋</div>
      {loading ? (
        <div className="loading">불러오는 중...</div>
      ) : filteredProfiles.length === 0 ? (
        <div className="empty-state">
          <h3>저장된 프리셋이 없습니다</h3>
          <p>기본 프리셋을 불러오거나, 직접 만들어 저장하세요</p>
        </div>
      ) : (
        <div className="preset-grid">
          {filteredProfiles.map((p) => (
            <div
              key={p.id}
              className={`preset-card preset-card-owned ${activeId === p.id ? "active" : ""}`}
            >
              <button className="preset-load-area" onClick={() => handleLoadProfile(p.id)}>
                <span className="preset-emoji">{p.emoji || "🎵"}</span>
                <h4>{p.name}</h4>
                <p>{p.description || [p.genre, p.mood].filter(Boolean).join(" · ")}</p>
                {p.tags && (
                  <div className="preset-tags">
                    {p.tags.split(",").slice(0, 3).map((t) => (
                      <span key={t} className="badge">{t.trim()}</span>
                    ))}
                  </div>
                )}
                {activeId === p.id && <span className="preset-active-label">적용 중</span>}
              </button>
              <div className="preset-actions">
                <button className="btn btn-sm btn-secondary" onClick={() => openEdit(p)}>
                  수정
                </button>
                <button className="btn btn-sm btn-secondary" onClick={() => handleDuplicate(p.id)}>
                  복제
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(p.id)}>
                  삭제
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={showModal}
        onClose={() => setShowModal(false)}
        title={editingId ? "프리셋 수정" : "내 프리셋 저장"}
        disableOverlayClose
      >
        {error && <div className="error">{error}</div>}
        <div className="form-row">
          <div className="form-group">
            <label>이모지</label>
            <input
              value={form.emoji}
              onChange={(e) => setForm({ ...form, emoji: e.target.value })}
              style={{ width: "60px" }}
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label>프리셋 이름 *</label>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="예: 비 오는 날 카페 스타일"
            />
          </div>
        </div>
        <div className="form-group">
          <label>태그 (쉼표 구분)</label>
          <input
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
            placeholder="예: 카페,피아노,잔잔"
          />
        </div>
        <div className="form-group">
          <label>설명</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={2}
            style={{ fontFamily: "var(--font)" }}
          />
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>장르</label>
            <input value={form.genre} onChange={(e) => setForm({ ...form, genre: e.target.value })} />
          </div>
          <div className="form-group">
            <label>분위기</label>
            <input value={form.mood} onChange={(e) => setForm({ ...form, mood: e.target.value })} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>템포 (BPM)</label>
            <input
              type="number"
              value={form.tempo_bpm}
              onChange={(e) => setForm({ ...form, tempo_bpm: Number(e.target.value) })}
            />
            <p className="panel-hint" style={{ marginTop: "0.35rem" }}>
              기준값입니다. 곡마다 가사·분위기에 따라 ±5 범위
              ({Math.max(40, (form.tempo_bpm || 80) - 5)}~
              {(form.tempo_bpm || 80) + 5})에서 자동 결정됩니다.
            </p>
          </div>
          <div className="form-group">
            <label>보컬</label>
            <input
              value={form.vocal_style}
              onChange={(e) => setForm({ ...form, vocal_style: e.target.value })}
            />
          </div>
        </div>
        <div className="form-group">
          <label>악기</label>
          <input
            value={form.instruments}
            onChange={(e) => setForm({ ...form, instruments: e.target.value })}
            placeholder="예: 피아노, 드럼, 신스"
          />
        </div>
        <div className="form-group">
          <label>프로덕션 스타일</label>
          <input
            value={form.production_style}
            onChange={(e) => setForm({ ...form, production_style: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>참고 아티스트</label>
          <input
            value={form.reference_artists}
            onChange={(e) => setForm({ ...form, reference_artists: e.target.value })}
          />
        </div>
        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={() => setShowModal(false)}>취소</button>
          <button className="btn btn-primary" onClick={handleSave}>
            {editingId ? "수정" : "저장 & 불러오기"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
