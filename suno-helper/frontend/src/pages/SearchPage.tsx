import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, SearchResult } from "../api";

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") || "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const q = params.get("q");
    if (q) {
      setQuery(q);
      setLoading(true);
      api.search(q).then(setResults).finally(() => setLoading(false));
    }
  }, [params]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setParams({ q: query });
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>검색</h2>
          <p>앨범, 곡, 가사, 태그를 검색하세요</p>
        </div>
      </div>

      <form onSubmit={handleSearch} style={{ marginBottom: "2rem", display: "flex", gap: "0.5rem" }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="검색어 입력..."
          style={{ flex: 1 }}
        />
        <button type="submit" className="btn btn-primary">검색</button>
      </form>

      {loading ? (
        <div className="loading">검색 중...</div>
      ) : results.length === 0 ? (
        <div className="empty-state">
          <p>{params.get("q") ? "결과가 없습니다" : "검색어를 입력하세요"}</p>
        </div>
      ) : (
        <ul className="track-list card" style={{ padding: 0 }}>
          {results.map((r) => (
            <li key={`${r.type}-${r.id}`} className="track-item">
              <span className="badge" style={{ minWidth: "50px", textAlign: "center" }}>
                {r.type === "album" ? "앨범" : "곡"}
              </span>
              <Link
                to={r.type === "album" ? `/albums/${r.id}` : `/songs/${r.id}`}
                style={{ flex: 1, color: "inherit" }}
              >
                <div className="track-info">
                  <h4>{r.title}</h4>
                  {r.subtitle && <p>{r.subtitle}</p>}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
