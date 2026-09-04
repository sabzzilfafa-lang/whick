(function () {
  const cfg = window.WHICK_REMOTE_PORTAL;

  function t(key) {
    if (window.WhickPortalI18n && typeof window.WhickPortalI18n.t === 'function') {
      return window.WhickPortalI18n.t(key);
    }
    return key;
  }

  function endpointsKey(deviceId) {
    return cfg.deviceEndpointsPrefix + String(deviceId);
  }

  function normalizeHost(host) {
    return String(host || '')
      .trim()
      .replace(/^https?:\/\//, '')
      .replace(/\/.*$/, '')
      .replace(/:\d+$/, '');
  }

  function isPrivateHost(host) {
    const h = normalizeHost(host);
    return (
      /^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h) ||
      h === 'localhost' ||
      h === '127.0.0.1'
    );
  }

  /** CC 장비 목록 → 연결 프로필 저장 (Wi-Fi↔데이터 전환 시 재사용) */
  function saveDeviceProfile(device) {
    if (!device?.device_id) return;
    const lan = normalizeHost(device.lan_ip);
    const tunnel = normalizeHost(device.tunnel_host);
    const profile = {
      device_id: device.device_id,
      member_no: device.member_no || '',
      hostname: device.hostname || '',
      lan: lan || null,
      tunnel: tunnel || null,
      player_token: device.player_token || null,
      savedAt: Date.now(),
    };
    try {
      localStorage.setItem(endpointsKey(device.device_id), JSON.stringify(profile));
    } catch {
      /* quota */
    }
    return profile;
  }

  function getDeviceProfile(deviceId) {
    try {
      const row = JSON.parse(localStorage.getItem(endpointsKey(deviceId)) || '{}');
      if (String(row.device_id) !== String(deviceId)) return null;
      return row;
    } catch {
      return null;
    }
  }

  function mergeDeviceProfile(device) {
    const saved = getDeviceProfile(device.device_id) || {};
    return saveDeviceProfile({
      ...device,
      lan_ip: device.lan_ip || saved.lan,
      tunnel_host: device.tunnel_host || saved.tunnel,
      player_token: device.player_token || saved.player_token || null,
    });
  }

  function describeEndpoints(profile) {
    if (!profile) return t('link.no_info');
    const parts = [];
    if (profile.lan) parts.push(t('link.mode_lan') + ' ' + profile.lan);
    if (profile.tunnel) parts.push(t('link.mode_ext') + ' ' + profile.tunnel);
    return parts.length ? parts.join(' · ') : t('link.addr_pending');
  }

  /** v4 WhickAPI에 넘길 { lan, tunnel } */
  function toWhickEndpoints(profile) {
    if (!profile) return null;
    return {
      lan: profile.lan || null,
      tunnel: profile.tunnel || null,
      deviceId: profile.device_id,
    };
  }

  let musicApi = null;
  let onLinkChange = null;

  function attachMusicApi(api) {
    musicApi = api;
  }

  function reconnectMusicApi() {
    if (musicApi && typeof musicApi.reconnect === 'function') {
      musicApi.reconnect();
    }
  }

  function setLinkChangeHandler(fn) {
    onLinkChange = fn;
  }

  function notifyLinkChange(info) {
    if (typeof onLinkChange === 'function') onLinkChange(info);
  }

  function handleNetworkRestore(refreshDevicesFn) {
    if (!window.WhickRemoteAuth?.getToken()) return;
    if (typeof refreshDevicesFn === 'function') {
      refreshDevicesFn({ silent: true, updateProfiles: true });
    }
    reconnectMusicApi();
  }

  window.WhickDeviceLink = {
    normalizeHost,
    isPrivateHost,
    saveDeviceProfile,
    getDeviceProfile,
    mergeDeviceProfile,
    describeEndpoints,
    toWhickEndpoints,
    attachMusicApi,
    reconnectMusicApi,
    setLinkChangeHandler,
    notifyLinkChange,
    handleNetworkRestore,
  };
})();
