/**
 * 판매 리모컨 — CC 상태 감시
 * 설치 전환·5분 오프라인 판정은 CC session/bootstrap을 SSOT로 사용한다.
 */
(function () {
  const POLL_MS = 5000;
  const TOKEN_KEY = 'whick_remote_token';
  let timer = null;
  let busy = false;
  let redirecting = false;

  function isGuestView() {
    const qs = new URLSearchParams(location.search);
    return Boolean(qs.get('sl') || qs.get('gt'));
  }

  function currentDeviceId() {
    const qs = new URLSearchParams(location.search);
    return String(qs.get('device') || localStorage.getItem('whick_remote_device_id') || '');
  }

  function goPortal(hash) {
    if (redirecting) return;
    redirecting = true;
    window.location.replace('/' + hash);
  }

  async function checkCcState(force = false) {
    if (busy || redirecting || isGuestView()) return;
    if (!force && document.visibilityState === 'hidden') return;
    const token = localStorage.getItem(TOKEN_KEY) || '';
    if (!token) return;

    busy = true;
    try {
      const res = await fetch('/api/v1/remote/session/bootstrap', {
        headers: { Authorization: 'Bearer ' + token },
        cache: 'no-store',
      });
      if (res.status === 401) {
        goPortal('#/login');
        return;
      }
      if (!res.ok) return;
      const body = await res.json();
      const state = body?.data || body;

      if (state?.mode === 'install') {
        goPortal('#/install');
        return;
      }
      if (state?.mode !== 'remote') return;

      const deviceId = currentDeviceId();
      if (!deviceId) return;
      const devices = Array.isArray(state.devices) ? state.devices : [];
      const current = devices.find((d) => String(d.device_id) === deviceId);
      // 계정에서 장비가 빠진 경우만 서버 선택으로. 오프라인은 리모컨 화면에 남긴다
      // (예전: agent_online===false 도 튕겨서 선택→진입→즉시 복귀 루프가 났음).
      if (!current) {
        goPortal('#/devices');
      }
    } catch {
      // 휴대폰 자체 네트워크 오류는 현재 리모컨 화면을 유지하고 다음 poll에서 재확인한다.
    } finally {
      busy = false;
    }
  }

  function schedule() {
    if (timer) clearInterval(timer);
    timer = setInterval(() => checkCcState(false), POLL_MS);
  }

  window.addEventListener('online', () => checkCcState(true));
  window.addEventListener('pageshow', () => checkCcState(true));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkCcState(true);
  });

  checkCcState(true);
  schedule();
})();
