import { useTranslation } from "react-i18next";

/** 웹 실행 흐름 외 로컬 직접 접속 차단 화면. */
export default function WebLaunchGate() {
  const { t } = useTranslation();
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        className="card"
        style={{
          maxWidth: 520,
          width: "100%",
          textAlign: "center",
          padding: "32px 28px",
        }}
      >
        <div style={{ fontSize: 42, marginBottom: 10 }}>🔐</div>
        <h1 style={{ fontSize: "1.15rem", margin: "0 0 10px" }}>
          {t("gate.title", "Suno Helper는 웹에서 실행하세요")}
        </h1>
        <p
          style={{
            color: "var(--tx2, #9aa4b2)",
            fontSize: ".9rem",
            lineHeight: 1.7,
            margin: "0 0 18px",
          }}
        >
          {t(
            "gate.desc",
            "직접 접속은 지원되지 않습니다. 아래 버튼으로 웹 대시보드에서 실행해 주세요."
          )}
        </p>
        <a
          className="btn btn-primary"
          href="https://whick.org/suno.html"
          style={{ textDecoration: "none", padding: "10px 22px" }}
        >
          {t("gate.go", "whick.org에서 열기")}
        </a>
      </div>
    </div>
  );
}
