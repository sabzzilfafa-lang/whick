import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Album, api } from "../api";
import ActiveStyleBar from "../components/ActiveStyleBar";
import { useLang } from "../lib/i18n";

export default function HomePage() {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [loading, setLoading] = useState(true);
  const { lang, t } = useLang();

  useEffect(() => {
    api.listAlbums().then(setAlbums).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{t("환영합니다")}</h2>
          <p>{t("일관된 음악 스타일로 수노 가사와 프롬프트를 만들어보세요")}</p>
        </div>
        <Link to="/albums">
          <button className="btn btn-primary">{t("새 앨범 만들기")}</button>
        </Link>
      </div>

      <ActiveStyleBar />

      <div className="card" style={{ marginBottom: "2rem" }}>
        <div className="card-title">{t("빠른 시작")}</div>
        {lang === "ko" ? (
          <ol style={{ paddingLeft: "1.2rem", color: "var(--text-secondary)", fontSize: "0.9rem" }}>
            <li style={{ marginBottom: "0.5rem" }}>
              <Link to="/settings">사용자 설정</Link>에서 OpenRouter API 키를 입력하세요
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              <Link to="/profiles">스타일 프리셋</Link>에서 오늘의 음악 성향을 선택하세요
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              <Link to="/analyze">취향 곡 분석</Link>으로 좋아하는 곡에서 프롬프트를 추출하세요
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              <Link to="/albums">앨범</Link>을 만들고 컨셉과 곡 수를 설정하세요
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              AI로 가사, Suno 프롬프트, 악기 세팅을 생성하세요
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              Suno에서 받은 음원을 <Link to="/studio">유튜브 스튜디오</Link>에 넣고 리마스터·영상을 만드세요
            </li>
            <li>기존 곡을 참조해 같은 분위기의 새 곡을 만들 수 있습니다</li>
          </ol>
        ) : (
          <ol style={{ paddingLeft: "1.2rem", color: "var(--text-secondary)", fontSize: "0.9rem" }}>
            <li style={{ marginBottom: "0.5rem" }}>
              {t("사용자 설정")} (<Link to="/settings">OpenRouter</Link>)
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              {t("스타일 프리셋")} (<Link to="/profiles">)</Link>
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              {t("취향 곡 분석")} (<Link to="/analyze">)</Link>
            </li>
            <li style={{ marginBottom: "0.5rem" }}>
              {t("앨범")} (<Link to="/albums">)</Link>
            </li>
            <li style={{ marginBottom: "0.5rem" }}>AI — lyrics · Suno prompt · instruments</li>
            <li style={{ marginBottom: "0.5rem" }}>
              Suno → <Link to="/studio">{t("유튜브 스튜디오")}</Link> (remaster · video)
            </li>
            <li>{t("앨범")} — reference tracks → new songs</li>
          </ol>
        )}
      </div>

      <div className="card-title">{t("최근 앨범")}</div>
      {loading ? (
        <div className="loading">{t("불러오는 중...")}</div>
      ) : albums.length === 0 ? (
        <div className="empty-state">
          <h3>{t("아직 앨범이 없습니다")}</h3>
          <p>{t("첫 번째 앨범을 만들어 음악 제작을 시작하세요")}</p>
        </div>
      ) : (
        <div className="album-grid">
          {albums.slice(0, 6).map((album) => (
            <Link key={album.id} to={`/albums/${album.id}`}>
              <div className="album-card">
                <h3>{album.title}</h3>
                {album.mood && <span className="badge">{album.mood}</span>}
                <p className="meta" style={{ marginTop: "0.5rem" }}>
                  {album.track_count}
                  {t("곡")}
                  {album.target_duration_min && ` · ${album.target_duration_min} min`}
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
