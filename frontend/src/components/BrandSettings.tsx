import { useEffect, useState } from "react";
import { api, ChannelBrand, DescBlockDef } from "../api";

/** 설정 페이지 오른쪽 탭: 유튜브 자동 게시 — 채널 브랜드 + 워터마크 */
export function BrandSettingsTab({ notify }: { notify: (msg: string, isErr?: boolean) => void }) {
  const [brand, setBrand] = useState<ChannelBrand | null>(null);
  const [saving, setSaving] = useState(false);
  const [wmPreview, setWmPreview] = useState<{ url: string } | null>(null);

  useEffect(() => {
    api.getBrand().then(setBrand).catch((e) => notify(String(e), true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 아이콘 미리보기 (brand.icon_url 변경 시 갱신)
  useEffect(() => {
    if (!brand) return;
    setWmPreview(brand.icon_url ? { url: brand.icon_url } : null);
  }, [brand?.icon_url]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!brand) return <div className="loading">브랜드 설정을 불러오는 중...</div>;

  const patch = (p: Partial<ChannelBrand>) => setBrand({ ...brand, ...p });

  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.saveBrand(brand);
      setBrand(saved);
      notify("채널 브랜드 설정이 저장되었습니다. 새 인코딩부터 적용됩니다.");
    } catch (e) {
      notify(String(e), true);
    } finally {
      setSaving(false);
    }
  };

  const uploadIcon = async (file: File) => {
    try {
      const res = await api.uploadBrandIcon(file);
      setBrand({ ...brand, icon_url: res.icon_url });
      notify("채널 아이콘이 변경되었습니다.");
    } catch (e) {
      notify(String(e), true);
    }
  };

  const resetIcon = async () => {
    try {
      await api.resetBrandIcon();
      setBrand({ ...brand, icon_url: "" });
      notify("채널 아이콘을 초기화했습니다.");
    } catch (e) {
      notify(String(e), true);
    }
  };

  return (
    <div>
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div className="card-title">채널 브랜드</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
          여기에 저장한 채널 정보가 유튜브 설명 자동 블록·기본 태그·해시태그·썸네일 푸터에 자동 반영됩니다.
        </p>
        <div className="form-group">
          <label>채널 이름</label>
          <input value={brand.channel_name} onChange={(e) => patch({ channel_name: e.target.value })} />
        </div>
        <div className="form-group">
          <label>저작권 문구 (설명·썸네일 푸터)</label>
          <input
            value={brand.copyright_line}
            placeholder="© 채널이름"
            onChange={(e) => patch({ copyright_line: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>소스 URL (선택 — 빈 칸이면 설명에서 뺍니다)</label>
          <input value={brand.source_url} onChange={(e) => patch({ source_url: e.target.value })} />
        </div>
        <div className="form-group">
          <label>기본 해시태그 (쉼표 구분)</label>
          <input
            value={brand.default_hashtags}
            onChange={(e) => patch({ default_hashtags: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label>기본 태그 (쉼표 구분)</label>
          <textarea
            rows={3}
            value={(brand.default_tags || []).join(", ")}
            onChange={(e) =>
              patch({ default_tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })
            }
          />
        </div>
      </div>

      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div className="card-title">영상 워터마크</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
          영상 좌측/우측 상단에 채널 아이콘+이름을 표시합니다.
          끄고 유튜브의 <strong>브랜딩 워터마크</strong>(YouTube Studio → 사용자 지정 → 브랜딩)를 쓸 수도 있습니다.
        </p>
        <div className="form-group">
          <label className="editor-check" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox"
              checked={brand.watermark_enabled}
              onChange={(e) => patch({ watermark_enabled: e.target.checked })}
            />
            영상에 워터마크 표시
          </label>
        </div>
        {brand.watermark_enabled && (
          <>
            <div className="form-group">
              <label>표시 이름 (빈 칸이면 채널 이름 사용)</label>
              <input
                value={brand.watermark_label}
                placeholder={brand.channel_name}
                onChange={(e) => patch({ watermark_label: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>위치</label>
              <select
                value={brand.watermark_pos}
                onChange={(e) => patch({ watermark_pos: e.target.value as ChannelBrand["watermark_pos"] })}
              >
                <option value="top_left">좌측 상단</option>
                <option value="top_right">우측 상단</option>
                <option value="bottom_left">좌측 하단</option>
                <option value="bottom_right">우측 하단</option>
                <option value="custom">직접 지정 (X, Y)</option>
              </select>
            </div>
            {brand.watermark_pos === "custom" && (
              <div style={{ display: "flex", gap: "0.75rem" }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>X (픽셀, 1920 기준)</label>
                  <input
                    type="number"
                    value={brand.watermark_x}
                    onChange={(e) => patch({ watermark_x: Number(e.target.value) || 0 })}
                  />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label>Y (픽셀, 1080 기준)</label>
                  <input
                    type="number"
                    value={brand.watermark_y}
                    onChange={(e) => patch({ watermark_y: Number(e.target.value) || 0 })}
                  />
                </div>
              </div>
            )}
            <div className="form-group">
              <label>채널 아이콘 (PNG/JPG — 정사각 권장)</label>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <div className="editor-brand-icon">
                  {wmPreview?.url ? (
                    <img src={wmPreview.url} alt="채널 아이콘" />
                  ) : (
                    <span className="editor-brand-icon-empty">아이콘 없음</span>
                  )}
                </div>
                <label className="btn btn-secondary btn-sm" style={{ cursor: "pointer" }}>
                  아이콘 변경
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void uploadIcon(f);
                      e.target.value = "";
                    }}
                  />
                </label>
                {brand.icon_url && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => void resetIcon()}>
                    초기화
                  </button>
                )}
              </div>
            </div>
          </>
        )}
        {!brand.watermark_enabled && (
          <p className="meta">
            워터마크를 끄면 YouTube Studio의 브랜딩 워터마크 기능을 사용하세요 — 모든 영상에 자동 표시되며
            클릭 시 채널로 이동합니다.
          </p>
        )}
      </div>

      <div className="form-group">
        <label className="editor-check" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
          <input
            type="checkbox"
            checked={brand.footer_enabled}
            onChange={(e) => patch({ footer_enabled: e.target.checked })}
          />
          썸네일 템플릿 푸터를 브랜드 문구로 자동 채움
        </label>
      </div>

      <button className="btn btn-primary" onClick={() => void save()} disabled={saving}>
        {saving ? "저장 중..." : "브랜드 설정 저장"}
      </button>
    </div>
  );
}

/** 설정 페이지 오른쪽 탭: 유튜브 설명 위젯 — 블록 구성 편집 */
export function DescBlocksSettingsTab({ notify }: { notify: (msg: string, isErr?: boolean) => void }) {
  const [brand, setBrand] = useState<ChannelBrand | null>(null);
  const [available, setAvailable] = useState<DescBlockDef[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getBrand()
      .then((b) => {
        setBrand(b);
        setAvailable(b.available_blocks || []);
        setSelected(b.selected_blocks || b.desc_blocks || []);
      })
      .catch((e) => notify(String(e), true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!brand) return <div className="loading">설명 블록 설정을 불러오는 중...</div>;

  const labelOf = (id: string) => available.find((b) => b.id === id)?.label || id;
  const hintOf = (id: string) => available.find((b) => b.id === id)?.hint || "";

  const addBlock = (id: string) => {
    if (!selected.includes(id)) setSelected([...selected, id]);
  };

  const removeBlock = (id: string) => {
    setSelected(selected.filter((s) => s !== id));
  };

  const move = (idx: number, dir: -1 | 1) => {
    const next = [...selected];
    const j = idx + dir;
    if (j < 0 || j >= next.length) return;
    [next[idx], next[j]] = [next[j], next[idx]];
    setSelected(next);
  };

  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.saveBrand({ ...brand, desc_blocks: selected });
      setBrand(saved);
      notify("설명 블록 구성이 저장되었습니다. 6단계 미리보기부터 바로 적용됩니다.");
    } catch (e) {
      notify(String(e), true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div className="card-title">유튜브 설명 자동 구성</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
          왼쪽은 넣을 수 있는 블록, 오른쪽은 실제 설명에 들어갈 블록 순서입니다.
          순서를 바꾸거나 빼고 넣을 수 있고, 편집기 6단계 미리보기에 바로 반영됩니다.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div>
            <label style={{ fontWeight: 600, marginBottom: "0.5rem", display: "block" }}>넣을 수 있는 블록</label>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {available
                .filter((b) => !selected.includes(b.id))
                .map((b) => (
                  <button
                    key={b.id}
                    type="button"
                    className="btn btn-secondary btn-sm desc-block-item"
                    onClick={() => addBlock(b.id)}
                    title="오른쪽에 추가"
                  >
                    <span className="desc-block-label">{b.label}</span>
                    <span className="meta">{b.hint}</span>
                    <span className="desc-block-add">＋</span>
                  </button>
                ))}
              {available.filter((b) => !selected.includes(b.id)).length === 0 && (
                <p className="meta">모든 블록이 선택되어 있습니다.</p>
              )}
            </div>
          </div>
          <div>
            <label style={{ fontWeight: 600, marginBottom: "0.5rem", display: "block" }}>
              설명에 들어갈 블록 (위에서부터 순서대로)
            </label>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
              {selected.map((id, idx) => (
                <div key={id} className="desc-block-selected">
                  <div className="desc-block-info">
                    <span className="desc-block-label">{labelOf(id)}</span>
                    <span className="meta">{hintOf(id)}</span>
                  </div>
                  <div className="desc-block-controls">
                    <button type="button" className="btn btn-sm" disabled={idx === 0} onClick={() => move(idx, -1)}>
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={idx === selected.length - 1}
                      onClick={() => move(idx, 1)}
                    >
                      ↓
                    </button>
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => removeBlock(id)}>
                      빼기
                    </button>
                  </div>
                </div>
              ))}
              {selected.length === 0 && <p className="meta">블록을 추가하세요. 빈 설명은 저장할 수 없습니다.</p>}
            </div>
          </div>
        </div>

        {selected.includes("custom") && (
          <div className="form-group" style={{ marginTop: "1rem" }}>
            <label>자유 블록 내용 (설명에 그대로 들어갑니다)</label>
            <textarea
              rows={4}
              value={brand.custom_desc_block || ""}
              onChange={(e) => setBrand({ ...brand, custom_desc_block: e.target.value })}
            />
          </div>
        )}
      </div>

      <button className="btn btn-primary" onClick={() => void save()} disabled={saving || selected.length === 0}>
        {saving ? "저장 중..." : "설명 블록 구성 저장"}
      </button>
    </div>
  );
}
