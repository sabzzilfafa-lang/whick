(function () {
  const auth = window.WhickRemoteAuth;
  const link = window.WhickDeviceLink;
  const cfg = window.WHICK_REMOTE_PORTAL;

  const el = {
    loading: document.getElementById('view-loading'),
    login: document.getElementById('view-login'),
    install: document.getElementById('view-install'),
    devices: document.getElementById('view-devices'),
    remote: document.getElementById('view-remote'),
    loginForm: document.getElementById('login-form'),
    loginErr: document.getElementById('login-error'),
    loginBtn: document.getElementById('login-btn'),
    installUserLabel: document.getElementById('install-user-label'),
    installLogoutBtn: document.getElementById('install-logout-btn'),
    installStage: document.getElementById('install-stage'),
    installProgressBar: document.getElementById('install-progress-bar'),
    installMsg: document.getElementById('install-msg'),
    installWaitHint: document.getElementById('install-wait-hint'),
    installConsent: document.getElementById('install-consent'),
    installHint: document.getElementById('install-hint'),
    deviceList: document.getElementById('device-list'),
    deviceEmpty: document.getElementById('device-empty'),
    deviceNotice: document.getElementById('device-notice'),
    userLabel: document.getElementById('user-label'),
    logoutBtn: document.getElementById('logout-btn'),
    backDevices: document.getElementById('back-devices'),
    remoteTitle: document.getElementById('remote-title'),
    remoteLinkStatus: document.getElementById('remote-link-status'),
    remotePlaceholder: document.getElementById('remote-placeholder'),
  };

  let currentDevice = null;
  let bootDone = false;
  let musicProbeToken = 0;
  let installPollTimer = null;
  let portalStatePollTimer = null;
  let portalStatePollBusy = false;
  let installSmoothTimer = null;
  let installDisplayPct = 0;
  let installTargetPct = 0;
  let installDisplayPhase = '';
  let lastInstall = null;

  function t(key, vars) {
    if (window.WhickPortalI18n && typeof window.WhickPortalI18n.t === 'function') {
      const v = window.WhickPortalI18n.t(key, vars);
      if (typeof v === 'string') return v;
    }
    return key;
  }

  function stopInstallPoll() {
    if (installPollTimer) {
      clearInterval(installPollTimer);
      installPollTimer = null;
    }
    if (installSmoothTimer) {
      clearInterval(installSmoothTimer);
      installSmoothTimer = null;
    }
  }

  function ensureInstallSmoothTicker() {
    if (installSmoothTimer) return;
    installSmoothTimer = setInterval(() => {
      if (installDisplayPct < installTargetPct) {
        installDisplayPct += 1;
        if (el.installProgressBar) el.installProgressBar.style.width = installDisplayPct + '%';
        if (el.installStage && installDisplayPhase) {
          el.installStage.textContent = installDisplayPhase + ' · ' + installDisplayPct + '%';
        }
      }
    }, 2000);
  }

  let installAlertPermissionPending = false;

  function maybeInstallPhoneAlert(st) {
    const title = st.phone_alert_title;
    const body = st.phone_alert_body;
    const alertId = Number(st.phone_alert_id || st.session_id || 0);
    if (!title || !alertId) return;
    const key =
      'whick-install-alert-' +
      alertId +
      '-' +
      String(st.phone_alert_title || st.portal_stage || st.phase || 'alert')
        .replace(/\s+/g, '_')
        .slice(0, 48);
    if (sessionStorage.getItem(key)) return;
    if (!('Notification' in window)) return;
    const markShown = () => sessionStorage.setItem(key, '1');
    const fire = () => {
      try {
        new Notification(title, { body: body || '', tag: key });
        markShown();
      } catch {
        /* ignore */
      }
    };
    if (Notification.permission === 'granted') fire();
    else if (Notification.permission === 'default') {
      if (installAlertPermissionPending) return;
      installAlertPermissionPending = true;
      Notification.requestPermission()
        .then((p) => {
          if (p === 'granted') fire();
        })
        .finally(() => {
          installAlertPermissionPending = false;
        });
    }
  }

  function startInstallPoll() {
    stopInstallPoll();
    installPollTimer = setInterval(() => {
      if (el.install?.classList.contains('hidden')) {
        stopInstallPoll();
        return;
      }
      refreshBootstrap({ silent: true }).catch(() => {});
    }, 2500);
  }

  function stopPortalStatePoll() {
    if (portalStatePollTimer) {
      clearInterval(portalStatePollTimer);
      portalStatePollTimer = null;
    }
    portalStatePollBusy = false;
  }

  async function refreshPortalState() {
    if (portalStatePollBusy || !auth.getToken()) return;
    portalStatePollBusy = true;
    try {
      const data = await auth.bootstrap();
      if (data?.mode === 'install') {
        stopPortalStatePoll();
        await enterAfterAuth(data, { fromLogin: false, silent: true });
        return;
      }
      if (data?.mode !== 'remote' || el.devices?.classList.contains('hidden')) return;

      const devices = mergeAndCacheDevices(data.devices || []);
      auth.cacheDevices(devices);
      renderDevices(devices);
      const allOffline = devices.length > 0 && devices.every((d) => d.agent_online === false);
      setNotice(
        allOffline
          ? t('notice.offline_all')
          : null,
        allOffline ? 'offline' : 'info',
      );
    } catch {
      // 중앙관제 일시 오류는 로그인·현재 화면을 유지하고 다음 poll에서 재확인한다.
    } finally {
      portalStatePollBusy = false;
    }
  }

  function startPortalStatePoll() {
    if (portalStatePollTimer) return;
    portalStatePollTimer = setInterval(refreshPortalState, 5000);
  }

  function renderInstallView(install) {
    lastInstall = install || null;
    const st = install || {};
    const stepPct = Math.max(
      0,
      Math.min(
        100,
        Number(st.phase_progress_pct != null ? st.phase_progress_pct : st.progress_pct) || 0,
      ),
    );
    const stepLabel =
      st.track_label ||
      st.portal_stage_label ||
      st.phase_label ||
      st.portal_state ||
      t('install.preparing');
    const phaseKey = String(st.phase || st.portal_stage || '');
    if (phaseKey !== installDisplayPhase) {
      installDisplayPhase = stepLabel;
      installDisplayPct = 0;
      installTargetPct = 0;
    }
    if (stepPct > installTargetPct) installTargetPct = stepPct;
    if (stepPct >= installDisplayPct && installDisplayPct === 0 && stepPct > 0) {
      installDisplayPct = Math.max(0, stepPct - 1);
    }
    ensureInstallSmoothTicker();
    if (el.installStage) {
      el.installStage.textContent = stepLabel + ' · ' + installDisplayPct + '%';
    }
    if (el.installProgressBar) el.installProgressBar.style.width = installDisplayPct + '%';
    if (el.installMsg) el.installMsg.textContent = st.progress_msg || t('install.waiting');

    // Linux rootfs 다운로드·배포(대략 55%대) 등은 진행이 안 보이는 것처럼 수 분~10분+ 걸릴 수 있음
    const phaseLc = String(st.phase || '').toLowerCase();
    const msgLc = String(st.progress_msg || '').toLowerCase();
    const stageLc = String(st.portal_stage || st.track_label || st.phase_label || '').toLowerCase();
    const longWaitLinux =
      phaseLc === 'install_linux' ||
      /ubuntu|rootfs|배포|download|linux 설치|파티션|grub|부트로더|ssd package/.test(
        msgLc + ' ' + stageLc,
      );
    if (el.installWaitHint) {
      if (longWaitLinux) {
        el.installWaitHint.classList.remove('hidden');
        el.installWaitHint.textContent = t('install.long_wait');
      } else {
        el.installWaitHint.classList.add('hidden');
        el.installWaitHint.textContent = '';
      }
    }
    if (el.installHint) {
      el.installHint.textContent = longWaitLinux
        ? t('install.long_hint')
        : t('install.auto_hint');
    }

    maybeInstallPhoneAlert(st);

    const showConsent =
      st.portal_stage === 'reinstall_consent' ||
      st.phase === 'reinstall_consent_pending' ||
      (st.reinstall_consent && st.reinstall_consent.required && st.reinstall_consent.status === 'pending');
    if (el.installConsent) {
      if (!showConsent) {
        el.installConsent.classList.add('hidden');
        el.installConsent.innerHTML = '';
      } else {
        el.installConsent.classList.remove('hidden');
        el.installConsent.innerHTML =
          '<p class="install-consent-msg">' + t('install.consent_msg') + '</p>' +
          '<div class="install-consent-actions">' +
          '<button type="button" class="btn" id="install-consent-yes">' + t('common.agree') + '</button>' +
          '<button type="button" class="btn btn-ghost" id="install-consent-no">' + t('common.reject') + '</button>' +
          '</div>';
        document.getElementById('install-consent-yes')?.addEventListener('click', () =>
          submitReinstallConsent(true),
        );
        document.getElementById('install-consent-no')?.addEventListener('click', () =>
          submitReinstallConsent(false),
        );
      }
    }
  }

  async function submitReinstallConsent(agreed) {
    try {
      const out = await auth.reinstallConsent(agreed);
      if (out?.bootstrap) await enterAfterAuth(out.bootstrap, { fromLogin: false });
      else await refreshBootstrap({ silent: false });
    } catch (e) {
      if (el.installMsg) el.installMsg.textContent = e.message || t('install.consent_fail');
    }
  }

  function showInstallShell() {
    updateUserLabels();
    show(el.install);
  }

  async function refreshBootstrap({ silent = false } = {}) {
    const data = await auth.bootstrap();
    await enterAfterAuth(data, { fromLogin: false, silent });
    return data;
  }

  async function enterAfterAuth(data, { fromLogin = true, silent = false } = {}) {
    const mode = data?.mode || 'none';
    if (mode === 'install') {
      stopPortalStatePoll();
      stopInstallPoll();
      showInstallShell();
      renderInstallView(data.install);
      startInstallPoll();
      history.replaceState({ view: 'install' }, '', '#/install');
      return;
    }

    stopInstallPoll();
    if (mode === 'remote') {
      if (data.devices?.length) auth.cacheDevices(data.devices);
    }

    showDevicesShell();
    replaceRoute('devices');
    if (mode === 'remote' && data.devices?.length) {
      renderDevices(mergeAndCacheDevices(data.devices));
      return;
    }
    await refreshDevices({ silent: silent || !fromLogin });
  }

  function parseHandoff() {
    const hash = location.hash || '';
    const m = hash.match(/^#handoff=([^&]+)/);
    if (!m) return null;
    try {
      const raw = decodeURIComponent(m[1]);
      const json = decodeURIComponent(escape(atob(raw)));
      return JSON.parse(json);
    } catch {
      try {
        return JSON.parse(atob(decodeURIComponent(m[1])));
      } catch {
        return null;
      }
    }
  }

  function applyHandoff(handoff) {
    if (!handoff) return false;
    history.replaceState(null, '', location.pathname + location.search);
    if (handoff.token) auth.setSession(handoff.token, handoff.user || {});
    if (handoff.connect) {
      try {
        localStorage.setItem('whick_remote_connect_mode', String(handoff.connect));
      } catch {
        /* ignore */
      }
    }
    const prof = handoff.profile || {};
    const deviceId = handoff.device_id || prof.device_id;
    if (!deviceId) return false;
    const device = {
      device_id: deviceId,
      hostname: prof.hostname || 'Whick Music Server',
      member_no: prof.member_no || '',
      lan_ip: prof.lan || null,
      tunnel_host: prof.tunnel || null,
      player_token: prof.player_token || null,
    };
    link.mergeDeviceProfile(device);
    try {
      const embed = {
        device_id: deviceId,
        lan: prof.lan || null,
        tunnel: prof.tunnel || null,
        member_no: prof.member_no || '',
        hostname: prof.hostname || '',
        player_token: prof.player_token || null,
      };
      sessionStorage.setItem('whick_remote_embed_profile', JSON.stringify(embed));
      localStorage.setItem('whick_remote_active_profile', JSON.stringify(embed));
      localStorage.setItem(cfg.deviceKey, String(deviceId));
    } catch {
      /* ignore */
    }
    bootDone = true;
    showDevicesShell();
    openRemote(device, { pushHistory: false });
    return true;
  }

  function show(view) {
    [el.loading, el.login, el.install, el.devices, el.remote].forEach((node) => {
      if (node) node.classList.add('hidden');
    });
    if (view) view.classList.remove('hidden');
  }

  function setRemoteLinkStatus(text, kind) {
    if (!el.remoteLinkStatus) return;
    if (!text) {
      el.remoteLinkStatus.classList.add('hidden');
      el.remoteLinkStatus.textContent = '';
      return;
    }
    el.remoteLinkStatus.textContent = text;
    el.remoteLinkStatus.classList.remove('hidden', 'notice-offline', 'notice-info');
    el.remoteLinkStatus.classList.add(kind === 'offline' ? 'notice-offline' : 'notice-info');
  }

  function getConnectModePref() {
    try {
      const v = localStorage.getItem('whick_remote_connect_mode') || 'auto';
      return v === 'cc' ? 'tunnel' : v;
    } catch {
      return 'auto';
    }
  }

  async function probeMusicServer(profile) {
    const mode = getConnectModePref();
    const candidates = [];
    // 'tunnel' 모드면 LAN 스킵, 'lan' 모드면 tunnel 스킵, 'auto'면 둘 다.
    if (profile?.lan && mode !== 'tunnel') {
      candidates.push({ mode: 'lan', url: 'http://' + profile.lan + ':8080/health', timeout: 2500 });
    }
    if (profile?.tunnel && mode !== 'lan') {
      candidates.push({ mode: 'tunnel', url: 'https://' + profile.tunnel + '/health', timeout: 4000 });
    }
    if (!candidates.length) return { ok: false };

    // 병렬 probe — 먼저 정상 응답한 경로를 채택한다.
    // (순차 시 외부망에서 LAN 타임아웃까지 "연결 확인 중"이 빙빙 도는 문제 방지)
    return new Promise((resolve) => {
      let pending = candidates.length;
      let settled = false;
      const finish = (val) => {
        if (!settled) {
          settled = true;
          resolve(val);
        }
      };
      candidates.forEach((c) => {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), c.timeout);
        fetch(c.url, { signal: ctrl.signal, cache: 'no-store' })
          .then((res) => {
            clearTimeout(timer);
            if (res.ok) finish({ ok: true, mode: c.mode });
            else if (--pending === 0) finish({ ok: false });
          })
          .catch(() => {
            clearTimeout(timer);
            if (--pending === 0) finish({ ok: false });
          });
      });
    });
  }

  async function refreshMusicLink(profile) {
    const token = ++musicProbeToken;
    if (!profile || (!profile.lan && !profile.tunnel)) {
      setRemoteLinkStatus(t('link.addr_wait'), 'offline');
      return;
    }

    setRemoteLinkStatus(t('link.checking'), 'info');
    const result = await probeMusicServer(profile);
    if (token !== musicProbeToken) return;

    if (result.ok) {
      const label = result.mode === 'lan' ? t('link.mode_lan') : t('link.mode_ext');
      setRemoteLinkStatus(t('link.connected') + label, 'info');
      link.notifyLinkChange({ ok: true, mode: result.mode, profile });
      link.reconnectMusicApi();
      return;
    }

    setRemoteLinkStatus(
      t('link.unreachable'),
      'offline',
    );
    link.notifyLinkChange({ ok: false, profile });
  }

  function mergeAndCacheDevices(devices) {
    return (devices || []).map((d) => {
      const merged = link.mergeDeviceProfile(d);
      return Object.assign({}, d, {
        lan_ip: merged.lan,
        tunnel_host: merged.tunnel,
      });
    });
  }

  function setNotice(text, kind) {
    if (!el.deviceNotice) return;
    if (!text) {
      el.deviceNotice.classList.add('hidden');
      el.deviceNotice.textContent = '';
      el.deviceNotice.classList.remove('notice-offline', 'notice-info');
      return;
    }
    el.deviceNotice.textContent = text;
    el.deviceNotice.classList.remove('hidden', 'notice-offline', 'notice-info');
    el.deviceNotice.classList.add(kind === 'offline' ? 'notice-offline' : 'notice-info');
  }

  function pushRoute(view, device) {
    const state = {
      view,
      deviceId: device ? device.device_id : null,
    };
    const hash =
      view === 'remote' && device
        ? '#/remote/' + device.device_id
        : view === 'devices'
          ? '#/devices'
          : '#/login';
    history.pushState(state, '', hash || '/');
  }

  function replaceRoute(view, device) {
    const state = {
      view,
      deviceId: device ? device.device_id : null,
    };
    const hash =
      view === 'remote' && device
        ? '#/remote/' + device.device_id
        : view === 'devices'
          ? '#/devices'
          : '/';
    history.replaceState(state, '', hash === '/' ? '/' : hash);
  }

  function findDeviceById(id) {
    const list = auth.getCachedDevices();
    return list.find((d) => String(d.device_id) === String(id)) || null;
  }

  async function redirectToInstallIfActive({ silent = false } = {}) {
    if (!auth.getToken()) return false;
    try {
      const data = await auth.bootstrap();
      if (data?.mode === 'install') {
        await enterAfterAuth(data, { fromLogin: false, silent });
        return true;
      }
    } catch {
      /* devices fallback */
    }
    return false;
  }

  function applyRoute(state) {
    if (!state || state.view === 'login') {
      if (!auth.getToken()) {
        show(el.login);
        replaceRoute('login');
        return;
      }
      state = { view: 'devices' };
    }

    if (state.view === 'install' && auth.getToken()) {
      showInstallShell();
      refreshBootstrap({ silent: true }).catch(() => {});
      return;
    }

    if (state.view === 'remote') {
      const device =
        currentDevice && String(currentDevice.device_id) === String(state.deviceId)
          ? currentDevice
          : findDeviceById(state.deviceId);
      if (device && auth.getToken()) {
        openRemote(device, { pushHistory: false });
        return;
      }
      state = { view: 'devices' };
    }

    if (state.view === 'devices' && auth.getToken()) {
      redirectToInstallIfActive({ silent: true }).then((switched) => {
        if (switched) return;
        currentDevice = null;
        showDevicesShell();
        replaceRoute('devices');
        refreshDevices({ silent: true });
      });
      return;
    }
  }

  function formatSeen(iso) {
    if (!iso) return t('devices.no_history');
    try {
      const lang = (window.WhickPortalI18n && window.WhickPortalI18n.getLang) ? window.WhickPortalI18n.getLang() : 'ko';
      const d = new Date(iso);
      return d.toLocaleString(lang === 'en' ? 'en-US' : 'ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return iso;
    }
  }

  function healthBadge(status) {
    if (status === 'normal') return '';
    return '<span class="badge badge-offline">' + (status === 'offline' ? t('devices.offline_badge') : status) + '</span>';
  }

  function deviceLabel(d) {
    return String(d?.name || d?.display_name || d?.hostname || t('devices.default_name')).trim();
  }

  function renderDevices(devices) {
    el.deviceList.innerHTML = '';
    if (!devices.length) {
      el.deviceEmpty.classList.remove('hidden');
      return;
    }
    el.deviceEmpty.classList.add('hidden');

    devices.forEach((d) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'device-item';
      btn.dataset.deviceId = String(d.device_id);
      const roleClass = d.role === 'remote' ? 'badge-remote' : 'badge-owner';
      const roleLabel = d.role === 'remote' ? t('devices.role_remote') : t('devices.role_owner');
      const canRename = d.role === 'owner';
      const title = deviceLabel(d);
      const sysHost = String(d.hostname || '').trim();
      const showSys =
        sysHost && title !== sysHost
          ? '<div class="device-syshost">' + t('devices.syshost') + escapeHtml(sysHost) + '</div>'
          : '';
      btn.innerHTML =
        '<div class="device-head">' +
        '<h2>' +
        escapeHtml(title) +
        '</h2>' +
        (canRename
          ? '<span class="device-rename" data-rename="' +
            escapeHtml(String(d.device_id)) +
            '" title="' + t('devices.rename') + '" role="button" tabindex="0">' + t('devices.rename') + '</span>'
          : '') +
        '</div>' +
        '<div class="device-meta">' +
        '<span class="badge ' +
        roleClass +
        '">' +
        roleLabel +
        '</span>' +
        healthBadge(d.health_status) +
        showSys +
        '<div>' + t('devices.customer_no') +
        escapeHtml(d.member_no || '—') +
        '</div>' +
        (d.lan_ip ? '<div>LAN ' + escapeHtml(d.lan_ip) + '</div>' : '') +
        '<div>' + t('devices.last_seen') +
        formatSeen(d.last_seen_at) +
        '</div>' +
        '</div>' +
        '<div class="ops-consent" data-ops-consent="' +
        escapeHtml(String(d.device_id)) +
        '"></div>';
      btn.addEventListener('click', (ev) => {
        if (ev.target.closest('[data-ops-consent-action]')) return;
        if (ev.target.closest('[data-rename]')) return;
        openRemote(d, { pushHistory: true });
      });
      const renameEl = btn.querySelector('[data-rename]');
      if (renameEl) {
        const runRename = (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          void renameDevice(d);
        };
        renameEl.addEventListener('click', runRename);
        renameEl.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') runRename(ev);
        });
      }
      el.deviceList.appendChild(btn);
    });

    refreshOpsReinstallConsents(devices).catch(() => {});
  }

  async function renameDevice(device) {
    const current = deviceLabel(device);
    const next = window.prompt(
      t('devices.rename_prompt'),
      current,
    );
    if (next == null) return;
    try {
      const data = await auth.renameDevice(device.device_id, next);
      device.display_name = data.display_name || null;
      device.hostname = data.hostname || device.hostname;
      device.name = data.name || deviceLabel(device);
      const list = mergeAndCacheDevices(
        (auth.getCachedDevices() || []).map((row) =>
          String(row.device_id) === String(device.device_id) ? { ...row, ...device } : row,
        ),
      );
      auth.cacheDevices(list);
      renderDevices(list);
      setNotice(t('devices.renamed', { name: deviceLabel(device) }), 'info');
    } catch (e) {
      if (auth.shouldClearSession(e)) {
        auth.clearSession();
        show(el.login);
        return;
      }
      setNotice(e.message || t('devices.rename_fail'), 'info');
    }
  }

  async function refreshOpsReinstallConsents(devices) {
    if (!auth.opsReinstallConsentStatus) return;
    for (const d of devices || []) {
      const slot = el.deviceList.querySelector('[data-ops-consent="' + String(d.device_id) + '"]');
      if (!slot) continue;
      try {
        const st = await auth.opsReinstallConsentStatus(d.device_id);
        if (!st || st.status !== 'sent') {
          slot.innerHTML = '';
          continue;
        }
        slot.innerHTML =
          '<div class="ops-consent-box" style="margin-top:10px;padding:10px;border:1px solid #c45;border-radius:8px;background:#fff5f5;text-align:left">' +
          '<p style="margin:0 0 8px;font-size:13px;line-height:1.45">' + t('ops.consent_msg') + '</p>' +
          '<div style="display:flex;gap:8px">' +
          '<button type="button" class="btn" data-ops-consent-action="yes" data-device-id="' +
          escapeHtml(String(d.device_id)) +
          '">' + t('common.agree') + '</button>' +
          '<button type="button" class="btn btn-ghost" data-ops-consent-action="no" data-device-id="' +
          escapeHtml(String(d.device_id)) +
          '">' + t('common.reject') + '</button>' +
          '</div></div>';
        slot.querySelectorAll('[data-ops-consent-action]').forEach((b) => {
          b.addEventListener('click', async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            const yes = b.getAttribute('data-ops-consent-action') === 'yes';
            const id = Number(b.getAttribute('data-device-id'));
            try {
              await auth.opsReinstallConsentRespond(id, yes);
              slot.innerHTML =
                '<p style="margin-top:8px;font-size:13px;color:#2a7">' +
                (yes ? t('ops.consent_done') : t('ops.consent_rejected')) +
                '</p>';
              setNotice(
                yes ? t('ops.consent_sent') : t('ops.consent_reject_sent'),
                'info',
              );
            } catch (e) {
              setNotice(e.message || t('ops.consent_fail'), 'offline');
            }
          });
        });
      } catch {
        /* ignore per-device */
      }
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function userName() {
    const user = auth.getUser();
    return user.name || user.mb_id || t('common.member');
  }

  function updateUserLabels() {
    const name = userName();
    const suffix = t('common.name_suffix');
    if (el.userLabel) el.userLabel.innerHTML = '<strong>' + escapeHtml(name) + '</strong>' + suffix;
    if (el.installUserLabel) el.installUserLabel.innerHTML = '<strong>' + escapeHtml(name) + '</strong>' + suffix;
  }

  function rerenderForLang() {
    updateUserLabels();
    if (!el.devices.classList.contains('hidden')) {
      const cached = mergeAndCacheDevices(auth.getCachedDevices());
      if (cached.length) renderDevices(cached);
    }
    if (!el.install.classList.contains('hidden') && lastInstall) {
      renderInstallView(lastInstall);
    }
  }

  function showDevicesShell() {
    updateUserLabels();
    const ver = (cfg && cfg.version) || 'v0.9.33';
    const pv = document.getElementById('portal-version');
    const fv = document.getElementById('foot-version');
    if (pv) pv.textContent = ver;
    if (fv) fv.textContent = ver;
    show(el.devices);
    startPortalStatePoll();
  }

  function buildRemoteUiUrl(device) {
    const profile = link.mergeDeviceProfile(device);
    try {
      sessionStorage.setItem(
        'whick_remote_embed_profile',
        JSON.stringify({
          device_id: device.device_id,
          lan: profile.lan,
          tunnel: profile.tunnel,
          member_no: device.member_no,
          hostname: device.name || device.display_name || device.hostname,
          display_name: device.display_name || null,
          player_token: device.player_token || null,
        }),
      );
    } catch {
      /* ignore */
    }
    const base = String(cfg.remoteUiBase || '/v4').replace(/\/$/, '');
    // 언어는 v4 리모컨과 동일한 localStorage 키(whick_sales_remote_lang)를 공유하므로
    // URL lang 파라미터를 붙이지 않는다. (URL lang은 detect()에서 localStorage보다 우선해
    // 리모컨 안에서 언어를 바꾼 뒤 새로고침하면 되돌아가는 회귀를 유발함)
    // v= 로 구버전 탭·브라우저 캐시된 index.html 강제 갱신
    return base + '/index.html?embed=1&device=' + encodeURIComponent(String(device.device_id))
      + '&v=20260903-en1';
  }

  function openRemote(device, { pushHistory = false } = {}) {
    currentDevice = device;
    localStorage.setItem(cfg.deviceKey, String(device.device_id));
    setRemoteLinkStatus(t('link.opening'), 'info');
    show(el.loading);
    if (pushHistory) pushRoute('remote', device);
    else replaceRoute('remote', device);

    // player_token 최신화 후 v4로 이동 (즐겨듣기 POST 인증에 필수)
    Promise.resolve()
      .then(async () => {
        try {
          const data = await auth.api('/devices/' + encodeURIComponent(device.device_id) + '/player-token');
          const tok = data?.player_token || data?.data?.player_token;
          if (tok) device.player_token = tok;
        } catch {
          /* 기존 device.player_token 유지 */
        }
        const profile = link.mergeDeviceProfile(device);
        refreshMusicLink(profile);
        window.location.assign(buildRemoteUiUrl(device));
      })
      .catch(() => {
        const profile = link.mergeDeviceProfile(device);
        refreshMusicLink(profile);
        window.location.assign(buildRemoteUiUrl(device));
      });
  }

  async function refreshDevices({ silent = false, updateProfiles = false } = {}) {
    if (!auth.getToken()) {
      show(el.login);
      return;
    }

    showDevicesShell();
    if (!silent) {
      el.deviceList.innerHTML = '';
      el.deviceEmpty.classList.add('hidden');
      const spinner = document.createElement('div');
      spinner.className = 'spinner';
      el.deviceList.appendChild(spinner);
    }

    try {
      const devices = mergeAndCacheDevices(await auth.listDevices());
      auth.cacheDevices(devices);
      renderDevices(devices);
      const allOffline = devices.length > 0 && devices.every((d) => !d.agent_online);
      if (allOffline) {
        setNotice(
          t('notice.install_pending'),
          'info',
        );
      } else {
        setNotice(null);
      }

      if (updateProfiles && currentDevice) {
        const updated = devices.find((d) => String(d.device_id) === String(currentDevice.device_id));
        if (updated) {
          currentDevice = updated;
          if (!el.remote.classList.contains('hidden')) {
            refreshMusicLink(link.getDeviceProfile(updated.device_id));
          }
        }
      }
    } catch (e) {
      if (auth.shouldClearSession(e)) {
        auth.clearSession();
        show(el.login);
        return;
      }

      const cached = mergeAndCacheDevices(auth.getCachedDevices());
      renderDevices(cached);

      if (auth.isNetworkError(e)) {
        setNotice(
          cached.length
            ? t('notice.network_unstable_saved')
            : t('notice.network_unstable_retry'),
          'offline',
        );
      } else {
        setNotice(e.message || t('notice.load_fail'), 'info');
      }
    }
  }

  async function boot() {
    if (bootDone) return;
    show(el.loading);

    const handoff = parseHandoff();
    if (handoff && applyHandoff(handoff)) {
      return;
    }

    const hash = location.hash || '';
    const hashRemote = hash.match(/^#\/remote\/(\d+)/);

    if (!auth.getToken()) {
      bootDone = true;
      show(el.login);
      replaceRoute('login');
      return;
    }

    const session = await auth.verifySession();
    if (!session.ok) {
      bootDone = true;
      auth.clearSession();
      show(el.login);
      replaceRoute('login');
      return;
    }

    bootDone = true;

    if (session.offline) {
      setNotice(t('notice.offline_session'), 'offline');
    }

    if (hashRemote) {
      applyRoute({ view: 'remote', deviceId: hashRemote[1] });
      return;
    }

    if (hash === '#/install') {
      applyRoute({ view: 'install' });
      return;
    }

    if (hash === '#/devices' || hash === '#/remote') {
      if (await redirectToInstallIfActive({ silent: false })) return;
      applyRoute({ view: 'devices' });
      return;
    }

    showDevicesShell();
    replaceRoute('devices');
    try {
      const bootstrap = await auth.bootstrap();
      if (bootstrap.mode === 'install') {
        bootDone = true;
        await enterAfterAuth(bootstrap, { fromLogin: false });
        return;
      }
    } catch {
      /* fallback devices */
    }
    const cached = mergeAndCacheDevices(auth.getCachedDevices());
    if (cached.length) renderDevices(cached);
    refreshDevices({ silent: !!cached.length });
  }

  el.loginForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    el.loginErr.classList.add('hidden');
    el.loginErr.textContent = '';
    el.loginBtn.disabled = true;

    const fd = new FormData(el.loginForm);
    const login = String(fd.get('login') || '').trim();
    const password = String(fd.get('password') || '');

    try {
      const data = await auth.login(login, password);
      bootDone = true;
      setNotice(null);
      await enterAfterAuth(data, { fromLogin: true });
    } catch (e) {
      el.loginErr.textContent = e.message || t('login.fail');
      el.loginErr.classList.remove('hidden');
    } finally {
      el.loginBtn.disabled = false;
    }
  });

  el.logoutBtn.addEventListener('click', () => {
    auth.clearSession();
    currentDevice = null;
    bootDone = false;
    stopInstallPoll();
    stopPortalStatePoll();
    setNotice(null);
    show(el.login);
    replaceRoute('login');
  });

  el.installLogoutBtn?.addEventListener('click', () => {
    el.logoutBtn?.click();
  });

  el.backDevices.addEventListener('click', () => {
    history.back();
  });

  window.addEventListener('popstate', (ev) => {
    if (!auth.getToken()) {
      show(el.login);
      return;
    }
    applyRoute(ev.state || { view: 'devices' });
  });

  window.addEventListener('pageshow', (ev) => {
    if (!auth.getToken()) return;
    if (ev.persisted) {
      applyRoute(history.state || { view: 'devices' });
      return;
    }
    auth.verifySession().then((session) => {
      if (!session.ok) return;
      if (!el.remote.classList.contains('hidden') && currentDevice) {
        refreshMusicLink(link.getDeviceProfile(currentDevice.device_id));
      }
    });
  });

  window.addEventListener('online', () => {
    link.handleNetworkRestore(() => refreshDevices({ silent: true, updateProfiles: true }));
    if (!el.remote.classList.contains('hidden') && currentDevice) {
      refreshMusicLink(link.getDeviceProfile(currentDevice.device_id));
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || !auth.getToken()) return;
    refreshPortalState();
    if (!el.remote.classList.contains('hidden') && currentDevice) {
      refreshMusicLink(link.getDeviceProfile(currentDevice.device_id));
    }
    link.reconnectMusicApi();
  });

  if (window.WhickPortalI18n && typeof window.WhickPortalI18n.onLangChange === 'function') {
    window.WhickPortalI18n.onLangChange(function () {
      rerenderForLang();
    });
  }

  boot();
})();
