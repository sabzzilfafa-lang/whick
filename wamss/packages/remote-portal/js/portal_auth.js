(function () {
  const cfg = window.WHICK_REMOTE_PORTAL;

  function t(key) {
    if (window.WhickPortalI18n && typeof window.WhickPortalI18n.t === 'function') {
      return window.WhickPortalI18n.t(key);
    }
    return key;
  }

  const AUTH_CLEAR_CODES = new Set([
    'REMOTE_AUTH_REQUIRED',
    'REMOTE_AUTH_INVALID',
    'REMOTE_AUTH_EXPIRED',
  ]);

  function getToken() {
    return localStorage.getItem(cfg.tokenKey) || '';
  }

  function setSession(token, user) {
    localStorage.setItem(cfg.tokenKey, token);
    localStorage.setItem(cfg.userKey, JSON.stringify(user || {}));
  }

  function clearSession() {
    localStorage.removeItem(cfg.tokenKey);
    localStorage.removeItem(cfg.userKey);
    localStorage.removeItem(cfg.deviceKey);
    localStorage.removeItem(cfg.devicesCacheKey);
  }

  function getUser() {
    try {
      return JSON.parse(localStorage.getItem(cfg.userKey) || '{}');
    } catch {
      return {};
    }
  }

  function cacheDevices(devices) {
    try {
      localStorage.setItem(
        cfg.devicesCacheKey,
        JSON.stringify({ savedAt: Date.now(), devices: devices || [] }),
      );
    } catch {
      /* quota */
    }
  }

  function getCachedDevices() {
    try {
      const row = JSON.parse(localStorage.getItem(cfg.devicesCacheKey) || '{}');
      return Array.isArray(row.devices) ? row.devices : [];
    } catch {
      return [];
    }
  }

  function shouldClearSession(err) {
    return err && err.status === 401 && AUTH_CLEAR_CODES.has(err.code);
  }

  function isNetworkError(err) {
    if (!err) return false;
    if (err.code === 'NETWORK_ERROR') return true;
    if (err.name === 'TypeError') return true;
    return !err.status;
  }

  async function api(path, options = {}) {
    const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    const token = getToken();
    if (token) headers.Authorization = 'Bearer ' + token;

    let res;
    try {
      res = await fetch(cfg.apiBase + path, Object.assign({}, options, { headers }));
    } catch (cause) {
      const err = new Error(t('error.network'));
      err.code = 'NETWORK_ERROR';
      err.cause = cause;
      throw err;
    }

    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.ok === false) {
      const err = new Error(body.error?.message || body.message || t('error.request'));
      err.code = body.error?.code || body.code || 'API_ERROR';
      err.status = res.status;
      throw err;
    }
    return body.data != null ? body.data : body;
  }

  async function bootstrap() {
    return api('/session/bootstrap');
  }

  async function reinstallConsent(agreed) {
    return api('/session/reinstall-consent', {
      method: 'POST',
      body: JSON.stringify({ agreed }),
    });
  }

  async function opsReinstallConsentStatus(deviceId) {
    return api('/devices/' + encodeURIComponent(String(deviceId)) + '/ops-reinstall-consent');
  }

  async function opsReinstallConsentRespond(deviceId, agreed) {
    return api('/devices/' + encodeURIComponent(String(deviceId)) + '/ops-reinstall-consent', {
      method: 'POST',
      body: JSON.stringify({ agreed }),
    });
  }

  async function login(login, password) {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login, password }),
    });
    setSession(data.token, data.user);
    return data;
  }

  async function me() {
    return api('/auth/me');
  }

  async function listDevices() {
    const data = await api('/devices');
    const devices = data.devices || [];
    cacheDevices(devices);
    return devices;
  }

  async function renameDevice(deviceId, displayName) {
    return api('/devices/' + encodeURIComponent(String(deviceId)), {
      method: 'PATCH',
      body: JSON.stringify({ display_name: displayName }),
    });
  }

  /** 토큰 있으면 네트워크 오류 시에도 세션 유지 */
  async function verifySession() {
    const token = getToken();
    if (!token) {
      return { ok: false, reason: 'no_token' };
    }

    try {
      const user = await me();
      setSession(token, user);
      return { ok: true, user, online: true };
    } catch (err) {
      if (shouldClearSession(err)) {
        return { ok: false, reason: 'auth', error: err };
      }
      return {
        ok: true,
        user: getUser(),
        online: false,
        offline: isNetworkError(err),
        error: err,
      };
    }
  }

  window.WhickRemoteAuth = {
    getToken,
    getUser,
    setSession,
    clearSession,
    cacheDevices,
    getCachedDevices,
    shouldClearSession,
    isNetworkError,
    api,
    login,
    bootstrap,
    reinstallConsent,
    opsReinstallConsentStatus,
    opsReinstallConsentRespond,
    me,
    listDevices,
    renameDevice,
    verifySession,
  };
})();
