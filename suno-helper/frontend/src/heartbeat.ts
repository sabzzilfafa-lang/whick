/**
 * 브라우저 닫힘 감지 하트비트.
 * 15초 간격으로 백엔드에 신호를 보내고, 탭이 닫히면 신호가 멈춰
 * 백엔드(90초 타임아웃)가 스스로 종료한다.
 * 백엔드가 없으면(개발 중 vite만 띄운 경우 등) 조용히 포기한다.
 */
const INTERVAL_MS = 15_000;

export function startHeartbeat(): void {
  let alive = true;
  let failures = 0;

  const ping = () => {
    if (!alive) return;
    fetch("/api/heartbeat", { method: "POST", keepalive: true }).catch(() => {
      failures += 1;
      if (failures > 3) alive = false; // 서버 없음 — 반복 시도 중단
    });
    failures = Math.max(0, failures - 1) as number;
  };

  ping();
  const timer = window.setInterval(ping, INTERVAL_MS);

  // 탭 닫힘/새로고침 시 즉시 알림 — 백엔드 그레이스타임과 무관하게 빠르게 마지막 신호 갱신
  window.addEventListener("beforeunload", () => {
    navigator.sendBeacon?.("/api/heartbeat");
    window.clearInterval(timer);
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") ping();
  });
}
