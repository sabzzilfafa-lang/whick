-- Whick 뮤직서버 PostgreSQL 스키마

CREATE TABLE IF NOT EXISTS tracks (
    track_id      BIGSERIAL PRIMARY KEY,
    title         VARCHAR(500) NOT NULL,
    artist        VARCHAR(300),
    album         VARCHAR(300),
    genre         VARCHAR(100),
    year          INT,
    duration_sec  INT,
    bit_depth     INT,          -- 16, 24, 32
    sample_rate   INT,          -- 44100, 48000, 88200, 96000, 192000
    format        VARCHAR(20),  -- FLAC, WAV, MP3, AAC
    file_path     TEXT NOT NULL UNIQUE,
    file_size     BIGINT,
    license       VARCHAR(200), -- Public Domain, CC-BY, 등
    source_url    TEXT,
    added_at      TIMESTAMPTZ DEFAULT now(),
    play_count    INT DEFAULT 0,
    last_played   TIMESTAMPTZ,
    quality       VARCHAR(20),  -- robot-classifier: dsd, hires-rate, hires-depth, hires-24-48, cd, reject
    quality_reasons TEXT,       -- 분류 로봇 판정 사유 (JSON array)
    composer      VARCHAR(300)  -- 작곡가 (클래식 등 · artist와 분리 가능)
);

CREATE INDEX idx_tracks_artist ON tracks(artist);
CREATE INDEX idx_tracks_album  ON tracks(album);
CREATE INDEX idx_tracks_genre  ON tracks(genre);
CREATE INDEX idx_tracks_search ON tracks USING gin(
    to_tsvector('simple', coalesce(title,'') || ' ' ||
                           coalesce(artist,'') || ' ' ||
                           coalesce(album,''))
);

-- 재생이력
CREATE TABLE IF NOT EXISTS play_history (
    id         BIGSERIAL PRIMARY KEY,
    track_id   BIGINT REFERENCES tracks(track_id),
    played_at  TIMESTAMPTZ DEFAULT now(),
    client_ip  INET
);
ALTER TABLE play_history ADD COLUMN IF NOT EXISTS weather VARCHAR(32);
ALTER TABLE play_history ADD COLUMN IF NOT EXISTS period VARCHAR(32);
ALTER TABLE play_history ADD COLUMN IF NOT EXISTS mood VARCHAR(64);
ALTER TABLE play_history ADD COLUMN IF NOT EXISTS location_label VARCHAR(128);

-- 즐겨찾기
CREATE TABLE IF NOT EXISTS favorites (
    id         BIGSERIAL PRIMARY KEY,
    track_id   BIGINT REFERENCES tracks(track_id),
    added_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(track_id)
);

-- DSP · 룸보정 (CamillaDSP yaml)
CREATE TABLE IF NOT EXISTS dsp_profiles (
    profile_key   VARCHAR(64) PRIMARY KEY,
    preset_slug   VARCHAR(32),
    dsp_profile   JSONB NOT NULL,
    camilla_yaml  TEXT NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS playlists (
    playlist_id BIGSERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id BIGINT REFERENCES playlists(playlist_id) ON DELETE CASCADE,
    track_id    BIGINT REFERENCES tracks(track_id) ON DELETE CASCADE,
    position    INT NOT NULL DEFAULT 0,
    added_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (playlist_id, track_id)
);

-- 게스트 추천곡 공유 (24h 토큰 · 허용 track_id만 스트리밍)
CREATE TABLE IF NOT EXISTS guest_shares (
    token_hash   TEXT PRIMARY KEY,
    title        VARCHAR(200),
    track_ids    BIGINT[] NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    play_count   INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_guest_shares_expires ON guest_shares(expires_at);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS quality VARCHAR(20);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS quality_reasons TEXT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS composer VARCHAR(300);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS storage_source VARCHAR(20) DEFAULT 'internal';
-- internal = music 내장, external = /media·외장 경로 등록
