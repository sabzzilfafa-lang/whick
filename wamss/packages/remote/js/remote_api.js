/**
 * Whick Remote — v4 SSOT 통신·UI 브리지
 * 설계: 3_product/docs/REMOTE-DESIGN.md
 *
 * Wi-Fi ↔ LTE 전환: LAN 우선 → 터널 fallback · 자동 재연결
 */
function normalizeRemoteHost(host) {
  return String(host || '')
    .trim()
    .replace(/^https?:\/\//, '')
    .replace(/\/.*$/, '')
    .replace(/:\d+$/, '');
}

/** 날씨 context 값(한글·영문) → 현재 언어 라벨 (server 기준값을 UI에서 매핑) (2026-09-03) */
window._pdT = function (koValue) {
  const v = String(koValue || '').trim();
  if (!v) return '';
  const MAP = {
    '새벽': 'wx.dawn',
    '아침': 'wx.morning',
    '한낮': 'wx.afternoon',
    '오후': 'wx.afternoon',
    '저녁': 'wx.evening',
    '밤': 'wx.night',
    '맑음': 'wx.sunny',
    '흐림': 'wx.cloudy',
    '비': 'wx.rainy',
    '눈': 'wx.snowy',
    '바람': 'wx.windy',
    '안개': 'wx.foggy',
    // server가 영문값을 주는 경우(v0.9.98+)도 현재 언어로 변환
    'Dawn': 'wx.dawn',
    'Morning': 'wx.morning',
    'Afternoon': 'wx.afternoon',
    'Evening': 'wx.evening',
    'Night': 'wx.night',
    'Sunny': 'wx.sunny',
    'Cloudy': 'wx.cloudy',
    'Rainy': 'wx.rainy',
    'Snowy': 'wx.snowy',
    'Windy': 'wx.windy',
    'Foggy': 'wx.foggy',
  };
  const key = MAP[v];
  if (!key) return v; // 알 수 없는 값은 원본 그대로
  try {
    const t = window.WhickI18n && typeof window.WhickI18n.t === 'function' ? window.WhickI18n.t(key) : null;
    return t && t !== key ? t : v;
  } catch {
    return v;
  }
};

function isPrivateRemoteHost(host) {
  const h = normalizeRemoteHost(host);
  return (
    /^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h) ||
    h === 'localhost' ||
    h === '127.0.0.1'
  );
}

function buildRemoteUrls(host) {
  const h = normalizeRemoteHost(host);
  const isLAN = isPrivateRemoteHost(h);
  // 미니PC에서 UI를 직접 연 경우(http://IP/ 또는 :8080) → same-origin (포트 80 포함)
  if (
    isLAN &&
    typeof location !== 'undefined' &&
    location.protocol === 'http:' &&
    normalizeRemoteHost(location.hostname) === h
  ) {
    const origin = location.origin;
    return {
      host: h,
      isLAN: true,
      baseURL: origin,
      wsURL: origin.replace(/^http/, 'ws') + '/ws',
    };
  }
  return {
    host: h,
    isLAN,
    baseURL: isLAN ? `http://${h}:8080` : `https://${h}`,
    wsURL: isLAN ? `ws://${h}:8080/ws` : `wss://${h}/ws`,
  };
}

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const WHICK_RADIO_STATIONS_FALLBACK = [
  { id: 'kbs-1radio', name: _t('radio.name.kbs-1radio', 'KBS 1 Radio'), org: _t('radio.org.kbs', 'KBS'), desc: _t('radio.desc.kbs-1radio', 'News · Current Affairs'), emoji: '📻', category: 'terrestrial' },
  { id: 'kbs-2radio', name: _t('radio.name.kbs-2radio', 'KBS 2 Radio'), org: _t('radio.org.kbs', 'KBS'), desc: _t('radio.desc.kbs-2radio', 'Lifestyle Info'), emoji: '📻', category: 'terrestrial' },
  { id: 'kbs-3radio', name: _t('radio.name.kbs-3radio', 'KBS 3 Radio'), org: _t('radio.org.kbs', 'KBS'), desc: _t('radio.desc.kbs-3radio', 'Music · Culture'), emoji: '🎵', category: 'terrestrial' },
  { id: 'kbs-1fm', name: _t('radio.name.kbs-1fm', 'KBS 1FM'), org: _t('radio.org.kbs', 'KBS'), desc: _t('radio.desc.kbs-1fm', 'Classical'), emoji: '🎼', category: 'terrestrial' },
  { id: 'kbs-coolfm', name: _t('radio.name.kbs-coolfm', 'KBS Cool FM'), org: _t('radio.org.kbs', 'KBS'), desc: _t('radio.desc.kbs-coolfm', 'Pop Music'), emoji: '🎵', category: 'terrestrial' },
  { id: 'kbs-hanmin', name: _t('radio.name.kbs-hanmin', 'KBS Hanminjok'), org: _t('radio.org.kbs', 'KBS'), desc: _t('radio.desc.kbs-hanmin', 'Traditional · Gugak'), emoji: '🎶', category: 'terrestrial' },
  { id: 'mbc-sfm', name: _t('radio.name.mbc-sfm', 'MBC Standard FM'), org: _t('radio.org.mbc', 'MBC'), desc: _t('radio.desc.mbc-sfm', 'Standard FM'), emoji: '📻', category: 'terrestrial' },
  { id: 'mbc-fm4u', name: 'MBC FM4U', org: 'MBC', desc: 'FM4U', emoji: '🎤', category: 'terrestrial' },
  { id: 'sbs-love', name: _t('radio.name.sbs-love', 'SBS Love FM'), org: _t('radio.org.sbs', 'SBS'), desc: _t('radio.desc.sbs-love', 'Love FM'), emoji: '❤️', category: 'terrestrial' },
  { id: 'sbs-power', name: _t('radio.name.sbs-power', 'SBS Power FM'), org: _t('radio.org.sbs', 'SBS'), desc: _t('radio.desc.sbs-power', 'Power FM'), emoji: '⚡', category: 'terrestrial' },
  { id: 'ebs-fm', name: _t('radio.name.ebs-fm', 'EBS FM'), org: _t('radio.org.ebs', 'EBS'), desc: _t('radio.desc.ebs-fm', 'Education · Culture'), emoji: '📚', category: 'terrestrial' },
  { id: 'tbs-fm', name: _t('radio.name.tbs-fm', 'TBS FM'), org: _t('radio.org.tbs', 'TBS'), desc: _t('radio.desc.tbs-fm', 'Traffic · Lifestyle'), emoji: '🚦', category: 'internet' },
  { id: 'tbs-efm', name: _t('radio.name.tbs-efm', 'TBS eFM'), org: _t('radio.org.tbs', 'TBS'), desc: _t('radio.desc.tbs-efm', 'English'), emoji: '🌐', category: 'internet' },
  // sales-remote SSOT fallback · Hi-Res 음악전문 (Mother Earth 제외 · 무료 FLAC)
  { id: 'hires-radio-calico', name: _t('radio.name.calico', 'Radio Calico'), org: _t('radio.org.us', 'USA'), desc: _t('radio.desc.calico', '24bit/48kHz FLAC · Ad-free'), emoji: '🐱', category: 'hires' },
  { id: 'hires-jb-radio-2', name: _t('radio.name.jb2', 'JB Radio-2'), org: _t('radio.org.be', 'Belgium'), desc: _t('radio.desc.jb2', '24bit/96kHz FLAC · Classical · Jazz · Pop'), emoji: '🎷', category: 'hires' },
  { id: 'hires-intense-radio', name: _t('radio.name.intense', 'Intense Radio'), org: _t('radio.org.nl', 'Netherlands'), desc: _t('radio.desc.intense', '24bit/44.1kHz FLAC · EDM/Dance · Free'), emoji: '⚡', category: 'hires' },
  { id: 'hires-radio-paradise', name: _t('radio.name.paradise', 'Radio Paradise'), org: _t('radio.org.us', 'USA'), desc: _t('radio.desc.paradise', '16bit/44.1kHz FLAC · Lossless Free'), emoji: '🌴', category: 'hires' },
  { id: 'hires-the-cheese', name: _t('radio.name.cheese', 'The Cheese'), org: _t('radio.org.nz', 'New Zealand'), desc: _t('radio.desc.cheese', '16bit/44.1kHz FLAC · Lossless Stream'), emoji: '🧀', category: 'hires' },
];

function normalizeRadioStations(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.stations)) return data.stations;
  return [];
}

class WhickAPI {
  constructor(serverHostOrOpts) {
    this.lanHost = null;
    this.tunnelHost = null;
    this.activeHost = null;
    this.connectionMode = null;
    this.deviceId = null;
    this.ws = null;
    this.wsReady = false;
    this.reconnectDelay = 2000;
    this.reconnectTimer = null;
    this.connecting = false;
    this.intentionalDisconnect = false;
    this.listeners = {};
    this.connectMode = 'auto';
    this.stateCache = { source: 'idle', playing: false, repeat: 'none', volume: 70 };
    this.mobileAudio = null;
    this.outputMode = 'server';
    this.clientId = this._ensureClientId();
    this._mobileTrackId = null;
    this._mobileRadioId = null;
    this._mobileStreamKey = null;
    this._mobileClaimedKey = null;
    this._mobileAwaitingOwnTransport = false;
    this._mobileAutoplayBlocked = false;
    this._mobileIsPreview = false;
    this._serverPlaying = false;
    this._mobileRadioSyncLock = null;
    this._mobileTransportPendingUntil = 0;
    this._mobileTransportOrigin = null;
    this._mobileHandoffGraceUntil = 0;
    this._outputHandoffLock = false;
    this._mobileAudioCtx = null;
    this._mobileAnalyser = null;
    this._mobileSpectrumSource = null;
    this._mobileSpectrumTimer = null;
    this._mobileSpectrumSmooth = null;
    this._manualReconnect = false;
    this._lastVolumeSent = null;
    /** 볼륨 드래그·연속 전송 직후 — 지연 state 방송이 막대를 좌우로 흔들지 않게 무시 */
    this._volumeHoldUntil = 0;
    // 듀얼 링크 — 터널·Wi-Fi(LAN)를 동시에 상시 유지. _primary 가 주 연결.
    this._links = {};
    this._primary = null;
    this._everConnected = false;
    try {
      this.outputMode =
        localStorage.getItem('whick_remote_output') === 'mobile' ? 'mobile' : 'server';
    } catch {
      this.outputMode = 'server';
    }
    this.playerToken = null;
    this._incomingAudit = null;

    if (serverHostOrOpts && typeof serverHostOrOpts === 'object') {
      this.deviceId = serverHostOrOpts.deviceId || null;
      this.lanHost = normalizeRemoteHost(serverHostOrOpts.lan) || null;
      this.tunnelHost = normalizeRemoteHost(serverHostOrOpts.tunnel) || null;
      if (serverHostOrOpts.connectMode) {
        this.connectMode = String(serverHostOrOpts.connectMode);
      }
      if (serverHostOrOpts.playerToken) {
        this.playerToken = String(serverHostOrOpts.playerToken);
      }
      const single = normalizeRemoteHost(serverHostOrOpts.host);
      if (single && !this.lanHost && !this.tunnelHost) {
        if (isPrivateRemoteHost(single)) this.lanHost = single;
        else this.tunnelHost = single;
      }
    } else {
      const h = normalizeRemoteHost(serverHostOrOpts);
      if (isPrivateRemoteHost(h)) this.lanHost = h;
      else if (h) this.tunnelHost = h;
    }

    const initial = this.lanHost || this.tunnelHost || '';
    this.host = initial;
    this._applyUrls(initial);
  }

  _applyUrls(host) {
    const urls = buildRemoteUrls(host);
    this.host = urls.host;
    this.baseURL = urls.baseURL;
    this.wsURL = urls.wsURL;
  }

  setEndpoints({ lan, tunnel, deviceId } = {}) {
    if (deviceId != null) this.deviceId = deviceId;
    if (lan != null) this.lanHost = normalizeRemoteHost(lan) || null;
    if (tunnel != null) this.tunnelHost = normalizeRemoteHost(tunnel) || null;
  }

  _endpointCandidates() {
    const out = [];
    if (this.lanHost) out.push({ host: this.lanHost, mode: 'lan' });
    if (this.tunnelHost && this.tunnelHost !== this.lanHost) {
      out.push({ host: this.tunnelHost, mode: 'tunnel' });
    }
    if (!out.length && this.host) {
      out.push({
        host: this.host,
        mode: isPrivateRemoteHost(this.host) ? 'lan' : 'tunnel',
      });
    }
    const mode = String(this.connectMode || 'auto').toLowerCase();
    if (mode === 'lan') {
      const lan = out.filter((c) => c.mode === 'lan');
      return lan.length ? lan : out;
    }
    if (mode === 'tunnel' || mode === 'cc') {
      const tun = out.filter((c) => c.mode === 'tunnel');
      return tun.length ? tun : out;
    }
    return out;
  }

  setConnectMode(mode) {
    const m = String(mode || 'auto').toLowerCase();
    this.connectMode = m === 'cc' ? 'tunnel' : m;
    try {
      localStorage.setItem('whick_remote_connect_mode', this.connectMode);
    } catch {
      /* ignore */
    }
  }

  connect() {
    this.intentionalDisconnect = false;
    this._ensureLinks();
    return Promise.resolve(this.wsReady);
  }

  // 모드 변경·네트워크 변동 시: 죽은 링크는 재연결하고 주 연결을 모드에 맞춰 다시 선택
  reconnect() {
    this.intentionalDisconnect = false;
    this._ensureLinks();
    this._updatePrimary();
    return Promise.resolve(this.wsReady);
  }

  // 유지할 링크 목록 — 터널 + (있으면)Wi-Fi LAN. 모드와 무관하게 둘 다 유지한다.
  _linkSpecs() {
    const specs = [];
    if (this.lanHost) specs.push({ mode: 'lan', host: this.lanHost });
    if (this.tunnelHost && this.tunnelHost !== this.lanHost) {
      specs.push({ mode: 'tunnel', host: this.tunnelHost });
    }
    if (!specs.length && this.host) {
      specs.push({ mode: isPrivateRemoteHost(this.host) ? 'lan' : 'tunnel', host: this.host });
    }
    return specs;
  }

  _ensureLinks() {
    if (this.intentionalDisconnect) return;
    const specs = this._linkSpecs();
    const wanted = new Set(specs.map((s) => s.mode));
    for (const mode of Object.keys(this._links)) {
      if (!wanted.has(mode)) {
        this._closeLink(this._links[mode]);
        delete this._links[mode];
      }
    }
    for (const spec of specs) {
      let link = this._links[spec.mode];
      if (!link) {
        link = { mode: spec.mode, host: spec.host, ws: null, ready: false, timer: null, delay: 2000 };
        this._links[spec.mode] = link;
      } else {
        link.host = spec.host;
      }
      this._connectLink(link);
    }
  }

  _connectLink(link) {
    if (this.intentionalDisconnect || !link) return;
    if (link.ws && (link.ws.readyState === WebSocket.OPEN || link.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const urls = buildRemoteUrls(link.host);
    let ws;
    try {
      ws = new WebSocket(this._wsUrlWithAuth(urls.wsURL));
    } catch {
      this._scheduleLink(link);
      return;
    }
    link.ws = ws;
    link.ready = false;
    ws.onopen = () => {
      if (this.intentionalDisconnect) {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
        return;
      }
      link.ready = true;
      link.delay = 2000;
      clearTimeout(link.timer);
      this._updatePrimary();
    };
    ws.onmessage = (e) => {
      // 주 연결의 메시지만 처리 — 중복 이벤트 방지(두 링크가 같은 broadcast 수신)
      if (this._primary === link) this._handleWsMessage(e);
    };
    ws.onclose = () => {
      if (link.ws !== ws) return;
      link.ws = null;
      link.ready = false;
      this._updatePrimary();
      if (!this.intentionalDisconnect) this._scheduleLink(link);
    };
    ws.onerror = () => {};
  }

  _scheduleLink(link) {
    if (this.intentionalDisconnect || !link) return;
    clearTimeout(link.timer);
    link.timer = setTimeout(() => {
      link.delay = Math.min((link.delay || 2000) * 1.5, 30000);
      this._connectLink(link);
    }, link.delay || 2000);
  }

  _closeLink(link) {
    if (!link) return;
    clearTimeout(link.timer);
    if (link.ws) {
      try {
        link.ws.onopen = link.ws.onclose = link.ws.onerror = link.ws.onmessage = null;
        link.ws.close();
      } catch {
        /* ignore */
      }
    }
    link.ws = null;
    link.ready = false;
  }

  // 고객 선택(connectMode)에 따라 주 연결 선택 — 둘 다 준비됐으면 선택한 쪽 우선
  _pickPrimary() {
    const mode = String(this.connectMode || 'auto').toLowerCase();
    const lan = this._links.lan;
    const tun = this._links.tunnel;
    const ready = (l) => l && l.ready;
    if (mode === 'tunnel') return ready(tun) ? tun : ready(lan) ? lan : null;
    // 'lan' · 'auto' 모두 Wi-Fi 직접 우선, 없으면 터널
    return ready(lan) ? lan : ready(tun) ? tun : null;
  }

  _updatePrimary() {
    const prev = this._primary;
    const next = this._pickPrimary();
    const wasReady = this.wsReady;

    // 동일 링크 객체가 재연결된 경우(유일 링크 down→up) — prev===next 이지만 세션 복구 필요
    if (next === prev) {
      this.wsReady = !!(next && next.ready);
      if (next) this.ws = next.ws;
      if (this.wsReady && !wasReady) {
        const payload = {
          host: next.host,
          mode: next.mode,
          standby: this._otherReady(next),
        };
        this.emit('connected', payload);
        void this._pullStateFromServer();
      }
      return;
    }

    this._primary = next;
    if (next) {
      this.ws = next.ws;
      this.wsReady = true;
      this.connectionMode = next.mode;
      this.activeHost = next.host;
      this._applyUrls(next.host);
      const payload = {
        host: next.host,
        mode: next.mode,
        standby: this._otherReady(next),
      };
      const wasAllDown = !wasReady;
      if (wasAllDown) {
        this._everConnected = true;
        this.emit('connected', payload);
      } else {
        this.emit('primary_changed', payload);
      }
      void this._pullStateFromServer();
    } else {
      this.ws = null;
      this.wsReady = false;
      this.emit('disconnected', { reason: 'all_links_down' });
    }
  }

  /** WS 초기 스냅샷·primary 전환·재연결 후 stateCache 동기화 (설계: GET /api/state = WS 끊김 fallback) */
  async _pullStateFromServer() {
    if (!this.wsReady) return;
    if (this.outputMode === 'mobile') {
      void this._pullMobileState();
      return;
    }
    try {
      const data = await this.getState();
      if (!data || typeof data !== 'object') return;
      if (typeof data.playing === 'boolean') {
        this._serverPlaying = data.playing;
      }
      this.stateCache = this._mergeStateFromServer(data);
      if (typeof data.volume === 'number' && !this._volumeUiLocked()) {
        this._lastVolumeSent = Math.max(0, Math.min(100, Math.round(data.volume)));
      }
      await this._syncMobilePlaybackFromState(this.stateCache);
      this.emit('state', this.stateCache);
    } catch (err) {
      console.warn('[WhickAPI] state pull failed', err);
    }
  }

  /** 사용자가 막대를 놓은 직후·드래그 중 — 서버 옛 volume 로 UI/_lastVolumeSent 덮어쓰기 금지 */
  _volumeUiLocked() {
    return Date.now() < (this._volumeHoldUntil || 0);
  }

  /** 모바일 존 재연결·출력 전환 — WS로 현재 상태 요청 */
  _pullMobileState() {
    if (!this.wsReady || !this.ws) return;
    this._sendWithOutput({ cmd: 'get_state' }, 'mobile');
  }

  _otherReady(primary) {
    return Object.values(this._links).some((l) => l !== primary && l.ready);
  }

  _authHeaders(extra = {}) {
    const h = { ...extra };
    if (this.playerToken) {
      h.Authorization = `Bearer ${this.playerToken}`;
    }
    return h;
  }

  _authenticatedUrl(pathOrUrl) {
    const url = pathOrUrl.startsWith('http')
      ? new URL(pathOrUrl)
      : new URL(pathOrUrl, this.baseURL);
    if (this.playerToken) {
      url.searchParams.set('token', this.playerToken);
    }
    return url.toString();
  }

  _wsUrlWithAuth(wsURL = this.wsURL) {
    const u = new URL(wsURL);
    if (this.playerToken) u.searchParams.set('token', this.playerToken);
    u.searchParams.set('client_id', this.clientId);
    return u.toString();
  }

  /** 탭·PWA 인스턴스별 ID — 같은 계정의 다른 폰과 모바일 출력을 격리 */
  _ensureClientId() {
    try {
      const key = 'whick_remote_client_id';
      let id = sessionStorage.getItem(key);
      if (!id || id.length < 8) {
        id =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
        sessionStorage.setItem(key, id);
      }
      return id;
    } catch {
      return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    }
  }

  _mobileSessionKey(state) {
    if (!state) return null;
    if (state.source === 'library' && state.track_id != null) return `library:${state.track_id}`;
    if (state.source === 'radio' && state.radio_station_id) return `radio:${state.radio_station_id}`;
    if ((state.source === 'spotify' || state.source === 'tidal') && state.stream_id) {
      return `${state.source}:${state.stream_id}`;
    }
    return null;
  }

  _claimMobileSession(keyOrState) {
    const key =
      typeof keyOrState === 'string' ? keyOrState : this._mobileSessionKey(keyOrState);
    this._mobileClaimedKey = key || null;
    this._mobileAwaitingOwnTransport = false;
  }

  _clearMobileClaim() {
    this._mobileClaimedKey = null;
    this._mobileAwaitingOwnTransport = false;
  }

  /** 이 기기가 모바일 오디오를 내야 하는 세션인지 */
  _isMobileAudioOwner(state) {
    // 서버가 이 client_id 소켓에만 보낸 모바일 존 상태 → 항상 이 기기 소유
    if (state?.output_scope === 'mobile') {
      const owner = state.mobile_owner_client_id || null;
      return !owner || owner === this.clientId;
    }
    // 전역 STATE에는 더 이상 mobile owner 독점을 쓰지 않음
    if (this._mobileAwaitingOwnTransport && state?.playing) return true;
    const key = this._mobileSessionKey(state);
    return !!(key && this._mobileClaimedKey && this._mobileClaimedKey === key);
  }

  _mergeStateFromServer(data) {
    const prev = this.stateCache || {};
    // DIAGNOSTIC: remove after debugging
    if (data.event === 'state') {
      const d = {src:data.source, tid:data.track_id, title:data.title, artist:data.artist, playing:data.playing};
      console.log('[MERGE]', new Date().toISOString().slice(11,19), 'INCOMING:', JSON.stringify(d), 'PREV:', prev.track_id, prev.title);
    }
    const merged = { ...prev, ...data };
    // MPD 전환 중 currentsong이 null 반환해도 기존 메타 보존
    if (data.title == null && prev.title != null) merged.title = prev.title;
    if (data.artist == null && prev.artist != null) merged.artist = prev.artist;
    if (data.album == null && prev.album != null) merged.album = prev.album;
    if (this.outputMode === 'mobile' && this.mobileAudio) {
      const trackChanged =
        (data.track_id != null && data.track_id !== prev.track_id) ||
        (data.stream_id != null && data.stream_id !== prev.stream_id) ||
        (data.radio_station_id != null && data.radio_station_id !== prev.radio_station_id) ||
        (data.source != null && data.source !== prev.source);
      if (!trackChanged) {
        merged.position = prev.position ?? data.position;
        if (this._mobileIsPreview && prev.duration > 0) {
          merged.duration = prev.duration;
        } else if (prev.duration > 0 && (!data.duration || data.duration === 0)) {
          merged.duration = prev.duration;
        }
      }
    }
    // 볼륨 드래그/전송 직후 — 지연 broadcast 의 옛 volume 으로 stateCache 가 흔들리지 않게
    if (this._volumeUiLocked() && this._lastVolumeSent != null) {
      merged.volume = this._lastVolumeSent;
    }
    // DIAGNOSTIC: remove after debugging
    console.log('[MERGE]', new Date().toISOString().slice(11,19), 'RESULT:', merged.track_id, merged.title, merged.artist, 'playing:', merged.playing);
    return merged;
  }

  _handleWsMessage(e) {
    try {
      const data = JSON.parse(e.data);
      if (data.event === 'state') {
        const isMobileState = data.output_scope === 'mobile';
        // 서버 스피커와 각 모바일 기기는 독립 존이다.
        if (this.outputMode === 'mobile' && !isMobileState) return;
        if (this.outputMode !== 'mobile' && isMobileState) return;
        if (!isMobileState && typeof data.playing === 'boolean') {
          this._serverPlaying = data.playing;
        }
        this.stateCache = this._mergeStateFromServer(data);
        if (typeof data.volume === 'number' && !this._volumeUiLocked()) {
          this._lastVolumeSent = Math.max(0, Math.min(100, Math.round(data.volume)));
        }
        void this._syncMobilePlaybackFromState(this.stateCache);
        this.emit('state', this.stateCache);
      } else if (data.event === 'spatial') {
        this.stateCache.spatial = data;
        this.emit('spatial', data);
      } else if (data.event === 'spectrum') {
        this.stateCache.spectrum = data;
        this.emit('spectrum', data);
      } else if (data.event === 'usb_library_prompt') {
        this.emit('usb_library_prompt', data);
      } else if (data.event === 'external_library_review') {
        this.emit('external_library_review', data);
      } else if (
        data.event === 'consent_request' ||
        data.event === 'agent_offline' ||
        data.event === 'agent_recovered' ||
        data.event === 'cc_link_lost' ||
        data.event === 'cc_link_recovered' ||
        data.event === 'notify'
      ) {
        this.emit('notify', data);
      }
    } catch (err) {
      console.warn('[WhickAPI] parse', err);
    }
  }

  disconnect() {
    this.intentionalDisconnect = true;
    this.stopRadio();
    for (const mode of Object.keys(this._links)) {
      this._closeLink(this._links[mode]);
    }
    this._links = {};
    this._primary = null;
    this.ws = null;
    this.wsReady = false;
  }

  _send(cmd) {
    return this._sendWithOutput(cmd, this.outputMode === 'mobile' ? 'mobile' : 'server');
  }

  _sendWithOutput(cmd, output) {
    if (!this.wsReady || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this._updatePrimary();
    }
    if (!this.wsReady || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WhickAPI] WS 미연결', cmd);
      return false;
    }
    const payload = {
      ...cmd,
      output: output === 'mobile' ? 'mobile' : 'server',
      client_id: this.clientId,
    };
    console.log('[DIAG] WS SEND', new Date().toISOString().slice(11,19), JSON.stringify({cmd: payload.cmd, track_id: payload.track_id, station_id: payload.station_id, output: payload.output, client_id: payload.client_id}));
    this.ws.send(JSON.stringify(payload));
    return true;
  }

  _mobileTransportBlocked() {
    return this._mobileTransportPendingUntil > Date.now();
  }

  _beginMobileTransportGuard() {
    const state = this.stateCache || {};
    this._mobileTransportOrigin = {
      source: state.source || null,
      trackId: this._mobileTrackId ?? state.track_id ?? null,
      radioId: this._mobileRadioId ?? state.radio_station_id ?? null,
      streamId: state.stream_id ?? null,
    };
    this._mobileTransportPendingUntil = Date.now() + 2500;
  }

  _guardMobileTransportState(state) {
    if (!this._mobileTransportBlocked()) {
      this._mobileTransportOrigin = null;
      return false;
    }
    const origin = this._mobileTransportOrigin || {};
    const sameOrigin =
      !state.playing ||
      (state.source === 'library' &&
        origin.source === 'library' &&
        state.track_id === origin.trackId) ||
      (state.source === 'radio' &&
        origin.source === 'radio' &&
        state.radio_station_id === origin.radioId) ||
      ((state.source === 'spotify' || state.source === 'tidal') &&
        state.source === origin.source &&
        state.stream_id === origin.streamId);
    if (sameOrigin) return true;
    this._mobileTransportPendingUntil = 0;
    this._mobileTransportOrigin = null;
    return false;
  }

  async _syncMobilePlaybackFromState(state) {
    if (this._outputHandoffLock) return;
    if (this.outputMode !== 'mobile') {
      if (this.mobileAudio) this._stopMobileAudio();
      this._mobileTrackId = null;
      this._mobileRadioId = null;
      this._mobileStreamKey = null;
      this._clearMobileClaim();
      return;
    }
    // 모바일 존(output_scope=mobile)은 기기별 독립 — 타 기기 owner로 로컬 재생을 죽이지 않는다.
    // 전역 STATE가 섞여 들어온 경우에만 owner/claim으로 걸러낸다.
    if (state.output_scope !== 'mobile' && state.playing && !this._isMobileAudioOwner(state)) {
      // 서버 스피커 존 상태 — 모바일 출력 기기에서는 무시
      return;
    }
    if (
      state.output_scope !== 'mobile' &&
      !state.playing &&
      state.mobile_owner_client_id &&
      state.mobile_owner_client_id !== this.clientId
    ) {
      return;
    }
    if (this._isMobileAudioOwner(state) || state.output_scope === 'mobile') {
      const key = this._mobileSessionKey(state);
      if (key) this._mobileClaimedKey = key;
    }
    // next/prev·라디오 변경 직후에는 서버에서 늦게 도착한 이전 소스 상태를 무시한다.
    // 새 track/station 상태는 즉시 통과시켜 모바일 재생 지연을 만들지 않는다.
    if (this._guardMobileTransportState(state)) return;
    // 모바일 전환 직후 보호창: 서버 stop→play 재설정 과정에서 잠깐 들어오는
    // source=idle·playing=false 브로드캐스트가 방금 시작한 폰 오디오를 끄지 않도록 한다.
    // (이 레이스가 반복 전환 시 두 번째부터 무음이 되던 원인)
    if (
      this._mobileHandoffGraceUntil &&
      Date.now() < this._mobileHandoffGraceUntil &&
      this.mobileAudio &&
      !this.mobileAudio.paused &&
      (!state.playing || state.source === 'idle')
    ) {
      return;
    }
    if (!state.playing) {
      if (
        this.mobileAudio &&
        state.source &&
        state.source !== 'idle' &&
        state.source === (this.stateCache?.source || state.source)
      ) {
        this.mobileAudio.pause();
        return;
      }
      this._stopMobileAudio();
      this._mobileTrackId = null;
      this._mobileRadioId = null;
      this._mobileStreamKey = null;
      return;
    }
    if (state.source === 'radio' && state.radio_station_id) {
      if (this._mobileRadioSyncLock) {
        return;
      }
      if (this._mobileRadioId === state.radio_station_id && this.mobileAudio) {
        if (this._mobileTransportBlocked()) {
          return;
        }
        // 자동재생 차단 시 state 브로드캐스트마다 play() 재시도하면 배너가 깜빡이고
        // 사용자 탭 재생과 충돌(play() interrupted)한다 → 탭(resumeMobilePlayback)에만 위임.
        if (this._mobileAutoplayBlocked) {
          return;
        }
        if (this.mobileAudio.paused) {
          try {
            await this.mobileAudio.play();
          } catch (err) {
            this._mobileAutoplayBlocked = true;
            this.emit('mobile_autoplay_blocked', { error: err });
          }
        }
        return;
      }
      this._mobileTransportPendingUntil = 0;
      // 라디오는 HLS → 안드로이드 직생 불가. 서버 프록시(연속 MP3, same-origin) 사용.
      // 식별자는 _playMobileStream 내부에서 _stopMobileAudio 직후 복원(opts.radioId).
      this._playMobileStream(this._radioMobileStreamUrl(state.radio_station_id), {
        source: 'radio',
        radioId: state.radio_station_id,
      }).catch(console.error);
      return;
    }
    if (state.source === 'library' && state.track_id) {
      if (this._mobileTrackId === state.track_id && this.mobileAudio) {
        if (this._mobileTransportBlocked()) {
          return;
        }
        if (this._mobileAutoplayBlocked) {
          return;
        }
        if (this.mobileAudio.paused) {
          try {
            await this.mobileAudio.play();
          } catch (err) {
            this._mobileAutoplayBlocked = true;
            this.emit('mobile_autoplay_blocked', { error: err });
          }
        }
        return;
      }
      this._mobileStreamKey = null;
      this._mobileTrackId = state.track_id;
      this._mobileRadioId = null;
      this._mobileTransportPendingUntil = 0;
      this._playMobileTrack(state.track_id).catch(console.error);
      return;
    }
    if ((state.source === 'spotify' || state.source === 'tidal') && state.stream_id) {
      const key = `${state.source}:${state.stream_id}`;
      if (this._mobileStreamKey === key && this.mobileAudio) {
        if (this._mobileTransportBlocked()) {
          return;
        }
        if (this._mobileAutoplayBlocked) {
          return;
        }
        if (this.mobileAudio.paused) {
          try {
            await this.mobileAudio.play();
          } catch (err) {
            this._mobileAutoplayBlocked = true;
            this.emit('mobile_autoplay_blocked', { error: err });
          }
        }
        return;
      }
      this._mobileTrackId = null;
      this._mobileRadioId = null;
      this._mobileTransportPendingUntil = 0;
      this._playMobileStreaming(state.source, state.stream_id).catch(console.error);
    }
  }

  isMobileOutput() {
    return this.outputMode === 'mobile';
  }

  isServerOutput() {
    return this.outputMode !== 'mobile';
  }

  async setOutputMode(mode) {
    const next = mode === 'mobile' ? 'mobile' : 'server';
    // 전환 진행 중 재진입 차단 — 빠른 토글로 서버·모바일이 겹쳐 재생되는 중복음 방지
    if (this._outputHandoffLock) return this.outputMode;
    if (next === this.outputMode) return next;
    const prev = this.outputMode;
    // 전환 전 재생 상태/소스 스냅샷 — 아래에서 서버 stop 을 보내면 state 가 playing=false 로
    // 갱신되어 _restartPlaybackForOutput 이 "재생 중 아님"으로 오판하고 새 출력 재생을 건너뛴다.
    const resumeSnap = { ...(this.stateCache || {}) };
    // 직전 출력의 실제 재생 여부를 함께 기록 — stateCache.playing 만으로는 반복 전환 시
    // (서버 재생 확인 전 전환 등) false 로 잘못 보여 두 번째부터 무음이 되는 문제 방지.
    resumeSnap.playing =
      !!resumeSnap.playing ||
      (prev === 'server' ? !!this._serverPlaying : !!(this.mobileAudio && !this.mobileAudio.paused));
    // 사용자가 의도적으로 전환했으므로 직전의 일시 차단/대기 플래그는 초기화한다.
    this._mobileAutoplayBlocked = false;
    this._mobileTransportPendingUntil = 0;

    this._outputHandoffLock = true;
    try {
      // 전환 시작 알림 — 리스너 예외가 lock 을 고착시키지 않도록 try 안에서 emit
      this.emit('output_transition', { state: 'start', from: prev, to: next });
      // 1) 이전 출력 경로를 확실히 정지 (겹침 방지)
      if (prev === 'mobile') {
        this._stopMobileAudio();
        this._clearMobileClaim();
      }
      // 서버 스피커는 별도 존이다. 모바일로 전환해도 다른 사용자가 듣는
      // 서버 재생을 끄지 않는다.

      // 2) 새 출력 모드 적용
      this.outputMode = next;
      try {
        localStorage.setItem('whick_remote_output', next);
      } catch {
        /* ignore */
      }
      this.emit('output_mode', { mode: next });

      // 3) 선택한 존의 현재 상태를 요청 — 크로스존 복제 없음
      if (next === 'mobile') {
        void this._pullMobileState();
        this._mobileHandoffGraceUntil = Date.now() + 2500;
      } else {
        this._clearMobileClaim();
        void this._pullStateFromServer();
      }
    } finally {
      this._outputHandoffLock = false;
      this.emit('output_transition', { state: 'end', from: prev, to: this.outputMode });
    }
    return next;
  }

  /**
   * 서버(MPD/CamillaDSP) 재생이 멈출 때까지 대기 — 출력 전환 중 겹침 방지.
   * `_serverPlaying` 이 false 로 보여도(낙관적 toggle 등으로 desync 가능) 방금 보낸
   * stop 이 DAC까지 반영되도록 최소 floor 시간만큼은 항상 대기한다.
   */
  _waitServerStopped(timeoutMs = 2000, floorMs = 250) {
    return new Promise((resolve) => {
      let done = false;
      let off = null;
      let timer = null;
      const finish = () => {
        if (done) return;
        done = true;
        if (off) off();
        if (timer) clearTimeout(timer);
        resolve();
      };
      if (!this._serverPlaying) {
        timer = setTimeout(finish, Math.max(0, floorMs));
        return;
      }
      off = this.on('state', (s) => {
        if (!s || s.playing === false) finish();
      });
      timer = setTimeout(finish, Math.max(floorMs, timeoutMs));
    });
  }

  /** 서버(미니PC) 재생이 실제로 시작될 때까지 대기 — 전환 안내 종료 타이밍 정확화 */
  _waitServerPlaying(timeoutMs = 4000) {
    if (this._serverPlaying) return Promise.resolve();
    return new Promise((resolve) => {
      let done = false;
      let off = null;
      const finish = () => {
        if (done) return;
        done = true;
        if (off) off();
        clearTimeout(timer);
        resolve();
      };
      off = this.on('state', (s) => {
        if (s && s.playing === true) finish();
      });
      const timer = setTimeout(finish, Math.max(200, timeoutMs));
    });
  }

  _stopMobileAudio() {
    this._stopMobileSpectrum();
    if (this.mobileAudio) {
      try {
        this.mobileAudio.pause();
        this.mobileAudio.removeAttribute('src');
        this.mobileAudio.load();
      } catch {
        /* ignore */
      }
      this.mobileAudio.onended = null;
      this.mobileAudio.ontimeupdate = null;
      this.mobileAudio = null;
    }
    this._mobileTrackId = null;
    this._mobileRadioId = null;
    this._mobileStreamKey = null;
    this._mobileAutoplayBlocked = false;
    this._mobileIsPreview = false;
  }

  _waitForCanPlay(audio, timeoutMs = 8000) {
    if (audio.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) return Promise.resolve();
    if (audio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        audio.removeEventListener('canplay', done);
        clearTimeout(timer);
        resolve();
      };
      audio.addEventListener('canplay', done, { once: true });
      const timer = setTimeout(done, timeoutMs);
    });
  }

  _stopMobileSpectrumLoop() {
    if (this._mobileSpectrumTimer) {
      clearInterval(this._mobileSpectrumTimer);
      this._mobileSpectrumTimer = null;
    }
  }

  _stopMobileSpectrum() {
    this._stopMobileSpectrumLoop();
    // Web Audio 그래프 노드를 끊어 이전 오디오 소스가 남아 겹쳐 들리지 않도록 한다.
    try {
      this._mobileSpectrumSource?.disconnect();
    } catch {
      /* ignore */
    }
    try {
      this._mobileAnalyser?.disconnect();
    } catch {
      /* ignore */
    }
    this._mobileAnalyser = null;
    this._mobileSpectrumSource = null;
    if (this._mobileSpectrumSmooth) {
      this._mobileSpectrumSmooth = this._mobileSpectrumSmooth.map(() => 0);
    }
  }

  _logBandFreqs(count = 24, fmin = 80, fmax = 12000) {
    if (count <= 1) return [fmin];
    const ratio = fmax / fmin;
    return Array.from({ length: count }, (_, i) => fmin * ratio ** (i / (count - 1)));
  }

  _analyzeMobileBands() {
    const analyser = this._mobileAnalyser;
    const ctx = this._mobileAudioCtx;
    const bandCount = 24;
    if (!analyser || !ctx) {
      return this._mobileSpectrumSmooth || new Array(bandCount).fill(0);
    }
    if (!this._mobileSpectrumSmooth) {
      this._mobileSpectrumSmooth = new Array(bandCount).fill(0);
    }
    const binCount = analyser.frequencyBinCount;
    const floatData = new Float32Array(binCount);
    analyser.getFloatFrequencyData(floatData);
    const nyquist = ctx.sampleRate / 2;
    const fmax = Math.min(12000, nyquist * 0.95);
    const freqs = this._logBandFreqs(bandCount, 80, fmax);
    const raw = freqs.map((freq) => {
      const bin = Math.min(binCount - 1, Math.round((freq / nyquist) * binCount));
      const db = floatData[bin];
      if (!Number.isFinite(db) || db <= -100) return 0;
      return 10 ** (db / 20);
    });
    const peak = Math.max(...raw, 1e-5);
    const norm = 1 / peak;
    const attack = 0.55;
    const release = 0.12;
    const out = raw.map((val, i) => {
      const target = Math.min(1, Math.max(0, val * norm * 1.15));
      const prev = this._mobileSpectrumSmooth[i] || 0;
      const alpha = target > prev ? attack : release;
      return prev + (target - prev) * alpha;
    });
    this._mobileSpectrumSmooth = out;
    return out;
  }

  _mobileSpectrumTick() {
    if (!this.isMobileOutput() || !this._mobileAnalyser) {
      this._stopMobileSpectrumLoop();
      return;
    }
    const audio = this.mobileAudio;
    if (!audio || audio.paused || audio.ended) {
      if (this._mobileSpectrumSmooth?.some((v) => v > 0.01)) {
        this._mobileSpectrumSmooth = this._mobileSpectrumSmooth.map((v) => v * 0.7);
        this.emit('spectrum', {
          event: 'spectrum',
          source: 'mobile-client',
          playing: false,
          bands: [...this._mobileSpectrumSmooth],
        });
      }
      return;
    }
    const bands = this._analyzeMobileBands();
    this.emit('spectrum', {
      event: 'spectrum',
      source: 'mobile-client',
      playing: true,
      bands,
      band_count: bands.length,
    });
  }

  _startMobileSpectrumLoop() {
    this._stopMobileSpectrumLoop();
    this._mobileSpectrumTimer = setInterval(() => this._mobileSpectrumTick(), 1000 / 15);
  }

  _attachMobileSpectrum(audio) {
    this._stopMobileSpectrum();
    if (typeof window === 'undefined') return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    if (!this._mobileAudioCtx) {
      this._mobileAudioCtx = new AudioCtx();
    }
    const ctx = this._mobileAudioCtx;
    try {
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.5;
      const source = ctx.createMediaElementSource(audio);
      source.connect(analyser);
      analyser.connect(ctx.destination);
      this._mobileAnalyser = analyser;
      this._mobileSpectrumSource = source;
      if (!this._mobileSpectrumSmooth) {
        this._mobileSpectrumSmooth = new Array(24).fill(0);
      }
      void ctx.resume();
      this._startMobileSpectrumLoop();
    } catch (err) {
      console.warn('[WhickAPI] mobile spectrum unavailable', err);
      this._mobileAnalyser = null;
      this._mobileSpectrumSource = null;
    }
  }

  _notifyMobilePlaybackError(err, context = {}) {
    const msg = err?.message || String(err || 'playback failed');
    this.emit('mobile_playback_error', { message: msg, ...context });
  }

  async _playMobileStreaming(provider, streamId) {
    try {
      const data = await this._get('/api/streaming/playback-url', {
        provider,
        stream_id: streamId,
      });
      if (!data.url) {
        throw new Error(data.error || 'playback url unavailable');
      }
      const key = `${provider}:${streamId}`;
      this._mobileIsPreview = !!data.preview;
      await this._playMobileStream(data.url, {
        source: provider,
        preview: !!data.preview,
        streamKey: key,
      });
    } catch (err) {
      this._notifyMobilePlaybackError(err, { provider, streamId });
      throw err;
    }
  }

  async _playMobileFromNowPlaying(snapshot = null) {
    const s = snapshot || this.stateCache || {};
    if (!s.playing) return;
    if (s.source === 'radio' && s.radio_station_id) {
      await this._playMobileStream(this._radioMobileStreamUrl(s.radio_station_id), {
        source: 'radio',
        radioId: s.radio_station_id,
      });
      return;
    }
    if (s.source === 'library' && s.track_id) {
      await this._playMobileTrack(s.track_id);
      return;
    }
    if ((s.source === 'spotify' || s.source === 'tidal') && s.stream_id) {
      await this._playMobileStreaming(s.source, s.stream_id);
    }
  }

  _trackStreamUrl(trackId) {
    return this._authenticatedUrl(`/api/tracks/${encodeURIComponent(trackId)}/stream`);
  }

  _radioMobileStreamUrl(stationId) {
    // 서버 프록시(연속 MP3, same-origin). 안드로이드 HLS 미지원 우회.
    // 터널 개통 후 player auth 필수 → ?token= 필요 (audio 엘리먼트는 Bearer 불가)
    return this._authenticatedUrl(
      `/api/radio/${encodeURIComponent(stationId)}/mobile-stream`,
    );
  }

  _isSameOriginStreamUrl(url) {
    try {
      const u = new URL(url, this.baseURL);
      const base = new URL(this.baseURL);
      return u.origin === base.origin;
    } catch {
      return false;
    }
  }

  async _playMobileStream(url, opts = {}) {
    this._stopMobileAudio();
    // 식별자는 _stopMobileAudio() 가 null 로 지운 직후 원자적으로 복원해야 한다.
    // (호출 전에 세팅하면 _stopMobileAudio 가 지워, 다음 state 동기화가 "다른 소스"로 오판→재생성→끊김)
    if (opts.radioId != null) this._mobileRadioId = opts.radioId;
    if (opts.trackId != null) this._mobileTrackId = opts.trackId;
    if (opts.streamKey != null) this._mobileStreamKey = opts.streamKey;
    const playUrl = this._isSameOriginStreamUrl(url) ? this._authenticatedUrl(url) : url;
    const sourceKind = opts.source || this.stateCache.source || 'library';
    const sameOrigin = this._isSameOriginStreamUrl(playUrl);
    // 라이브 라디오(서버 프록시 포함)는 Web Audio 우회. createMediaElementSource로
    // 라우팅하면 모바일 AudioContext가 제스처 밖에서 resume되지 않아 suspended → 무음.
    // 외부 라디오는 CORS도 없어 crossOrigin 설정 시 재생 실패. 직접 element 출력 유지.
    const useWebAudio = sameOrigin && sourceKind !== 'radio';
    const audio = new Audio();
    if (sourceKind === 'radio') {
      audio.preload = 'auto';
    }
    if (useWebAudio) {
      audio.crossOrigin = 'anonymous';
    }
    audio.src = playUrl;
    this.mobileAudio = audio;
    if (useWebAudio) {
      this._attachMobileSpectrum(audio);
    } else {
      this._stopMobileSpectrum();
    }
    audio.addEventListener('timeupdate', () => {
      if (!this.mobileAudio || this.mobileAudio !== audio) return;
      const position = Math.floor(audio.currentTime || 0);
      let duration = Math.floor(audio.duration || this.stateCache.duration || 0);
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        duration = Math.floor(audio.duration);
      }
      const playing = !audio.paused && !audio.ended;
      const patch = { ...this.stateCache, position, duration };
      if (this.outputMode !== 'mobile') {
        patch.playing = playing;
      }
      this.stateCache = patch;
      this.emit('state', patch);
    });
    audio.addEventListener('ended', () => {
      if (this.outputMode !== 'mobile') return;
      if (sourceKind === 'library' || sourceKind === 'spotify' || sourceKind === 'tidal') {
        this.next();
      }
    });
    audio.addEventListener('volumechange', () => {
      if (this.outputMode !== 'mobile' || this.mobileAudio !== audio) return;
      const vol = Math.max(0, Math.min(100, Math.round(audio.volume * 100)));
      this.stateCache = { ...this.stateCache, volume: vol };
      this.emit('state', this.stateCache);
    });
    // 라이브 라디오 스트림(FLAC 등)은 canplay까지 대기 후 5초 추가 버퍼링으로 언더런 방지
    if (sourceKind === 'radio') {
      await this._waitForCanPlay(audio, 8000);
      await new Promise(r => setTimeout(r, 500));
    }
    try {
      await audio.play();
      this._mobileAutoplayBlocked = false;
      this.emit('mobile_autoplay_resumed');
    } catch (err) {
      this._mobileAutoplayBlocked = true;
      this.emit('mobile_autoplay_blocked', { url, error: err });
      throw err;
    }
  }

  async _playMobileTrack(trackId) {
    await this._playMobileStream(this._trackStreamUrl(trackId), {
      source: 'library',
      trackId,
    });
  }

  async _restartPlaybackForOutput(snapshot = null) {
    // 전환 전 스냅샷 우선 — 서버 stop 으로 stateCache.playing 이 false 가 되어도 복구되도록.
    const s = snapshot || this.stateCache || {};
    if (!s.playing) return;
    if (this.outputMode === 'mobile') {
      if (s.source === 'library' && s.track_id) {
        this._send({ cmd: 'play', track_id: s.track_id });
      } else if (s.source === 'radio' && s.radio_station_id) {
        this._send({ cmd: 'play_radio', station_id: s.radio_station_id });
      } else if ((s.source === 'spotify' || s.source === 'tidal') && s.stream_id) {
        this._send({
          cmd: 'play_streaming',
          provider: s.source,
          stream_id: s.stream_id,
          meta: { title: s.title, artist: s.artist, album: s.album, duration_sec: s.duration },
        });
      }
      await this._playMobileFromNowPlaying(s);
      return;
    }
    this._stopMobileAudio();
    if (s.source === 'radio' && s.radio_station_id) {
      this._send({ cmd: 'play_radio', station_id: s.radio_station_id });
    } else if (s.source === 'spotify' || s.source === 'tidal') {
      if (s.stream_id) {
        this._send({
          cmd: 'play_streaming',
          provider: s.source,
          stream_id: s.stream_id,
          meta: { title: s.title, artist: s.artist, album: s.album, duration_sec: s.duration },
        });
      }
    } else if (s.track_id) {
      this._send({ cmd: 'play', track_id: s.track_id });
    }
  }

  play(trackId = null) {
    const context = this._playContextPayload();
    if (this.isMobileOutput()) {
      this._stopMobileAudio();
      if (trackId != null) {
        this._claimMobileSession(`library:${trackId}`);
        this._send({ cmd: 'play', track_id: trackId, context });
        this._playMobileTrack(trackId).catch(console.error);
        return true;
      }
    } else {
      this._stopMobileAudio();
      this._clearMobileClaim();
    }
    return this._send(
      trackId != null ? { cmd: 'play', track_id: trackId, context } : { cmd: 'play', context },
    );
  }

  playQueue(trackIds, startTrackId = null) {
    const ids = (trackIds || []).map((id) => Number(id)).filter((id) => id > 0);
    if (!ids.length) return false;
    const startId = startTrackId != null ? Number(startTrackId) : ids[0];
    const index = Math.max(0, ids.indexOf(startId));
    const context = this._playContextPayload();
    if (this.isMobileOutput()) {
      this._stopMobileAudio();
      this._claimMobileSession(`library:${startId}`);
      this._send({ cmd: 'play_queue', track_ids: ids, index, context });
      this._playMobileTrack(startId).catch(console.error);
      return true;
    }
    this._stopMobileAudio();
    this._clearMobileClaim();
    return this._send({ cmd: 'play_queue', track_ids: ids, index, context });
  }

  setQueue(trackIds) {
    const ids = [...new Set((trackIds || []).map((id) => Number(id)).filter((id) => id > 0))];
    return this._send({ cmd: 'set_queue', track_ids: ids });
  }

  playAlbum(album, artist = null) {
    this._stopMobileAudio();
    return this._send({ cmd: 'play_album', album, artist, context: this._playContextPayload() });
  }

  _playContextPayload() {
    try {
      const ctx =
        typeof window !== 'undefined' && typeof window.aiContext === 'function'
          ? window.aiContext()
          : null;
      if (!ctx) return {};
      return {
        weather: ctx.weather || '',
        period: ctx.period || '',
        mood: ctx.mood || '',
        location_label: ctx.locationLabel || ctx.city || '',
      };
    } catch {
      return {};
    }
  }

  stop() {
    this._stopMobileAudio();
    this._clearMobileClaim();
    return this._send({ cmd: 'stop' });
  }

  pause() {
    if (this.isMobileOutput() && this.mobileAudio) {
      this.mobileAudio.pause();
    }
    return this._send({ cmd: 'pause' });
  }

  resumeMobilePlayback() {
    if (!this.isMobileOutput()) return Promise.resolve(false);
    if (this._mobileTransportBlocked()) return Promise.resolve(false);
    // 사용자 제스처 안에서 AudioContext를 resume해야 Web Audio(라이브러리·스트리밍) 출력이 살아난다.
    try {
      this._mobileAudioCtx?.resume();
    } catch {
      /* ignore */
    }
    if (this.mobileAudio) {
      return this.mobileAudio
        .play()
        .then(() => {
          this._mobileAutoplayBlocked = false;
          this.emit('mobile_autoplay_resumed');
          return true;
        })
        .catch((err) => {
          this._mobileAutoplayBlocked = true;
          this.emit('mobile_autoplay_blocked', { error: err });
          return false;
        });
    }
    return this._syncMobilePlaybackFromState(this.stateCache)
      .then(() => {
        const ok = !!(this.mobileAudio && !this.mobileAudio.paused);
        this._mobileAutoplayBlocked = !ok;
        this.emit(ok ? 'mobile_autoplay_resumed' : 'mobile_autoplay_blocked', {});
        return ok;
      })
      .catch((err) => {
        this._mobileAutoplayBlocked = true;
        this.emit('mobile_autoplay_blocked', { error: err });
        return false;
      });
  }

  toggle() {
    if (this.isMobileOutput()) {
      const mobilePlaying = !!(this.mobileAudio && !this.mobileAudio.paused);
      if (mobilePlaying) {
        this.mobileAudio.pause();
      } else if (this.mobileAudio) {
        this.mobileAudio
          .play()
          .then(() => {
            this._mobileAutoplayBlocked = false;
            this.emit('mobile_autoplay_resumed');
          })
          .catch((err) => {
            this._mobileAutoplayBlocked = true;
            this.emit('mobile_autoplay_blocked', { error: err });
          });
      } else if (this._mobileAutoplayBlocked) {
        void this._syncMobilePlaybackFromState(this.stateCache);
      }
      return this._send({ cmd: 'toggle' });
    }
    const sent = this._send({ cmd: 'toggle' });
    if (sent) {
      this._serverPlaying = !this._serverPlaying;
    }
    return sent;
  }

  next() {
    if (this.isMobileOutput()) {
      this._beginMobileTransportGuard();
      this._stopMobileAudio();
      this._mobileClaimedKey = null;
      this._mobileAwaitingOwnTransport = true;
    }
    return this._send({ cmd: 'next' });
  }

  prev() {
    if (this.isMobileOutput()) {
      this._beginMobileTransportGuard();
      this._stopMobileAudio();
      this._mobileClaimedKey = null;
      this._mobileAwaitingOwnTransport = true;
    }
    return this._send({ cmd: 'prev' });
  }

  seek(positionSeconds) {
    if (this.isMobileOutput() && this.mobileAudio) {
      try {
        this.mobileAudio.currentTime = Math.max(0, Number(positionSeconds) || 0);
      } catch {
        /* ignore */
      }
    }
    return this._send({ cmd: 'seek', position: Math.round(positionSeconds) });
  }

  setVolume(value, opts = {}) {
    const vol = Math.max(0, Math.min(100, Math.round(value)));
    const { optimistic = true, force = false } = opts;
    if (!force && this._lastVolumeSent === vol) {
      return true;
    }
    this._lastVolumeSent = vol;
    // 연속 volume 명령의 지연 broadcast 가 막대를 흔들지 않도록 잠시 서버 volume 반영 보류
    this._volumeHoldUntil = Date.now() + 650;
    if (this.isMobileOutput() && this.mobileAudio) {
      this.mobileAudio.volume = vol / 100;
    }
    if (optimistic) {
      this.stateCache = { ...(this.stateCache || {}), volume: vol };
      this.emit('state', this.stateCache);
    }
    return this._send({ cmd: 'volume', value: vol });
  }

  async getPlaybackNow() {
    return this._get('/api/playback/now');
  }

  setShuffle(value) {
    return this._send({ cmd: 'shuffle', value: !!value });
  }

  setRepeat(value) {
    return this._send({ cmd: 'repeat', value });
  }

  toggleRepeat() {
    return this._send({ cmd: 'repeat', value: 'toggle' });
  }

  addToQueue(trackId) {
    return this._send({ cmd: 'add_to_queue', track_id: trackId });
  }

  async _get(path, params = {}) {
    const url = new URL(this.baseURL + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    let resp;
    try {
      resp = await fetch(url.toString(), { headers: this._authHeaders() });
    } catch (cause) {
      const err = new Error(_t('err.network', '네트워크 연결을 확인해 주세요.'));
      err.code = 'NETWORK_ERROR';
      err.cause = cause;
      throw err;
    }
    if (!resp.ok) throw new Error(`${resp.status} ${path}`);
    return resp.json();
  }

  async _post(path, body = null) {
    let resp;
    try {
      const init = {
        method: 'POST',
        headers: this._authHeaders(
          body != null ? { 'Content-Type': 'application/json' } : {},
        ),
      };
      if (body != null) init.body = JSON.stringify(body);
      resp = await fetch(this.baseURL + path, init);
    } catch (cause) {
      const err = new Error(_t('err.network', '네트워크 연결을 확인해 주세요.'));
      err.code = 'NETWORK_ERROR';
      err.cause = cause;
      throw err;
    }
    if (!resp.ok) throw new Error(`${resp.status} ${path}`);
    const text = await resp.text();
    if (!text) return { ok: true };
    try {
      return JSON.parse(text);
    } catch {
      return { ok: true, raw: text };
    }
  }

  async getTracks(page = 1, sort = 'title', perPage = 20) {
    return this._get('/api/tracks', { page, sort, per_page: perPage });
  }

  async getArtists() {
    return this._get('/api/artists');
  }

  async getAlbums() {
    return this._get('/api/albums');
  }

  async getArtistTracks(artist) {
    return this._get(`/api/artists/${encodeURIComponent(artist)}/tracks`);
  }

  async getAlbumTracks(album) {
    return this._get(`/api/albums/${encodeURIComponent(album)}/tracks`);
  }

  async getComposers() {
    return this._get('/api/composers');
  }

  async getComposerTracks(composer) {
    return this._get(`/api/composers/${encodeURIComponent(composer)}/tracks`);
  }

  async getGenres() {
    return this._get('/api/genres');
  }

  async getGenreTracks(genre) {
    return this._get(`/api/genres/${encodeURIComponent(genre)}/tracks`);
  }

  async getFavorites() {
    return this._get('/api/favorites');
  }

  async addFavorite(trackId) {
    const resp = await fetch(`${this.baseURL}/api/favorites/${encodeURIComponent(trackId)}`, {
      method: 'POST',
      headers: this._authHeaders(),
    });
    if (!resp.ok) throw new Error(`${resp.status} add favorite`);
    return resp.json();
  }

  async removeFavorite(trackId) {
    const resp = await fetch(`${this.baseURL}/api/favorites/${encodeURIComponent(trackId)}`, {
      method: 'DELETE',
      headers: this._authHeaders(),
    });
    if (!resp.ok) throw new Error(`${resp.status} remove favorite`);
    return resp.json();
  }

  async getHistory(limit = 50) {
    return this._get('/api/history', { limit });
  }

  async search(query) {
    return this._get('/api/search', { q: query });
  }

  async getDashboard() {
    return this._get('/api/dashboard');
  }

  async getSystemStatus() {
    return this._get('/api/system/status');
  }

  async getUsbPending() {
    return this._get('/api/library/usb-pending');
  }

  async fsBrowse(root, path = '') {
    const q = `?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path || '')}`;
    return this._get(`/api/library/fs/browse${q}`);
  }

  async fsMkdir(root, path, name) {
    const resp = await fetch(`${this.baseURL}/api/library/fs/mkdir`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ root, path, name }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'mkdir'));
    return resp.json();
  }

  async fsRename(root, path, newName) {
    const resp = await fetch(`${this.baseURL}/api/library/fs/rename`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ root, path, new_name: newName }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'rename'));
    return resp.json();
  }

  async fsDelete(root, paths) {
    const resp = await fetch(`${this.baseURL}/api/library/fs/delete`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ root, paths }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'delete'));
    return resp.json();
  }

  async deleteLibraryTracks(trackIds) {
    /** 라이브러리 = 바로가기(목록). 실제 파일 삭제는 설정→파일 탐색기만. */
    const ids = [...new Set((trackIds || []).map((x) => Number(x)).filter((n) => n > 0))];
    if (!ids.length) throw new Error('track_ids required');
    const resp = await fetch(`${this.baseURL}/api/library/tracks/delete`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ track_ids: ids, delete_files: false }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'tracks/delete'));
    return resp.json();
  }

  async fsPreflight(sources, destRoot, destPath) {
    const resp = await fetch(`${this.baseURL}/api/library/fs/preflight`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ sources, dest_root: destRoot, dest_path: destPath }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'preflight'));
    return resp.json();
  }

  async fsCopy(sources, destRoot, destPath, move = false) {
    const resp = await fetch(`${this.baseURL}/api/library/fs/copy`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ sources, dest_root: destRoot, dest_path: destPath, move: !!move }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'copy'));
    return resp.json();
  }

  async fsRegister(root, paths, audit = false) {
    const resp = await fetch(`${this.baseURL}/api/library/fs/register`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ root, paths, audit }),
    });
    if (!resp.ok) throw new Error(await this._errText(resp, 'register'));
    return resp.json();
  }

  async _errText(resp, fallback) {
    try {
      const j = await resp.json();
      return j.detail || j.message || `${resp.status} ${fallback}`;
    } catch {
      return `${resp.status} ${fallback}`;
    }
  }

  async scanExternalMount(mountPoint) {
    const q = mountPoint ? `?mount_point=${encodeURIComponent(mountPoint)}` : '';
    return this._get(`/api/library/external/scan${q}`);
  }

  async processExternalLibrary({ mountPoint, mode = 'manual', paths = [], importRejected = [] }) {
    const resp = await fetch(`${this.baseURL}/api/library/external/process`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        mount_point: mountPoint,
        mode,
        paths,
        import_rejected: importRejected,
      }),
    });
    if (!resp.ok) throw new Error(`${resp.status} external-process`);
    return resp.json();
  }

  async importUsbLibrary(mountPoint, opts = {}) {
    const resp = await fetch(`${this.baseURL}/api/library/usb-import`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ mount_point: mountPoint || '' }),
    });
    if (!resp.ok) throw new Error(`${resp.status} usb-import`);
    return resp.json();
  }

  async dismissUsbPrompt(mountPoint) {
    const resp = await fetch(`${this.baseURL}/api/library/usb-dismiss`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ mount_point: mountPoint || '' }),
    });
    if (!resp.ok) throw new Error(`${resp.status} usb-dismiss`);
    return resp.json();
  }

  async getPlaylists() {
    return this._get('/api/playlists');
  }

  async getPlaylistTracks(playlistId) {
    return this._get(`/api/playlists/${playlistId}/tracks`);
  }

  async createPlaylist(name) {
    const resp = await fetch(`${this.baseURL}/api/playlists`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ name }),
    });
    if (!resp.ok) throw new Error(`${resp.status} playlists`);
    return resp.json();
  }

  async addToPlaylist(playlistId, trackId) {
    const resp = await fetch(`${this.baseURL}/api/playlists/${playlistId}/tracks`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ track_id: trackId }),
    });
    if (!resp.ok) throw new Error(`${resp.status} playlist track`);
    return resp.json();
  }

  async removeFromPlaylist(playlistId, trackId) {
    const resp = await fetch(`${this.baseURL}/api/playlists/${playlistId}/tracks/${trackId}`, {
      method: 'DELETE',
      headers: this._authHeaders(),
    });
    if (!resp.ok) throw new Error(`${resp.status} remove playlist track`);
    return resp.json();
  }

  async deletePlaylist(playlistId) {
    const resp = await fetch(`${this.baseURL}/api/playlists/${playlistId}`, {
      method: 'DELETE',
      headers: this._authHeaders(),
    });
    if (!resp.ok) throw new Error(`${resp.status} delete playlist`);
    return resp.json();
  }

  async getIncomingAudit() {
    return this._get('/api/library/incoming-audit');
  }

  async importIncomingApproved(approvedPaths) {
    const resp = await fetch(`${this.baseURL}/api/library/import-incoming`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ user_approved: true, approved_paths: approvedPaths }),
    });
    if (!resp.ok) throw new Error(`${resp.status} import-incoming`);
    return resp.json();
  }

  async deleteIncomingRejected(paths) {
    const resp = await fetch(`${this.baseURL}/api/library/delete-incoming`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ user_approved: true, paths }),
    });
    if (!resp.ok) throw new Error(`${resp.status} delete-incoming`);
    return resp.json();
  }

  async getLibraryStatus() {
    return this._get('/api/library/status');
  }

  async getStreamingStatus() {
    const resp = await fetch(`${this.baseURL}/api/streaming/status`, {
      headers: this._authHeaders(),
    });
    if (!resp.ok) {
      const err = new Error(`${resp.status} streaming/status`);
      err.status = resp.status;
      throw err;
    }
    return resp.json();
  }

  async startSpotifyConnect() {
    const resp = await fetch(`${this.baseURL}/api/streaming/spotify/connect/start`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
    });
    if (!resp.ok) throw new Error(`${resp.status} spotify/start`);
    return resp.json();
  }

  async completeSpotifyConnect() {
    const resp = await fetch(`${this.baseURL}/api/streaming/spotify/connect/complete`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
    });
    if (!resp.ok) throw new Error(`${resp.status} spotify/complete`);
    return resp.json();
  }

  async disconnectSpotify() {
    const resp = await fetch(`${this.baseURL}/api/streaming/spotify/disconnect`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
    });
    if (!resp.ok) throw new Error(`${resp.status} spotify/disconnect`);
    return resp.json();
  }

  async getSpotifyOAuthStatus() {
    return this._get('/api/streaming/spotify/oauth/status');
  }

  async startSpotifyOAuth() {
    const resp = await fetch(`${this.baseURL}/api/streaming/spotify/oauth/start`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
    });
    if (!resp.ok) throw new Error(`${resp.status} spotify/oauth/start`);
    return resp.json();
  }

  async startTidalConnect() {
    const resp = await fetch(`${this.baseURL}/api/streaming/tidal/connect/start`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
    });
    if (!resp.ok) throw new Error(`${resp.status} tidal/start`);
    return resp.json();
  }

  async pollTidalConnect() {
    return this._get('/api/streaming/tidal/connect/poll');
  }

  async disconnectTidal() {
    const resp = await fetch(`${this.baseURL}/api/streaming/tidal/disconnect`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
    });
    if (!resp.ok) throw new Error(`${resp.status} tidal/disconnect`);
    return resp.json();
  }

  async streamingSearch(query, providers = 'spotify,tidal') {
    return this._get('/api/streaming/search', { q: query, providers });
  }

  async playStreamingTrack(item, queueItems = null) {
    const provider = item.source || item.provider;
    const streamId = item.stream_id;
    const items = queueItems || [item];
    const index = Math.max(
      0,
      items.findIndex((t) => (t.stream_id || t.id) === streamId),
    );
    if (this.isMobileOutput()) {
      this._stopMobileAudio();
      if (provider && streamId) this._claimMobileSession(`${provider}:${streamId}`);
    } else {
      this._clearMobileClaim();
    }
    const sent = this._send({
      cmd: 'play_streaming_queue',
      items,
      index,
    });
    if (this.isMobileOutput() && sent && provider && streamId) {
      this._playMobileStreaming(provider, streamId).catch((err) => {
        console.warn('[WhickAPI] mobile streaming', err);
      });
    }
    return sent;
  }

  async aiSearch(query, opts = {}) {
    const params = { q: query };
    if (opts.local === false) params.local = '0';
    if (opts.spotify === false) params.spotify = '0';
    if (opts.tidal === false) params.tidal = '0';
    return this._get('/api/ai-search', params);
  }

  /** Whick AI 채팅 — 일반 대화 + 라이브러리 도구 */
  async aiChat(message, opts = {}) {
    const msg = String(message || '').trim();
    const history = Array.isArray(opts.history) ? opts.history : [];
    const userName = String(opts.userName || opts.user_name || '').trim();
    if (history.length) {
      const body = { message: msg, history };
      if (userName) body.user_name = userName;
      return this._post('/api/ai-chat', body);
    }
    const params = { q: msg };
    if (userName) params.user_name = userName;
    return this._get('/api/ai-chat', params);
  }

  async getState() {
    return this._get('/api/state');
  }

  async getUpdateStatus() {
    return this._get('/api/update/status');
  }

  async prepareUpdate() {
    return this._post('/api/update/prepare', { confirm: true });
  }

  async requestUpdate() {
    return this._post('/api/update/apply', { confirm: true });
  }

  async getOpsConsentPending() {
    return this._get('/api/ops-consent/pending');
  }

  async resolveOpsConsent(id, status = 'resolved') {
    return this._post('/api/ops-consent/resolve', { id, status });
  }

  /**
   * playerToken이 유효한지 확인. 401 발생 시 force refresh 시도.
   * @param {{ force?: boolean }} [opts]
   * @returns {Promise<string|null>}
   */
  async ensurePlayerToken(opts) {
    if (this.playerToken && !opts?.force) return this.playerToken;
    // deviceProfile에서 token 재조회
    try {
      const dp = window.deviceProfile;
      const token = dp?.player_token || dp?.playerToken || null;
      if (token) {
        this.playerToken = token;
        return token;
      }
    } catch (_) { /* ignore */ }
    return this.playerToken;
  }

  async getRadioStations() {
    return this._get('/api/radio');
  }

  async getWeatherContext(opts = {}) {
    // 판매용: 고객 뮤직서버만. 중앙 /api/site/* fallback 금지.
    try {
      const params = {};
      if (opts && opts.lat != null && opts.lon != null) {
        params.lat = opts.lat;
        params.lon = opts.lon;
      }
      return await this._get('/api/weather/context', params);
    } catch {
      return null;
    }
  }

  async getAiRecommend(opts = {}) {
    const params = { limit: opts.limit || 8 };
    if (opts.lang) params.lang = opts.lang;
    else if (window.WhickI18n && typeof window.WhickI18n.getLang === 'function') params.lang = window.WhickI18n.getLang();
    if (opts.weather) params.weather = opts.weather;
    if (opts.period) params.period = opts.period;
    if (opts.mood) params.mood = opts.mood;
    if (opts.location_label) params.location_label = opts.location_label;
    return this._get('/api/ai-recommend', params);
  }

  async getDspProfile() {
    return this._get('/api/dsp/profile');
  }

  async getDspPresets() {
    return this._get('/api/dsp/presets');
  }

  async saveDspProfile(dsp) {
    const resp = await fetch(`${this.baseURL}/api/dsp/profile`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ dsp }),
    });
    if (!resp.ok) throw new Error(`${resp.status} dsp profile`);
    return resp.json();
  }

  async saveUserEq({ eqEnabled, gains, balanceDb, masterGainDb, enabled } = {}) {
    const body = {};
    if (eqEnabled != null) body.eqEnabled = !!eqEnabled;
    if (Array.isArray(gains)) body.gains = gains;
    if (balanceDb) body.balanceDb = balanceDb;
    if (masterGainDb != null) body.masterGainDb = Number(masterGainDb) || 0;
    if (enabled != null) body.enabled = !!enabled;
    const resp = await fetch(`${this.baseURL}/api/dsp/eq`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    if (resp.ok) return resp.json();
    if (resp.status !== 404) throw new Error(`${resp.status} dsp eq`);
    // 구버전 플레이어: /api/dsp/profile 로 폴백
    const prof = await this.getDspProfile();
    const dsp = { ...(prof.dsp || {}) };
    const room = dsp.roomPeaking || [];
    const userPeaking = WHICK_EQ_BANDS.map((def, i) => ({
      freq: def.freq,
      q: def.q,
      gainDb: Array.isArray(gains) ? Number(gains[i]) || 0 : 0,
    }));
    if (eqEnabled != null) {
      dsp.eqEnabled = !!eqEnabled;
      dsp.peaking = eqEnabled
        ? this._mergePeaking(room, userPeaking)
        : room.length
          ? room
          : userPeaking.map((b) => ({ ...b, gainDb: 0 }));
    }
    if (Array.isArray(gains)) dsp.userPeaking = userPeaking;
    if (balanceDb) dsp.balanceDb = balanceDb;
    if (masterGainDb != null) dsp.masterGainDb = Math.max(-12, Math.min(12, Number(masterGainDb) || 0));
    if (enabled != null) dsp.enabled = !!enabled;
    dsp.source = 'user-eq';
    return this.saveDspProfile(dsp);
  }

  _mergePeaking(room, user) {
    const merged = {};
    [...(room || []), ...(user || [])].forEach((band) => {
      const freq = Number(band.freq) || 0;
      if (freq <= 0) return;
      if (!merged[freq]) merged[freq] = { freq, q: Number(band.q) || 1, gainDb: 0 };
      merged[freq].gainDb = Math.max(-9, Math.min(9, merged[freq].gainDb + (Number(band.gainDb) || 0)));
    });
    return Object.values(merged).sort((a, b) => a.freq - b.freq);
  }

  /** 구조 변경(DAC 전처리·pipe rate 등) 후 재생 재동기화. EQ/밸런스 필터만은 Camilla WS hot apply — 곡 재시작 금지. */
  async replayForDspApply() {
    const s = this.stateCache || {};
    if (!s.playing || this.isMobileOutput()) return;
    const pos = Math.max(0, Number(s.position) || 0);
    this._stopMobileAudio();
    if (s.source === 'radio' && s.radio_station_id) {
      this._send({ cmd: 'play_radio', station_id: s.radio_station_id });
      return;
    }
    if ((s.source === 'spotify' || s.source === 'tidal') && s.stream_id) {
      this._send({
        cmd: 'play_streaming',
        provider: s.source,
        stream_id: s.stream_id,
        meta: { title: s.title, artist: s.artist, album: s.album, duration_sec: s.duration },
      });
      return;
    }
    if (s.track_id) {
      this._send({ cmd: 'play', track_id: s.track_id });
      if (pos > 2) {
        setTimeout(() => this.seek(pos), 600);
      }
    }
  }

  async saveRoomCorrection(peaking) {
    const resp = await fetch(`${this.baseURL}/api/dsp/room-correction`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ peaking }),
    });
    if (!resp.ok) throw new Error(`${resp.status} room-correction`);
    return resp.json();
  }

  async saveChannelSetup({ swapChannels = false } = {}) {
    const resp = await fetch(`${this.baseURL}/api/dsp/channel-setup`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ swapChannels: !!swapChannels }),
    });
    if (!resp.ok) throw new Error(`${resp.status} channel-setup`);
    return resp.json();
  }

  async saveDacPreprocess(enabled, { osFactor = null, osFactorAuto = null } = {}) {
    const body = { enabled: !!enabled };
    if (osFactorAuto != null) body.dacOsFactorAuto = !!osFactorAuto;
    if (osFactorAuto === false && osFactor != null) body.dacOsFactor = osFactor === 8 ? 8 : 4;
    const resp = await fetch(`${this.baseURL}/api/dsp/dac-preprocess`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`${resp.status} dac-preprocess`);
    const data = await resp.json();
    if (this.stateCache?.playing) await this.replayForDspApply();
    return data;
  }

  async playTestTone(channel, { swapChannels = null } = {}) {
    const ch = channel === 'right' ? 'right' : 'left';
    const body = { channel: ch };
    if (swapChannels != null) body.swapChannels = !!swapChannels;
    const resp = await fetch(`${this.baseURL}/api/spatial/test-tone`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`${resp.status} test-tone`);
    return resp.json();
  }

  playTestToneWs(channel, swapChannels = null) {
    const payload = { cmd: 'spatial_test_tone', channel: channel === 'right' ? 'right' : 'left' };
    if (swapChannels != null) payload.swapChannels = !!swapChannels;
    return this._send(payload);
  }

  spatialSweepStart(pointIndex, pointTotal) {
    return this._send({
      cmd: 'spatial_sweep_start',
      point_index: pointIndex,
      point_total: pointTotal,
    });
  }

  spatialPointDone(completedPoints) {
    return this._send({ cmd: 'spatial_point_done', completed_points: completedPoints });
  }

  spatialReset() {
    return this._send({ cmd: 'spatial_reset' });
  }

  spatialSetPhase(phase) {
    return this._send({ cmd: 'spatial_set_phase', phase });
  }

  async getSpatialState() {
    return this._get('/api/spatial/state');
  }

  static float32ToBase64(samples) {
    const u8 = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < u8.length; i += chunk) {
      binary += String.fromCharCode.apply(null, u8.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  async analyzeSpatialPoint(samples, sampleRate, { deviceProfileId = null } = {}) {
    const resp = await fetch(`${this.baseURL}/api/spatial/analyze`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        samples_b64: WhickAPI.float32ToBase64(samples),
        sample_rate: sampleRate,
        level: 'smartphone',
        device_profile_id: deviceProfileId,
        room_mode_only: true,
      }),
    });
    if (!resp.ok) throw new Error(`${resp.status} spatial/analyze`);
    return resp.json();
  }

  async averageSpatialRuns(runs, pointCount) {
    const resp = await fetch(`${this.baseURL}/api/spatial/average`, {
      method: 'POST',
      headers: this._authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ runs, point_count: pointCount }),
    });
    if (!resp.ok) throw new Error(`${resp.status} spatial/average`);
    return resp.json();
  }

  async applyDspPreset(slug) {
    const resp = await fetch(`${this.baseURL}/api/dsp/preset/${encodeURIComponent(slug)}`, {
      method: 'POST',
      headers: this._authHeaders(),
    });
    if (!resp.ok) throw new Error(`${resp.status} dsp preset`);
    return resp.json();
  }

  async playRadio(stationId) {
    if (this.isMobileOutput()) {
      this._beginMobileTransportGuard();
      this._mobileRadioSyncLock = true;
      this._claimMobileSession(`radio:${stationId}`);
      this._send({ cmd: 'play_radio', station_id: stationId });
      try {
        await this._playMobileStream(this._radioMobileStreamUrl(stationId), {
          source: 'radio',
          radioId: stationId,
        });
        const data = { ok: true, station_id: stationId };
        this.emit('radio_started', data);
        return data;
      } finally {
        this._mobileRadioSyncLock = null;
      }
    }
    this._stopMobileAudio();
    this._clearMobileClaim();
    const sent = this._send({ cmd: 'play_radio', station_id: stationId });
    if (!sent) {
      // WS 미연결 시 REST 로 MPD 재생 시작 (설계: GET /api/radio/{id}/play)
      await this._get(`/api/radio/${encodeURIComponent(stationId)}/play?output=server`);
    }
    const data = await this._get(`/api/radio/${encodeURIComponent(stationId)}/stream`);
    this.emit('radio_started', { ...data, playback: 'server' });
    return { ...data, playback: 'server' };
  }

  stopRadio() {
    this._stopMobileAudio();
    return this._send({ cmd: 'stop_radio' });
  }

  on(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
    return () => this.off(event, callback);
  }

  off(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter((cb) => cb !== callback);
    }
  }

  emit(event, data) {
    (this.listeners[event] || []).forEach((cb) => cb(data));
  }

  get isConnected() {
    return this.wsReady;
  }

  get state() {
    return this.stateCache;
  }

  static formatTime(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const m = Math.floor(s / 60);
    return `${m}:${(s % 60).toString().padStart(2, '0')}`;
  }

  static qualityLabel(t) {
    const bd = t.bit_depth || '';
    const sr = t.sample_rate ? Math.round(t.sample_rate / 1000) : '';
    const fmt = t.format || 'FLAC';
    return bd && sr ? `${bd}/${sr}·${fmt}` : fmt;
  }
}

const WHICK_EQ_BANDS = [
  { freq: 60, q: 1.0 },
  { freq: 120, q: 1.0 },
  { freq: 250, q: 1.0 },
  { freq: 500, q: 1.1 },
  { freq: 1000, q: 1.0 },
  { freq: 2000, q: 1.0 },
  { freq: 5000, q: 0.9 },
  { freq: 10000, q: 0.8 },
];

// 프리셋 gain(8밴드) — 서버 dsp_store.PRESET_CATALOG 와 동일하게 유지.
// 구버전 플레이어는 /api/dsp/presets 응답에 gains 를 주지 않으므로 클라이언트에서 보유한다.
const WHICK_EQ_PRESET_GAINS = {
  neutral: [0, 0, 0, 0, 0, 0, 0, 0],
  warm: [2.5, 2.2, 1.6, 1.0, 0.3, -0.8, -1.6, -2.4],
  bright: [-2.0, -1.4, -0.5, 0, 0.8, 1.6, 2.4, 3.0],
  vocal: [-1.5, -0.4, 1.0, 2.2, 2.8, 2.2, 1.2, -0.5],
  wide: [0.8, 0.5, 0, -0.3, 0, 0.5, 1.0, 1.2],
};

class WhickUIBridge {
  constructor(api) {
    this.api = api;
    this._systemPollTimer = null;
    this._activeLibraryTab = 'all';
    this._libraryTabLoaded = {};
    this._extStorageMounted = false;
    this._extStoragePct = null;
    this._lastSystemStatus = null;
    this._favIds = null; // 서버 즐겨듣기 track_id Set — null이면 아직 로드 전
    this._checkedTracks = new Set(); // 라이브러리 선택 → 재생 대기열
    this._favCheckedTracks = new Set(); // 즐겨듣기 모음 만들기/수정 전용 (재생과 무관)
    this._radioOnId = null; // 라디오 선택 표시 (.rc.on)
    this._metaOpenKey = null; // listId:index — 라이브러리 메타 아코디언
    this._bindAPIEvents();
    this._bindTransport();
    this._bindSpeakerOutputSettings();
    this._bindDspSettings();
    this._bindDacPreprocessSettings();
    this._bindConnectModeSettings();
    this._bindUsbPromptButtons();
    this._fsExplorer =
      typeof window.WhickLibraryFsExplorer === 'function'
        ? new window.WhickLibraryFsExplorer(api)
        : null;
  }

  openFsExplorer(opts = {}) {
    if (!this._fsExplorer) {
      alert(_t('err.fs_load', '파일 탐색기를 불러오지 못했습니다.'));
      return;
    }
    this._fsExplorer.open(opts);
  }

  _bindSpeakerOutputSettings() {
    const serverBtn = document.getElementById('spk-server');
    const mobileBtn = document.getElementById('spk-mobile');
    const sync = (mode) => {
      const mobile = mode === 'mobile';
      serverBtn?.classList.toggle('on', !mobile);
      mobileBtn?.classList.toggle('on', mobile);
      if (typeof window.syncOutputPipeline === 'function') {
        window.syncOutputPipeline(mode);
        return;
      }
      this._setText(
        'spk-mode-desc',
        mobile
          ? _t('out.to_phone', '모든 재생 → 이 스마트폰 (공유기·터널 스트림)')
          : _t('out.to_dac', '모든 재생 → 미니PC DAC · AMP · 스피커'),
      );
    };
    // 출력 전환 중에는 버튼을 잠그고 안내를 표시 → 완료되면 다시 활성화
    const setTransition = (active, to) => {
      [serverBtn, mobileBtn].forEach((btn) => {
        if (!btn) return;
        btn.disabled = active;
        btn.style.opacity = active ? '0.5' : '';
        btn.style.pointerEvents = active ? 'none' : '';
        btn.setAttribute('aria-busy', active ? 'true' : 'false');
      });
      if (active) {
        this._setText(
          'spk-mode-desc',
          to === 'mobile'
            ? _t('out.switching_phone', '전환 중… 이 스마트폰으로 출력 준비')
            : _t('out.switching_dac', '전환 중… 미니PC DAC 출력 준비'),
        );
      }
    };
    sync(this.api.outputMode);
    this.api.on('output_mode', (data) => sync(data.mode));
    this.api.on('output_transition', (data) => {
      if (data?.state === 'start') {
        setTransition(true, data.to);
      } else {
        setTransition(false);
        sync(this.api.outputMode);
      }
    });
    serverBtn?.addEventListener('click', () => {
      if (this.api._outputHandoffLock) return;
      this.api.setOutputMode('server');
    });
    mobileBtn?.addEventListener('click', () => {
      if (this.api._outputHandoffLock) return;
      this.api.setOutputMode('mobile');
    });
  }

  _bindDspSettings() {
    this._dspState = {
      bands: WHICK_EQ_BANDS.map((b) => ({ ...b, gainDb: 0 })),
      eqEnabled: true,
      dspEnabled: true,
      balancePan: 0,
      masterGainDb: 0,
      swapChannels: false,
      presets: [],
      applying: false,
    };

    const presetsEl = document.getElementById('dsp-presets');
    const bandsEl = document.getElementById('dsp-eq-bands');
    const balanceEl = document.getElementById('dsp-balance');
    const balanceVal = document.getElementById('dv-balance');
    const balanceNudgeL = document.getElementById('dsp-balance-l');
    const balanceNudgeR = document.getElementById('dsp-balance-r');
    const masterEl = document.getElementById('dsp-master-gain');
    const masterVal = document.getElementById('dv-master-gain');
    const dspTog = document.getElementById('tog-dsp');
    const eqTog = document.getElementById('tog-eq');
    const swapTog = document.getElementById('tog-dsp-swap');
    const statusEl = document.getElementById('dsp-eq-status');
    if (!bandsEl || !balanceEl) return;

    const setStatus = (msg, kind = 'info') => {
      if (!statusEl) return;
      statusEl.textContent = msg || '';
      statusEl.dataset.kind = kind;
    };

    const formatPan = (pan) =>
      pan === 0 ? '0' : pan > 0 ? `R+${pan.toFixed(1)}` : `L+${(-pan).toFixed(1)}`;

    const formatMaster = (db) => {
      const n = Number(db) || 0;
      return `${n >= 0 ? '+' : ''}${n.toFixed(1)}`;
    };

    const nudgeBalance = (delta) => {
      const pan = Math.max(-6, Math.min(6, (Number(balanceEl.value) || 0) + delta));
      balanceEl.value = String(pan);
      if (balanceVal) balanceVal.textContent = formatPan(pan);
      balanceEl.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const syncToggles = () => {
      dspTog?.classList.toggle('on', !!this._dspState.dspEnabled);
      eqTog?.classList.toggle('on', !!this._dspState.eqEnabled);
      swapTog?.classList.toggle('on', !!this._dspState.swapChannels);
      swapTog?.setAttribute('aria-checked', this._dspState.swapChannels ? 'true' : 'false');
      bandsEl.classList.toggle('eq-off', !this._dspState.eqEnabled);
      balanceEl.disabled = !this._dspState.dspEnabled;
      if (masterEl) masterEl.disabled = !this._dspState.dspEnabled;
    };

    const syncWizardSwap = () => {
      if (!window._sharedSpatialWizard) return;
      window._sharedSpatialWizard.swapChannels = !!this._dspState.swapChannels;
      try {
        window._sharedSpatialWizard.render?.();
      } catch {
        /* ignore */
      }
    };

    const freqLabel = (hz) => (hz >= 1000 ? `${Math.round(hz / 1000)}k` : String(hz));

    const renderPresets = () => {
      if (!presetsEl) return;
      presetsEl.innerHTML = (this._dspState.presets || [])
        .map(
          (p) =>
            `<button type="button" class="chip dsp-preset" data-slug="${p.slug}">${window._t('dsp.preset_' + p.slug, p.labelKo || p.slug)}</button>`,
        )
        .join('');
      presetsEl.querySelectorAll('.dsp-preset').forEach((btn) => {
        btn.addEventListener('click', () => this._applyDspPreset(btn.dataset.slug));
      });
    };

    const renderBands = () => {
      bandsEl.innerHTML = this._dspState.bands
        .map((b, i) => {
          const g = Number(b.gainDb) || 0;
          const pct = Math.round(((g + 9) / 18) * 100);
          return `
        <label class="eq-band">
          <span class="eq-band-f">${freqLabel(b.freq)}</span>
          <input type="range" class="eq-band-r" data-idx="${i}" min="-9" max="9" step="0.5" value="${g}" orient="vertical">
          <span class="eq-band-v" data-idx="${i}">${g >= 0 ? '+' : ''}${g.toFixed(1)}</span>
        </label>`;
        })
        .join('');
      bandsEl.querySelectorAll('.eq-band-r').forEach((inp) => {
        const idx = Number(inp.dataset.idx);
        inp.addEventListener('input', () => {
          const g = Number(inp.value) || 0;
          this._dspState.bands[idx].gainDb = g;
          const readout = bandsEl.querySelector(`.eq-band-v[data-idx="${idx}"]`);
          if (readout) readout.textContent = `${g >= 0 ? '+' : ''}${g.toFixed(1)}`;
          presetsEl?.querySelectorAll('.dsp-preset.on').forEach((b) => b.classList.remove('on'));
        });
        inp.addEventListener('change', () =>
          this._commitDspEq({ restart: false, eqEnabled: true }),
        );
      });
    };

    const applyProfileToUi = (prof) => {
      const dsp = prof?.dsp || prof || {};
      const userPeaking = dsp.userPeaking || dsp.peaking || [];
      this._dspState.dspEnabled = dsp.enabled !== false;
      this._dspState.eqEnabled = dsp.eqEnabled != null ? !!dsp.eqEnabled : true;
      this._dspState.swapChannels = !!dsp.swapChannels;
      this._dspState.bands = WHICK_EQ_BANDS.map((def, i) => {
        const band = userPeaking[i] || {};
        return {
          freq: def.freq,
          q: def.q,
          gainDb: Number(band.gainDb) || 0,
        };
      });
      const bal = dsp.balanceDb || { left: 0, right: 0 };
      // pan>0 = 오른쪽(R+) → right gain 이 양수
      this._dspState.balancePan = (Number(bal.right) || 0) - (Number(bal.left) || 0);
      balanceEl.value = String(this._dspState.balancePan);
      if (balanceVal) {
        const p = this._dspState.balancePan;
        balanceVal.textContent = p === 0 ? '0' : p > 0 ? `R+${p.toFixed(1)}` : `L+${(-p).toFixed(1)}`;
      }
      this._dspState.masterGainDb = Math.max(
        -12,
        Math.min(12, Number(dsp.masterGainDb) || 0),
      );
      if (masterEl) masterEl.value = String(this._dspState.masterGainDb);
      if (masterVal) masterVal.textContent = formatMaster(this._dspState.masterGainDb);
      syncToggles();
      syncWizardSwap();
      renderBands();
    };

    this._commitDspSwap = async (on) => {
      if (this._dspState.applying) return;
      const next = !!on;
      const prev = !!this._dspState.swapChannels;
      this._dspState.swapChannels = next;
      syncToggles();
      syncWizardSwap();
      this._dspState.applying = true;
      setStatus(_t('rev.applying', '좌우 반전 적용 중…'));
      try {
        await this.api.saveChannelSetup({ swapChannels: next });
        if (this.api.outputMode === 'server') {
          setStatus(
            next
              ? _t('rev.on', '좌우 반전 켜짐 · 왼쪽/오른쪽 버튼으로 확인')
              : _t('rev.off', '좌우 반전 꺼짐 · 왼쪽/오른쪽 버튼으로 확인'),
            'ok',
          );
        } else {
          setStatus(
            next
              ? _t('rev.saved_on', '저장됨 (미니PC·서버 스피커 출력에서 적용)')
              : _t('rev.saved_off', '저장됨 (미니PC·서버 스피커 출력에서 해제)'),
            'ok',
          );
        }
      } catch (e) {
        console.error(e);
        this._dspState.swapChannels = prev;
        syncToggles();
        syncWizardSwap();
        setStatus(_t('rev.failed', '좌우 반전 적용 실패'), 'err');
      } finally {
        this._dspState.applying = false;
      }
    };

    this._commitDspEq = async ({ restart = false, eqEnabled, dspEnabled } = {}) => {
      if (this._dspState.applying) return;
      if (eqEnabled != null) this._dspState.eqEnabled = !!eqEnabled;
      if (dspEnabled != null) this._dspState.dspEnabled = !!dspEnabled;
      syncToggles();
      this._dspState.applying = true;
      setStatus(_t('eq.applying', 'EQ 적용 중…'));
      try {
        const pan = Number(balanceEl.value) || 0;
        this._dspState.balancePan = pan;
        if (balanceVal) {
          balanceVal.textContent = pan === 0 ? '0' : pan > 0 ? `R+${pan.toFixed(1)}` : `L+${(-pan).toFixed(1)}`;
        }
        if (masterEl) {
          this._dspState.masterGainDb = Math.max(-12, Math.min(12, Number(masterEl.value) || 0));
          if (masterVal) masterVal.textContent = formatMaster(this._dspState.masterGainDb);
        }
        await this.api.saveUserEq({
          eqEnabled: this._dspState.eqEnabled,
          dspEnabled: this._dspState.dspEnabled,
          enabled: this._dspState.dspEnabled,
          gains: this._dspState.bands.map((b) => Number(b.gainDb) || 0),
          // pan>0 = 오른쪽(R+) 강조 → 오른쪽 채널 gain↑, pan<0 = 왼쪽(L+)
          balanceDb: { left: pan < 0 ? -pan : 0, right: pan > 0 ? pan : 0 },
          masterGainDb: this._dspState.masterGainDb,
        });
        // restart=true 는 구조 변경용만. EQ/밸런스/마스터는 Camilla SetConfig hot path.
        if (restart && this.api.outputMode === 'server') {
          await this.api.replayForDspApply();
        }
        setStatus(
          this.api.outputMode === 'mobile'
            ? _t('eq.saved_on', '저장됨 (미니PC 출력에서 적용)')
            : _t('eq.applied', '적용됨'),
          'ok',
        );
      } catch (e) {
        console.error(e);
        setStatus(_t('eq.failed', 'EQ 적용 실패'), 'err');
      } finally {
        this._dspState.applying = false;
      }
    };

    this._applyDspPreset = async (slug) => {
      if (!slug || this._dspState.applying) return;
      const preset = (this._dspState.presets || []).find((p) => p.slug === slug);
      const gains = (preset && preset.gains) || WHICK_EQ_PRESET_GAINS[slug];
      if (!gains) {
        setStatus(_t('eq.unknown_preset', '알 수 없는 프리셋'), 'err');
        return;
      }
      // 프리셋 = 슬라이더 gain 채우기 + EQ ON 유지 (백엔드 응답에 의존하지 않음)
      this._dspState.bands = WHICK_EQ_BANDS.map((def, i) => ({
        freq: def.freq,
        q: def.q,
        gainDb: Number(gains[i]) || 0,
      }));
      this._dspState.eqEnabled = true;
      renderBands();
      presetsEl?.querySelectorAll('.dsp-preset').forEach((b) => {
        b.classList.toggle('on', b.dataset.slug === slug);
      });
      syncToggles();
      await this._commitDspEq({ restart: false });
    };

    this._loadDspProfile = async () => {
      try {
        const [prof, presetData] = await Promise.all([
          this.api.getDspProfile(),
          this.api.getDspPresets().catch(() => ({ presets: [] })),
        ]);
        const presetLabelMap = {
          neutral: _t('dsp.flat', '플랫'),
          warm: _t('dsp.warm', '따뜻'),
          bright: _t('dsp.bright', '밝음'),
          vocal: _t('dsp.vocal', '보컬'),
          wide: _t('dsp.wide', '와이드'),
        };
        this._dspState.presets = (presetData.presets || []).map((p) => ({
          ...p,
          labelKo: presetLabelMap[p.slug] || p.labelKo || p.slug,
          gains: p.gains || WHICK_EQ_PRESET_GAINS[p.slug],
        }));
        if (!this._dspState.presets.length) {
          this._dspState.presets = Object.keys(WHICK_EQ_PRESET_GAINS).map((slug) => ({
            slug,
            labelKo: presetLabelMap[slug] || slug,
            gains: WHICK_EQ_PRESET_GAINS[slug],
          }));
        }
        renderPresets();
        applyProfileToUi(prof);
        setStatus('');
      } catch (e) {
        console.error(e);
        renderBands();
        setStatus(_t('dsp.load_failed', 'DSP 프로필 불러오기 실패'), 'err');
      }
    };

    balanceEl.addEventListener('input', () => {
      const pan = Number(balanceEl.value) || 0;
      if (balanceVal) {
        balanceVal.textContent = pan === 0 ? '0' : pan > 0 ? `R+${pan.toFixed(1)}` : `L+${(-pan).toFixed(1)}`;
      }
    });
    balanceEl.addEventListener('change', () => this._commitDspEq({ restart: false }));

    if (masterEl) {
      masterEl.addEventListener('input', () => {
        const db = Math.max(-12, Math.min(12, Number(masterEl.value) || 0));
        this._dspState.masterGainDb = db;
        if (masterVal) masterVal.textContent = formatMaster(db);
      });
      masterEl.addEventListener('change', () => {
        const db = Math.max(-12, Math.min(12, Number(masterEl.value) || 0));
        this._dspState.masterGainDb = db;
        if (masterVal) masterVal.textContent = formatMaster(db);
        this._commitDspEq({ restart: false });
      });
    }

    balanceNudgeL?.addEventListener('click', () => nudgeBalance(-0.1));
    balanceNudgeR?.addEventListener('click', () => nudgeBalance(0.1));

    dspTog?.addEventListener('click', (e) => {
      e.stopPropagation();
      this._commitDspEq({ dspEnabled: !this._dspState.dspEnabled, restart: false });
    });
    eqTog?.addEventListener('click', (e) => {
      e.stopPropagation();
      this._commitDspEq({ eqEnabled: !this._dspState.eqEnabled, restart: false });
    });
    swapTog?.addEventListener('click', (e) => {
      e.stopPropagation();
      this._commitDspSwap(!this._dspState.swapChannels);
    });

    renderBands();
    this.api.on('connected', () => this._loadDspProfile());
    if (this.api.wsReady) this._loadDspProfile();
  }

  _bindDacPreprocessSettings() {
    const load = async () => {
      try {
        const prof = await this.api.getDspProfile();
        const dsp = prof?.dsp || {};
        const on = dsp.dacPreprocessEnabled !== false;
        const osInfo = prof?.dacOs || {};
        if (typeof window._setDacPreprocessFromServer === 'function') {
          window._setDacPreprocessFromServer(on, osInfo);
        }
      } catch {
        /* profile optional on connect */
      }
    };
    this.api.on('connected', load);
    if (this.api.wsReady) load();
  }

  _bindUsbPromptButtons() {
    const yes = document.getElementById('usb-prompt-yes');
    const no = document.getElementById('usb-prompt-no');
    const manual = document.getElementById('usb-prompt-manual');
    const reviewYes = document.getElementById('ext-review-yes');
    const reviewNo = document.getElementById('ext-review-no');
    if (yes) yes.addEventListener('click', () => this._registerExternalQuick());
    if (manual) manual.addEventListener('click', () => this._openExternalManual());
    if (no) no.addEventListener('click', () => this._dismissUsbPrompt());
    if (reviewYes) reviewYes.addEventListener('click', () => this._acceptRejectedImport());
    if (reviewNo) reviewNo.addEventListener('click', () => this._dismissRejectedImport());
  }

  static formatMetricPct(v) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return `${Math.round(Number(v))}%`;
  }

  static formatMetricsLine(m) {
    if (!m) return '';
    const parts = [
      'CPU ' + WhickUIBridge.formatMetricPct(m.cpu_pct),
      'RAM ' + WhickUIBridge.formatMetricPct(m.mem_pct),
      'SSD1 ' + WhickUIBridge.formatMetricPct(m.ssd1_pct ?? m.disk_pct),
    ];
    if (m.ssd2_pct != null) parts.push('SSD2 ' + WhickUIBridge.formatMetricPct(m.ssd2_pct));
    // CPU/SoC 온도는 게이지 「온도」에만 표시. 여기 숫자°C는 외기·현재위치 기온으로 오인됨(구 23°C).
    return parts.join(' · ');
  }

  _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? '';
  }

  _setAutoplayBanner(show) {
    const el = document.getElementById('mobile-autoplay-banner');
    if (!el) return;
    el.classList.toggle('hd', !show);
  }

  _resetSpectrumBars() {
    document.querySelectorAll('#vu .vu-bar').forEach((bar) => {
      bar.style.height = '5%';
      bar.style.opacity = '0.15';
    });
    document.querySelectorAll('#eq .eq-bar').forEach((bar) => {
      bar.style.height = '5%';
    });
  }

  _updateSpectrumBars(bands) {
    if (!bands || !bands.length) return;
    const vuBars = document.querySelectorAll('#vu .vu-bar');
    vuBars.forEach((bar, i) => {
      const idx = Math.min(
        bands.length - 1,
        Math.floor((i / Math.max(1, vuBars.length - 1)) * (bands.length - 1)),
      );
      const v = bands[idx];
      bar.style.height = `${5 + v * 90}%`;
      bar.style.opacity = `${0.25 + v * 0.75}`;
    });
    document.querySelectorAll('#eq .eq-bar').forEach((bar, i) => {
      const idx = Math.min(i, bands.length - 1);
      const v = bands[idx];
      bar.style.height = `${Math.min(100, 5 + v * 92)}%`;
    });
  }

  _bindAPIEvents() {
    this.api.on('state', (s) => {
      this._syncCheckedFromQueue(s);
      this._updateNowPlaying(s);
      this._syncRadioSelectionFromState(s);
      this._updateControls(s);
      this._updateProgress(s);
      this._updateQueuePanel(s);
      if (!s.playing) this._resetSpectrumBars();
    });

    this.api.on('spectrum', (data) => {
      // 모바일 출력: 폰 Audio() 분석값만 사용 (서버 MPD fifo 스펙트럼 무시)
      if (this.api.isMobileOutput() && data?.source !== 'mobile-client') {
        return;
      }
      if (!this.api.stateCache.playing) {
        this._resetSpectrumBars();
        return;
      }
      this._updateSpectrumBars(data.bands || []);
    });

    this.api.on('mobile_playback_error', (info) => {
      const msg = info?.message || _t('err.cannot_play', '이 기기에서 재생할 수 없습니다');
      const hint =
        info?.provider === 'spotify'
          ? _t('err.no_preview', '\n(No Spotify preview · use mini PC speakers or Spotify Connect)')
          : '';
      console.warn('[WhickUI] mobile playback', info);
      if (typeof window !== 'undefined' && window.alert) {
        window.alert(msg + hint);
      }
    });

    this.api.on('mobile_autoplay_blocked', () => this._setAutoplayBanner(true));
    this.api.on('mobile_autoplay_resumed', () => this._setAutoplayBanner(false));
    this.api.on('state', (s) => {
      // 모바일 출력인데 폰에서 실제로 소리가 안 나는 상태(엘리먼트 없음·일시정지·차단)면
      // "탭하여 소리 재생" 배너를 띄운다. (전환 시 자동재생 차단 복구 경로)
      const ma = this.api.mobileAudio;
      const mobileSilent = !ma || ma.paused || this.api._mobileAutoplayBlocked;
      const needsMobileTap =
        !!s?.playing && this.api.isMobileOutput() && s.server_audio_active === false && mobileSilent;
      if (needsMobileTap) {
        this._setAutoplayBanner(true);
        return;
      }
      if (!s?.playing || !this.api._mobileAutoplayBlocked) {
        this._setAutoplayBanner(false);
      }
    });

    this.api.on('connected', (info) => this._onConnectionActive(info, { fullInit: true }));
    this.api.on('primary_changed', (info) => this._onConnectionActive(info, { fullInit: false }));

    this.api.on('disconnected', () => {
      document.querySelectorAll('.top-srv .dot').forEach((d) => d.classList.remove('on'));
      this._setText('top-srv-label', window._t('conn.reconnecting', '재연결 중…'));
      this._setText('conn-text', window._t('conn.reconnecting', '재연결 중…'));
      this._stopSystemPoll();
      this._renderSystemStatus({ agent_online: false, metrics: null });
      this._resetSpectrumBars();
    });

    this.api.on('usb_library_prompt', (data) => {
      this._showExternalPrompt(data);
    });
    this.api.on('external_library_review', (data) => {
      this._showExternalReview(data);
    });
    this.api.on('notify', (data) => {
      if (data?.event === 'consent_request' && typeof window.onOpsConsentRequest === 'function') {
        try {
          window.onOpsConsentRequest(data);
        } catch (err) {
          console.warn('[WhickUI] ops consent notify', err);
        }
      }
      const msg = String(data?.message || data?.title || '').trim();
      if (!msg) return;
      if (typeof window.libToast === 'function') {
        window.libToast(msg);
      } else if (typeof window.alert === 'function') {
        window.alert(msg);
      }
    });
  }

  _connectionModeLabel(info) {
    const base =
      info?.mode === 'lan'
        ? window._t('conn.online_wifi', '온라인 · Wi-Fi')
        : info?.mode === 'tunnel'
          ? window._t('conn.online_cc', '온라인 · 관제')
          : window._t('conn.online', '온라인');
    if (info?.standby) {
      const standby =
        info.mode === 'lan'
          ? window._t('conn.standby_cc', '관제 대기')
          : info.mode === 'tunnel'
            ? window._t('conn.standby_wifi', 'Wi-Fi 대기')
            : '';
      return standby ? `${base} (${standby})` : base;
    }
    return base;
  }

  _onConnectionActive(info, { fullInit = true } = {}) {
    document.querySelectorAll('.dot').forEach((d) => d.classList.add('on'));
    const modeLabel = this._connectionModeLabel(info);
    this._setText('top-srv-label', modeLabel);
    this._setText('conn-text', modeLabel);
    this._updateConnectModeUi(info?.mode);
    if (fullInit) {
      this._loadDashboard();
      this._loadLibrary();
      this._loadRadio();
      this._startSystemPoll();
      this._pollUsbPending();
      this._maybeShowVolumeHint();
    } else {
      this._startSystemPoll();
    }
  }

  _updateConnectModeUi(activeMode) {
    const mode = this.api.connectMode || 'auto';
    const hasTun = !!this.api.tunnelHost;
    const hasLan = !!this.api.lanHost;
    const labels = {
      auto: _t('conn.auto', '자동 (Wi-Fi 우선 → 관제)'),
      lan: _t('conn.lan', '공유기 Wi-Fi 직접'),
      tunnel: _t('conn.tunnel', '중앙관제 터널'),
    };
    const active =
      activeMode === 'lan' ? _t('conn.lan_short', '공유기 Wi-Fi') : activeMode === 'tunnel' ? _t('conn.cc_short', '중앙관제') : '—';
    this._setText('conn-mode-value', labels[mode] || labels.auto);
    // 실제 가용 링크를 반영해 정직하게 안내한다. (예: 이 기기에 터널이 없으면 Wi-Fi 폴백)
    let note = active !== '—' ? `_t('conn.now_prefix', '현재: ')${active}` : '';
    if (mode === 'tunnel' && !hasTun) {
      note = _t('conn.no_tunnel', '이 기기는 터널 미설정 → Wi-Fi로 연결됨');
    } else if (mode === 'lan' && !hasLan) {
      note = _t('conn.no_lan', 'Wi-Fi 직접 주소 없음 → 터널로 연결됨');
    }
    this._setText('conn-mode-active', note);
    const sel = document.getElementById('conn-mode-select');
    if (sel) {
      sel.value = mode;
      const tunOpt = sel.querySelector('option[value="tunnel"]');
      if (tunOpt) {
        tunOpt.textContent = hasTun
          ? _t('conn.tunnel_external', '중앙관제 터널 — 외부·LTE')
          : _t('conn.tunnel_unset', '중앙관제 터널 — (이 기기 미설정)');
      }
    }
  }

  async _pollUsbPending() {
    try {
      const data = await this.api.getUsbPending();
      if (data?.pending) this._showUsbPrompt(data.pending);
    } catch {
      /* ignore */
    }
  }

  _showExternalPrompt(pending) {
    if (!pending?.mount_point) return;
    this._markExtStorage(pending);
    const overlay = document.getElementById('usb-prompt-overlay');
    const review = document.getElementById('ext-review-panel');
    const detect = document.getElementById('ext-detect-panel');
    if (!overlay) return;
    if (review) review.style.display = 'none';
    if (detect) detect.style.display = '';
    const files = pending.audio_files || 0;
    const label = pending.label || pending.mount_point;
    const msg = document.getElementById('usb-prompt-msg');
    if (msg) {
      msg.textContent = `「${label}」· ${files} ${_t('unit.files_found', 'music files found. Copy/move in the file explorer, or add the path to the library.')}`;
    }
    overlay.dataset.mount = pending.mount_point;
    overlay.classList.add('open');
  }

  _showExternalReview(review) {
    if (!review?.mount_point) return;
    const overlay = document.getElementById('usb-prompt-overlay');
    const detect = document.getElementById('ext-detect-panel');
    const panel = document.getElementById('ext-review-panel');
    const list = document.getElementById('ext-review-list');
    if (!overlay || !panel) return;
    if (detect) detect.style.display = 'none';
    panel.style.display = '';
    overlay.dataset.mount = review.mount_point;
    const rejected = review.rejected || review.rejected_items || [];
    if (list) {
      list.innerHTML = rejected
        .map(
          (it) => `
        <label class="ext-review-item">
          <input type="checkbox" class="ext-reject-pick" value="${it.rel_path}" checked />
          <span>${it.rel_path}</span>
          <small>${(it.reasons || []).join(', ')}</small>
        </label>`,
        )
        .join('');
    }
    const msg = document.getElementById('ext-review-msg');
    if (msg) {
      msg.textContent = `${rejected.length} ${_t('rev2.rejected_prefix', 'rejected — select tracks to add to the library anyway.')}`;
    }
    overlay.classList.add('open');
  }

  async _registerExternalQuick() {
    const overlay = document.getElementById('usb-prompt-overlay');
    const mount = overlay?.dataset?.mount || '';
    overlay?.classList.remove('open');
    if (!mount) return;
    // mount like /media/LABEL → register whole mount under media root
    let rel = String(mount).replace(/^\/media\//, '').replace(/^\/run\/media\/[^/]+\//, '');
    if (rel.startsWith('/')) rel = rel.replace(/^\/+/, '');
    try {
      const r = await this.api.fsRegister('media', [rel || '']);
      alert(`${_t('rev2.imported_prefix', 'Library import done — ')}${r.upserted || 0}${_t('unit.tracks_suffix', ' tracks (files kept on external drive)')}`);
      await this._loadDashboard();
      this._loadLibrary();
    } catch (e) {
      alert(_t('err.register_failed', '등록 실패: ') + (e.message || e));
      this.openFsExplorer({ root: 'media', path: rel });
    }
  }

  async _acceptExternalAuto() {
    await this._registerExternalQuick();
  }

  async _openExternalManual() {
    const overlay = document.getElementById('usb-prompt-overlay');
    const mount = overlay?.dataset?.mount || '';
    overlay?.classList.remove('open');
    let rel = '';
    if (mount) {
      rel = String(mount).replace(/^\/media\//, '').replace(/^\/run\/media\/[^/]+\//, '');
    }
    this.openFsExplorer({ root: 'media', path: rel });
  }

  async _acceptRejectedImport() {
    const overlay = document.getElementById('usb-prompt-overlay');
    const mount = overlay?.dataset?.mount || '';
    const picks = [...document.querySelectorAll('.ext-reject-pick:checked')].map((el) => el.value);
    if (!mount || !picks.length) {
      alert(_t('lib.select_first', '추가할 곡을 선택하세요.'));
      return;
    }
    overlay.classList.remove('open');
    try {
      const r = await this.api.processExternalLibrary({
        mountPoint: mount,
        mode: 'manual',
        paths: picks,
        importRejected: picks,
      });
      alert(`${r.imported?.moved ?? picks.length}${_t('rev2.tracks_added_suffix', ' rejected tracks added')}`);
      await this._loadDashboard();
      this._loadLibrary();
    } catch (e) {
      alert(_t('err.add_failed', '추가 실패: ') + (e.message || e));
    }
  }

  _dismissRejectedImport() {
    this._dismissUsbPrompt();
  }

  _showUsbPrompt(pending) {
    this._showExternalPrompt(pending);
  }

  async _acceptUsbPrompt() {
    await this._acceptExternalAuto();
  }

  _dismissUsbPrompt() {
    const overlay = document.getElementById('usb-prompt-overlay');
    const mount = overlay?.dataset?.mount || '';
    overlay?.classList.remove('open');
    this.api.dismissUsbPrompt(mount).catch(() => {});
  }

  _markExtStorage(pending) {
    this._extStorageMounted = true;
    const pct = pending?.usage_pct ?? pending?.ext_pct ?? pending?.disk_pct;
    if (pct != null) this._extStoragePct = Number(pct);
    if (this._lastSystemStatus) this._renderSystemStatus(this._lastSystemStatus);
  }

  _bindConnectModeSettings() {
    const sel = document.getElementById('conn-mode-select');
    if (!sel) return;
    sel.addEventListener('change', () => {
      const mode = sel.value || 'auto';
      this.api.setConnectMode(mode);
      this._updateConnectModeUi(this.api.connectionMode);
      this.api.reconnect();
    });
  }

  _startSystemPoll() {
    this._stopSystemPoll();
    this._pollSystemStatus();
    this._systemPollTimer = window.setInterval(() => this._pollSystemStatus(), 30000);
  }

  _stopSystemPoll() {
    if (this._systemPollTimer) {
      clearInterval(this._systemPollTimer);
      this._systemPollTimer = null;
    }
  }

  async _pollSystemStatus() {
    try {
      const data = await this.api.getSystemStatus();
      this._lastSystemStatus = data;
      this._renderSystemStatus(data);
    } catch (e) {
      if (!this.api.isConnected) {
        this._lastSystemStatus = { agent_online: false, metrics: null };
        this._renderSystemStatus(this._lastSystemStatus);
      }
    }
  }

  _weatherFooterLine() {
    const loading = () => window._t('ai.weather_loading', '지역·날씨 확인 중…');
    try {
      // 네트워크 확정 전 캐시/부분 컨텍스트로 「맑음 23°」 깜빡임 금지
      if (!window.__aiWeatherReady) return loading();
      if (typeof window.aiContext !== 'function') return loading();
      const ctx = window.aiContext();
      const tempOk =
        ctx &&
        ctx.temp != null &&
        ctx.temp !== '' &&
        Number.isFinite(Number(ctx.temp)) &&
        ctx.source &&
        ctx.source !== 'fallback';
      if (!tempOk) return loading();
      const loc =
        typeof window._ctxLocationLine === 'function'
          ? window._ctxLocationLine(ctx)
          : [
              ctx.city || ctx.locationLabel || '',
              ctx.wEmoji || '',
              typeof window._pdT === 'function' ? window._pdT(ctx.weather) : (ctx.weather || ''),
              `${(Math.round(Number(ctx.temp) * 10) / 10).toFixed(1)}°C`,
            ]
              .filter(Boolean)
              .join(' ');
      const periodLabel =
        typeof window._pdT === 'function'
          ? window._pdT(ctx.period)
          : String(ctx.period || '');
      const period = [ctx.pEmoji, periodLabel].filter(Boolean).join(' ');
      return [loc, period].filter(Boolean).join(' · ');
    } catch {
      return loading();
    }
  }

  _renderSystemStatus(data) {
    const online = !!(data?.agent_online || data?.ok);
    const dot = document.getElementById('top-srv-dot');
    if (dot) dot.classList.toggle('on', online);
    const m = data?.metrics || null;
    const G = window.WhickSysGauge;
    const metrics = this._metricsForGauges(m, data);
    const footer = online ? this._weatherFooterLine() : '';
    if (G) {
      const subline = online && m ? WhickUIBridge.formatMetricsLine(m) : '';
      const badgeOn = window._t('sys.badge_online', '온라인');
      const badgeOff = window._t('sys.badge_offline', '오프라인');
      const offlineMsg = window._t('sys.offline_msg', 'Wi-Fi·터널 연결을 확인해 주세요.');
      G.paint(
        'dash-sys',
        G.renderPanel({
          online,
          badgeOnline: badgeOn,
          badgeOffline: badgeOff,
          offlineMsg,
          subline,
          metrics,
          alerts: data?.health_alerts,
          footer,
        }),
      );
      G.paint(
        'settings-sys',
        G.renderPanel({
          online,
          badgeOnline: badgeOn,
          badgeOffline: badgeOff,
          offlineMsg,
          metrics,
          alerts: data?.health_alerts,
          footer,
        }),
      );
      return;
    }
    const el = document.getElementById('dash-sys');
    if (!el) return;
    if (!online) {
      el.innerHTML =
        `<div class="ssh"><div class="sst">${window._t('sys.minipc_status', '미니PC 상태')}</div><div class="ssb"><div class="dot" style="background:var(--red)"></div>${window._t('sys.badge_offline', '오프라인')}</div></div>` +
        `<div style="font-size:11px;color:var(--text2)">${window._t('sys.offline_msg', 'Wi-Fi·터널 연결을 확인해 주세요.')}</div>`;
      return;
    }
    const line = WhickUIBridge.formatMetricsLine(m);
    const cells = [
      { label: 'CPU', val: m?.cpu_pct },
      { label: 'RAM', val: m?.mem_pct },
      { label: 'SSD1', val: m?.ssd1_pct ?? m?.disk_pct },
    ];
    if (m?.ssd2_pct != null) cells.push({ label: 'SSD2', val: m.ssd2_pct });
    if (m?.temp_c != null) cells.push({ label: window._t('sys.temp', '칩온도'), val: m.temp_c, unit: '°C' });
    el.innerHTML =
      `<div class="ssh"><div class="sst">${window._t('sys.minipc_status', '미니PC 상태')}</div><div class="ssb"><div class="dot on"></div>${window._t('sys.badge_online', '온라인')}</div></div>` +
      '<div style="font-size:10px;color:var(--text2);margin-bottom:10px">' +
      (line || window._t('sys.collecting', '메트릭 수집 중…')) +
      '</div>' +
      '<div class="ssg">' +
      cells
        .map((c) => {
          const v = c.unit ? Math.round(Number(c.val)) + c.unit : WhickUIBridge.formatMetricPct(c.val);
          return '<div class="ssi"><div class="ssv">' + v + '</div><div class="ssl">' + c.label + '</div></div>';
        })
        .join('') +
      '</div>';
  }

  _metricsForGauges(m, data) {
    if (!m) return null;
    const src = m || {};
    const gpu = src.gpu || {};
    const gpuAvailable = !!(src.gpu_available || gpu.available);
    let netPct = src.net_pct ?? src.net ?? src.network_pct ?? null;
    if (netPct == null && src.network_mbps != null) {
      const cap = Number(src.network_link_mbit || 1000);
      netPct = Math.min(100, Math.round((Number(src.network_mbps) / cap) * 100));
    }
    const operatingHours =
      src.ssd_hours ?? src.operating_hours ?? src.drive_hours ?? null;
    const uptimeSec =
      src.uptime_sec != null
        ? Number(src.uptime_sec)
        : data?.uptime_sec != null
          ? Number(data.uptime_sec)
          : null;
    return {
      cpu_pct: src.cpu_pct,
      mem_pct: src.mem_pct,
      ssd1_pct: src.ssd1_pct ?? src.disk_pct,
      ssd2_pct: src.ssd2_pct ?? null,
      ssd1_total_kb: src.ssd1_total_kb ?? null,
      ssd1_used_kb: src.ssd1_used_kb ?? null,
      ssd2_total_kb: src.ssd2_total_kb ?? null,
      ssd2_used_kb: src.ssd2_used_kb ?? null,
      uptime_sec: Number.isFinite(uptimeSec) ? uptimeSec : null,
      ssd_hours: operatingHours,
      operating_hours: operatingHours,
      temp_c: src.temp_c,
      ext_mounted: !!(this._extStorageMounted || src.ext_mounted || src.external_mounted),
      ext_pct: this._extStoragePct ?? src.ext_pct ?? src.ext_usage_pct,
      net_pct: netPct,
      vram_pct: src.vram_pct ?? (gpuAvailable ? gpu.vram_pct : null),
      vram_label: src.vram_label ?? (gpuAvailable ? gpu.vram_label : null),
      gpu_available: gpuAvailable,
      gpu,
    };
  }

  _findCachedTrack(trackId) {
    if (trackId == null || !this._trackLists) return null;
    const tid = Number(trackId);
    for (const list of Object.values(this._trackLists)) {
      if (!Array.isArray(list)) continue;
      const hit = list.find((t) => Number(t.track_id) === tid);
      if (hit) return hit;
    }
    return null;
  }

  _syncWindowCurFromState(s) {
    if (typeof window === 'undefined') return null;
    if (!s || s.source === 'idle' || !s.track_id) {
      if (typeof EMPTY_TR !== 'undefined') window.cur = EMPTY_TR;
      return window.cur || null;
    }
    const cached = this._findCachedTrack(s.track_id) || {};
    const filename =
      s.filename ||
      cached.filename ||
      (cached.file_path ? String(cached.file_path).split('/').pop() : '') ||
      '';
    const next = {
      id: s.track_id,
      track_id: s.track_id,
      t: s.title || cached.title || '—',
      a: s.artist || cached.artist || '—',
      al: s.album || cached.album || '—',
      title: s.title || cached.title || '',
      artist: s.artist || cached.artist || '',
      album: s.album || cached.album || '',
      c: s.composer || cached.composer || '',
      composer: s.composer || cached.composer || '',
      g: s.genre || cached.genre || '',
      genre: s.genre || cached.genre || '',
      fn: filename,
      filename,
      file_path: cached.file_path || '',
      q: s.quality || cached.quality || (typeof WhickAPI !== 'undefined' ? WhickAPI.qualityLabel(cached) : '') || '—',
      quality: s.quality || cached.quality || '',
      d:
        s.duration != null && typeof WhickAPI !== 'undefined'
          ? WhickAPI.formatTime(s.duration)
          : cached.duration_sec != null && typeof WhickAPI !== 'undefined'
            ? WhickAPI.formatTime(cached.duration_sec)
            : '—',
      duration_sec: s.duration || cached.duration_sec || 0,
      play_count: s.play_count ?? cached.play_count ?? 0,
      format: s.format || cached.format || '',
      license: cached.license || null,
      e: '🎼',
    };
    window.cur = next;
    try {
      if (typeof playerMetaOpen !== 'undefined' && playerMetaOpen && typeof renderPlayerMeta === 'function') {
        renderPlayerMeta(next);
      }
    } catch (_) {
      /* meta panel optional */
    }
    return next;
  }

  _updateNowPlaying(s) {
    // DIAGNOSTIC: remove after debugging
    const diag = {src:s.source, playing:s.playing, tid:s.track_id, title:s.title, artist:s.artist, album:s.album, dur:s.duration, pos:s.position};
    console.log('[NOWPLAYING]', new Date().toISOString().slice(11,19), JSON.stringify(diag));

    const srcLabel =
      s.source === 'radio'
        ? 'LIVE'
        : s.source === 'spotify'
          ? 'Spotify'
          : s.source === 'tidal'
            ? 'Tidal'
            : [s.artist, s.album].filter(Boolean).join(' · ');
    this._setText('hn-t', s.title || '—');
    this._setText('hn-a', srcLabel || '—');
    const nq = document.getElementById('hn-q');
    if (nq) {
      nq.textContent =
        s.source === 'radio'
          ? 'RADIO · LIVE'
          : s.source === 'spotify'
            ? 'SPOTIFY'
            : s.source === 'tidal'
              ? 'TIDAL · HiFi'
              : s.quality || (s.source === 'idle' ? window._t('player.waiting', '대기 중') : '');
    }
    this._setText('pt', s.title || '—');
    this._setText('pa', s.artist || '—');
    const pal =
      s.source === 'radio'
        ? _t('nav.radio', '라디오')
        : s.source === 'spotify'
          ? `Spotify${s.quality ? ' · ' + s.quality : ''}`
          : s.source === 'tidal'
            ? `Tidal${s.quality ? ' · ' + s.quality : ''}`
            : `${s.album || ''}${s.quality ? ' · ' + s.quality : ''}`;
    this._setText('pal', pal);
    this._setText('mpt', s.title || '—');
    this._setText('mpa', s.artist || '—');
    const mthEl = document.getElementById('mth');
    const mpArt = document.getElementById('mp-art');
    if (mthEl && mpArt) {
      mpArt.src = 'img/whick-mark.png?v=20260717-product';
      mthEl.classList.remove('mp-th--cover');
      mthEl.classList.add('mp-th--faint');
    } else {
      const thumb =
        s.source === 'radio' ? '📻' : s.source === 'spotify' ? '🎧' : s.source === 'tidal' ? '🌊' : '🎼';
      this._setText('mth', thumb);
    }
    // 음질 — 서버가 분석한 실제 코덱/샘플레이트. 분석 전 라디오는 LIVE 표기.
    let mpQuality = '—';
    if (s.source && s.source !== 'idle') {
      if (s.source === 'radio') {
        mpQuality = s.quality && s.quality !== 'RADIO' ? s.quality : 'LIVE';
      } else {
        mpQuality = s.quality || '—';
      }
    }
    this._setText('mp-quality', mpQuality);
    this._setText('player-quality', mpQuality);
    // 재생화면 하트(즐겨듣기) 아이콘 — 트랙 전환 시마다 서버 즐겨듣기 상태로 동기화
    this._syncPlayerHeart();
    // 메타 패널(곡명·작곡가·장르·파일명)은 window.cur 기준 — 상태와 라이브러리 캐시로 동기화
    this._syncWindowCurFromState(s);
  }

  _updateControls(s) {
    const playing = !!s.playing;
    const icon = playing ? '⏸' : '▶';
    this._setText('mp2', icon);
    this._setText('mpb', icon);
    const shuf = document.getElementById('shuf');
    const rep = document.getElementById('rep');
    if (shuf) shuf.style.opacity = s.shuffle ? '1' : '0.3';
    if (rep) {
      const on = s.repeat && s.repeat !== 'none';
      rep.style.opacity = on ? '1' : '0.3';
      rep.dataset.mode = s.repeat || 'none';
    }
    const vol = Math.max(0, Math.min(100, Math.round(s.volume ?? 70)));
    // 드래그 중·전송 직후 hold — 큐에 남은 옛 volume state 가 막대를 좌우로 흔들지 않게 한다.
    if (!this._volDragging && !this.api._volumeUiLocked()) {
      document.querySelectorAll('.vf').forEach((vf) => {
        vf.style.width = `${vol}%`;
      });
      this._setText('vol-pct', `${vol}%`);
    }
  }

  _updateProgress(s) {
    if (s.source === 'radio' || !s.duration) return;
    const pct = Math.min(100, Math.round((s.position / s.duration) * 100));
    ['skf', 'mpf'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.width = `${pct}%`;
    });
    this._setText('ct', WhickAPI.formatTime(s.position));
    this._setText('dt', WhickAPI.formatTime(s.duration));
  }

  /**
   * 라이브러리·즐겨듣기에서 선택해 재생한 곡들이 실제 「재생 화면」 재생목록에 표시되도록
   * 서버가 관리하는 현재 재생목록(s.queue = track_id 배열)을 그려준다.
   * 곡을 아직 재생 중이 아니고 체크만 해둔 상태(대기)의 표시는 syncQueueUi()가 담당한다.
   */
  _updateQueuePanel(s) {
    const wrap = document.getElementById('player-queue-wrap');
    const listEl = document.getElementById('player-queue-list');
    const nowEl = document.getElementById('player-queue-now');
    if (!wrap || !listEl || !nowEl) return;
    // 라디오·스트리밍(spotify/tidal) 전환 시에도 서버가 이전 라이브러리 큐를 그대로 들고 있을 수 있어
    // 라이브러리 재생일 때만 큐 패널을 보여준다.
    const queue = s.source === 'library' && Array.isArray(s.queue) ? s.queue : [];
    if (!queue.length) {
      wrap.classList.add('hd');
      listEl.innerHTML = '';
      nowEl.textContent = '—';
      const mpq = document.querySelector('.mp-q');
      if (mpq) {
        const n = this._checkChecked().size;
        mpq.textContent = n ? `선택 ${n}곡` : _t('queue.empty', '대기 0곡');
      }
      return;
    }
    if (!this._trackLists) this._trackLists = {};
    const byId = new Map();
    Object.keys(this._trackLists).forEach((k) => {
      (this._trackLists[k] || []).forEach((t) => {
        if (t && t.track_id != null) byId.set(t.track_id, t);
      });
    });
    const curIdx = queue.indexOf(s.track_id);
    wrap.classList.remove('hd');
    nowEl.textContent =
      (s.playing ? '▶ ' : '⏸ ') + (s.title || '—') + (s.artist ? ' · ' + s.artist : '');
    listEl.innerHTML = queue
      .map((tid, i) => {
        const t = byId.get(tid);
        const label = t ? t.title || '—' : _t('queue.track_n', '곡 #') + tid;
        const on = i === curIdx;
        return (
          '<div class="pq-row' +
          (on ? ' on' : '') +
          '"><span class="pq-n">' +
          (on ? '▶' : i + 1) +
          '</span><span>' +
          escapeHtml(label) +
          '</span></div>'
        );
      })
      .join('');
    const mpq = document.querySelector('.mp-q');
    if (mpq) mpq.textContent = curIdx >= 0 ? `${_t('queue.playing_n', 'Playing ')}${curIdx + 1}/${queue.length}` : `${queue.length}${_t('unit.queued', ' queued')}`;
  }

  _bindTransport() {
    const bind = (id, fn) => {
      const el = document.getElementById(id);
      if (el) el.onclick = (e) => {
        e.stopPropagation();
        fn();
      };
    };
    bind('mp2', () => this.playOrToggleFromSelection());
    bind('mpb', () => this.playOrToggleFromSelection());
    bind('shuf', () => this.api.setShuffle(!this.api.state.shuffle));
    bind('rep', () => this.api.toggleRepeat());
    bind('mobile-autoplay-banner', () => this.api.resumeMobilePlayback());

    document.querySelectorAll('.sk-tr').forEach((el) => this.bindSeek(el));
    // 재생화면·미니플레이어 볼륨 막대 — 모두 탭 + 드래그 지원
    // (재생화면에서는 하단 미니플레이어가 숨겨지므로 .vt 로 직접 조절해야 한다)
    document.querySelectorAll('.vt').forEach((el) => this.bindVolumeDrag(el));
    const miniVt = document.getElementById('mp-vt');
    if (miniVt) this.bindVolumeDrag(miniVt);
    const volHintOk = document.getElementById('vol-hint-ok');
    if (volHintOk) {
      volHintOk.addEventListener('click', () => {
        const pop = document.getElementById('vol-hint-pop');
        if (pop) pop.classList.add('hd');
        try {
          localStorage.setItem('whick_vol_hint_seen', '1');
        } catch {
          /* ignore */
        }
      });
    }
  }

  /** DAC(미니PC) 출력 볼륨 안내 — 최초 1회만 (하드웨어 버튼 누름은 웹에서 감지 불가) */
  _maybeShowVolumeHint() {
    if (this.api.isMobileOutput()) return;
    let seen = false;
    try {
      seen = localStorage.getItem('whick_vol_hint_seen') === '1';
    } catch {
      /* ignore */
    }
    if (seen) return;
    const pop = document.getElementById('vol-hint-pop');
    if (pop) pop.classList.remove('hd');
  }

  /** 포인터 드래그·탭으로 볼륨 조절 — UI 즉시, 서버는 50ms 쓰로틀 + 놓을 때 즉시 전송 */
  bindVolumeDrag(track) {
    const fill = track.querySelector('.mp-vf') || track.querySelector('.vf');
    let lastSentAt = 0;
    let lastSentPct = null;
    const pctFromEvent = (clientX) => {
      const r = track.getBoundingClientRect();
      if (!r.width) return 0;
      return Math.max(0, Math.min(100, Math.round(((clientX - r.left) / r.width) * 100)));
    };
    const paint = (pct) => {
      if (fill) fill.style.width = `${pct}%`;
      this._setText('vol-pct', `${pct}%`);
    };
    const sendVol = (pct, { force = false } = {}) => {
      const now = Date.now();
      if (!force && pct === lastSentPct && now - lastSentAt < 50) return;
      lastSentPct = pct;
      lastSentAt = now;
      this.api.setVolume(pct, { optimistic: false, force });
    };
    track.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      this._volDragging = true;
      try {
        track.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
      const pct = pctFromEvent(e.clientX);
      paint(pct);
      sendVol(pct, { force: true });
    });
    track.addEventListener('pointermove', (e) => {
      if (!this._volDragging) return;
      const pct = pctFromEvent(e.clientX);
      paint(pct);
      if (Date.now() - lastSentAt >= 50) sendVol(pct);
    });
    const end = (e) => {
      if (!this._volDragging) return;
      const pct = pctFromEvent(e.clientX);
      paint(pct);
      // hold 먼저 건 뒤 드래그 해제 — 직후 도착하는 옛 state 가 막대를 덮지 않음
      sendVol(pct, { force: true });
      this._volDragging = false;
    };
    track.addEventListener('pointerup', end);
    track.addEventListener('pointercancel', () => {
      if (lastSentPct != null) {
        this.api._volumeHoldUntil = Date.now() + 650;
      }
      this._volDragging = false;
    });
  }

  bindSeek(el) {
    el.addEventListener('click', (e) => {
      const r = el.getBoundingClientRect();
      const pct = (e.clientX - r.left) / r.width;
      const dur = this.api.state.duration || 0;
      if (dur) this.api.seek(Math.round(pct * dur));
    });
  }

  bindVolume(el) {
    el.addEventListener('click', (e) => {
      const r = el.getBoundingClientRect();
      this.api.setVolume(Math.round(((e.clientX - r.left) / r.width) * 100));
    });
  }

  async _loadDashboard() {
    try {
      const data = await this.api.getDashboard();
      this._renderHomeDashboard(data);
    } catch (e) {
      console.warn('[WhickUI] dashboard', e);
    }
  }

  _renderHomeDashboard(data) {
    const lib = data.library || {};
    const dash = document.getElementById('dash-lib');
    if (dash) {
      dash.innerHTML = `
        <div class="ssh"><div class="sst">${window._t('lib.title', '라이브러리')}</div><div class="ssb"><div class="dot on"></div>LIVE</div></div>
        <div class="ssg">
          <div class="ssi"><div class="ssv">${lib.tracks ?? 0}</div><div class="ssl">${window._t('lib.stats_tracks', _t('unit.tracks', '곡'))}</div></div>
          <div class="ssi"><div class="ssv">${lib.albums ?? 0}</div><div class="ssl">${window._t('lib.stats_albums', '앨범')}</div></div>
          <div class="ssi"><div class="ssv">${lib.artists ?? 0}</div><div class="ssl">${window._t('lib.stats_artists', '아티스트')}</div></div>
        </div>`;
    }
    const ai = data.ai || {};
    const aiBadge = document.getElementById('dash-ai');
    if (aiBadge) {
      aiBadge.textContent = ai.ok ? `AI ${ai.model || 'gemma4:e2b'}` : _t('ai.offline', 'AI 오프라인');
      aiBadge.style.color = ai.ok ? 'var(--teal)' : 'var(--amber)';
    }
    this._renderRecentHome(data.recent || []);
    this._renderPlaylistHome(data.playlists || []);
    this.refreshLibraryStatus();
  }

  _renderRecentHome(tracks) {
    const el = document.getElementById('rec');
    if (!el) return;
    if (!tracks.length) {
      el.innerHTML =
        '<div style="padding:16px;color:var(--text3);font-size:12px;text-align:center">' + window._t('lib.no_history', '아직 재생 이력이 없습니다') + '</div>';
      return;
    }
    el.innerHTML = tracks
      .map(
        (t, i) => `
      <div class="ri" onclick="window._api.playQueue([${t.track_id}], ${t.track_id})">
        <div class="ri-n">${i + 1}</div>
        <div class="ri-th" style="background:linear-gradient(135deg,#1a3a4a,#0d6e55)">🎵</div>
        <div class="ri-in"><div class="ri-ti">${t.title}</div><div class="ri-su">${t.artist || ''}</div></div>
        <div class="ri-q">${WhickAPI.qualityLabel(t)}</div>
      </div>`,
      )
      .join('');
  }

  _renderPlaylistHome(playlists) {
    const el = document.getElementById('home-playlists');
    if (!el) return;
    if (!playlists.length) {
      el.innerHTML =
        '<div style="padding:12px 0;color:var(--text3);font-size:12px">' + _t('pl.empty', 'No playlists · add tracks with ➕ while playing') + '</div>';
      return;
    }
    el.innerHTML = playlists
      .slice(0, 6)
      .map(
        (p) => `
      <div class="hcard" onclick="window._uiBridge.loadPlaylistTracks(${p.playlist_id})">
        <div class="hc-ic">📋</div>
        <div class="hc-t">${p.name}</div>
        <div class="hc-d">${p.track_count || 0} ${_t('unit.tracks_short', 'tracks')}</div>
      </div>`,
      )
      .join('');
  }

  async loadPlaylistTracks(playlistId) {
    const data = await this.api.getPlaylistTracks(playlistId);
    const tracks = data.tracks || [];
    if (this._listOffset) this._listOffset.tlist = 0;
    this._hideLibPager();
    this._renderTracks(tracks, 'tlist', tracks.map((t) => t.track_id));
    go('library', _t('nav.library', '라이브러리'));
    document.querySelectorAll('.lt').forEach((t, i) => t.classList.toggle('on', i === 0));
    document.querySelectorAll('[id^=lib-]').forEach((x) => x.classList.add('hd'));
    document.getElementById('lib-all')?.classList.remove('hd');
  }

  async _loadLibraryEssentials(page) {
    try {
      const perPage = 20;
      const cur = Math.max(1, Number(page || this._libPage || 1) || 1);
      this._libPage = cur;
      const [tracksData] = await Promise.all([
        this.api.getTracks(cur, 'title', perPage),
        this._ensureFavIds(),
      ]);
      const total = Number(tracksData.total || 0);
      const pages = Math.max(1, Math.ceil(total / perPage) || 1);
      if (cur > pages) {
        this._libPage = pages;
        return this._loadLibraryEssentials(pages);
      }
      if (!this._listOffset) this._listOffset = {};
      this._listOffset.tlist = (this._libPage - 1) * perPage;
      this._renderTracks(tracksData.tracks || []);
      this._updateLibPager(total, this._libPage, perPage);
    } catch (e) {
      console.error('[WhickUI] library tracks', e);
    }
  }

  /** 라이브러리 전체 목록 페이지 이동 (20곡/페이지) */
  _gotoLibPage(page) {
    const next = Math.max(1, Number(page) || 1);
    if (next === this._libPage) return;
    this._libPage = next;
    this._loadLibraryEssentials(next).then(() => {
      document.getElementById('tlist')?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
    });
  }

  _updateLibPager(total, page, perPage) {
    const bar = document.getElementById('lib-pager');
    const info = document.getElementById('lib-pg-info');
    const prev = document.getElementById('lib-pg-prev');
    const next = document.getElementById('lib-pg-next');
    if (!bar || !info || !prev || !next) return;
    const pages = Math.max(1, Math.ceil((Number(total) || 0) / (perPage || 20)) || 1);
    const cur = Math.min(Math.max(1, Number(page) || 1), pages);
    if (total <= perPage) {
      bar.classList.add('hd');
      return;
    }
    bar.classList.remove('hd');
    info.textContent = `${cur} / ${pages} · ${total} ${_t('unit.tracks_short', 'tracks')}`;
    prev.disabled = cur <= 1;
    next.disabled = cur >= pages;
    prev.onclick = () => this._gotoLibPage(cur - 1);
    next.onclick = () => this._gotoLibPage(cur + 1);
  }

  _hideLibPager() {
    document.getElementById('lib-pager')?.classList.add('hd');
  }

  /** 서버 즐겨듣기 track_id 집합을 최초 1회 로드(캐시). 하트 아이콘을 동기 렌더하기 위함. */
  async _ensureFavIds() {
    if (this._favIds) return this._favIds;
    if (this._favIdsLoading) return this._favIdsLoading; // 동시 호출 시 하나의 요청만 발행 (single-flight)
    this._favIdsLoading = (async () => {
      try {
        const data = await this.api.getFavorites();
        this._favIds = new Set((data.tracks || []).map((t) => Number(t.track_id)));
      } catch (e) {
        console.warn('[WhickUI] favorites preload', e);
        this._favIds = new Set();
      }
      this._favIdsLoading = null;
      // _updateNowPlaying에서 isServerFav를 먼저 호출했을 때 favIds가 null이면 🤍로 그려졌을 수 있다.
      // favIds 준비가 끝났으므로 재생화면 하트를 다시 동기화한다.
      this._syncPlayerHeart();
      return this._favIds;
    })();
    return this._favIdsLoading;
  }

  isServerFav(trackId) {
    const tid = Number(trackId);
    return !!(this._favIds && this._favIds.has(tid));
  }

  /** 재생화면 하트(#lk)를 현재 재생곡의 서버 즐겨듣기 상태로 동기화 */
  _syncPlayerHeart() {
    const lk = document.getElementById('lk');
    if (!lk) return;
    const s = this.api.stateCache || {};
    // radio/spotify/tidal은 즐겨듣기 대상이 아니므로 무조건 🤍
    if (s.source !== 'library') { lk.textContent = '🤍'; lk.classList.remove('lk'); return; }
    const tid = Number(s.track_id);
    if (!tid) { lk.textContent = '🤍'; lk.classList.remove('lk'); return; }
    const on = this.isServerFav(tid);
    lk.textContent = on ? '❤️' : '🤍';
    lk.classList.toggle('lk', on);
  }

  /** 라이브러리·재생화면 하트 클릭 → 서버 즐겨듣기(전체 즐겨듣기) 토글 */
  async toggleTrackFav(trackId) {
    const tid = Number(trackId);
    if (!tid) return;
    if (!this._favToggleBusy) this._favToggleBusy = new Set();
    if (this._favToggleBusy.has(tid)) return; // double-click 방지: 이미 처리 중
    this._favToggleBusy.add(tid);
    try {
      await this._ensureFavIds();
      const wasFav = this._favIds.has(tid);
      try {
        if (wasFav) {
          await this.api.removeFavorite(tid);
          this._favIds.delete(tid);
        } else {
          await this.api.addFavorite(tid);
          this._favIds.add(tid);
        }
      } catch (e) {
        console.error('[WhickUI] toggleTrackFav', e);
        return;
      }
      // 라이브러리·즐겨듣기 목록에 렌더된 하트 아이콘 갱신
      if (this._trackLists) {
        Object.keys(this._trackLists).forEach((listId) => {
          this._renderTracks(this._trackLists[listId], listId);
        });
      }
      // 재생화면 하트도 즉시 반영 — 현재 재생곡이 토글된 트랙이면 즉시 업데이트
      if (Number(this.api.stateCache?.track_id) === tid) this._syncPlayerHeart();
      // 「전체 즐겨듣기」 화면이 열려 있으면 곡수·목록도 함께 갱신
      if (typeof libSubTab !== 'undefined' && libSubTab === 'fav') this._loadFavorites();
    } finally {
      this._favToggleBusy.delete(tid);
    }
  }

  async ensureLibraryTab(tab) {
    if (!this._libraryTabLoaded) this._libraryTabLoaded = {};
    if (this._libraryTabLoaded[tab]) return;
    this._libraryTabLoaded[tab] = true;
    try {
      if (tab === 'artist') {
        const data = await this.api.getArtists();
        this._renderArtists(data.artists || []);
      } else if (tab === 'album') {
        const data = await this.api.getAlbums();
        this._renderAlbums(data.albums || []);
      } else if (tab === 'composer') {
        const data = await this.api.getComposers();
        this._renderComposers(data.composers || []);
      } else if (tab === 'genre') {
        const data = await this.api.getGenres();
        this._renderGenreHub(data.genres || []);
      } else if (tab === 'fav') {
        await this._loadFavorites();
      } else if (tab === 'history') {
        await this._loadHistory();
      }
    } catch (e) {
      this._libraryTabLoaded[tab] = false;
      console.error('[WhickUI] library tab', tab, e);
    }
  }

  async _loadLibrary() {
    const active = this._activeLibraryTab || 'all';
    this._libraryTabLoaded = {};
    await this._loadLibraryEssentials();
    if (active !== 'all') {
      await this.ensureLibraryTab(active);
    }
  }

  async _loadFavorites() {
    try {
      const data = await this.api.getFavorites();
      const tracks = data.tracks || [];
      this._favIds = new Set(tracks.map((t) => Number(t.track_id)));
      this._renderTracks(tracks, 'flist');
      const cnt = document.getElementById('fav-all-cnt');
      if (cnt) cnt.textContent = `(${tracks.length} ${_t('unit.tracks_short', 'tracks')})`;
    } catch (e) {
      console.warn('[WhickUI] favorites', e);
    }
  }

  async _loadHistory() {
    try {
      const data = await this.api.getHistory();
      this._renderTracks(data.tracks || [], 'hlist');
    } catch (e) {
      console.warn('[WhickUI] history', e);
    }
  }

  _radioStationRow(s) {
    const sid = String(s?.id || '').trim();
    if (!sid) return null;
    const selected = this._radioOnId != null && String(this._radioOnId) === sid;
    const row = document.createElement('div');
    row.className = selected ? 'rc on' : 'rc';
    row.setAttribute('data-sid', sid);
    row.addEventListener('click', () => {
      this._setRadioSelection(sid);
      this.api.playRadio(sid).catch(console.error);
    });
    const icon = document.createElement('div');
    icon.className = 'rl';
    icon.textContent = s.emoji || '📻';
    const info = document.createElement('div');
    info.className = 'ri2';
    const name = document.createElement('div');
    name.className = 'rn';
    name.textContent = (typeof window._radioN === 'function') ? window._radioN(s.name || sid) : (s.name || sid);
    const desc = document.createElement('div');
    desc.className = 'rd';
    const descParts = [];
    if (s.org) descParts.push(window._t('radio.org_' + s.org, String(s.org)));
    if (s.desc) descParts.push((typeof window._radioD === 'function') ? window._radioD(s.desc) : window._t('radio.desc_' + s.id, String(s.desc)));
    desc.textContent = descParts.join(' · ');
    info.appendChild(name);
    info.appendChild(desc);
    const live = document.createElement('div');
    live.className = 'rlv';
    live.textContent = selected ? window._t('radio.playing', '▶ 재생중') : 'LIVE';
    row.appendChild(icon);
    row.appendChild(info);
    row.appendChild(live);
    return row;
  }

  _setRadioSelection(stationId) {
    const sid = stationId != null ? String(stationId).trim() : '';
    this._radioOnId = sid || null;
    if (typeof radioOnId !== 'undefined') {
      try {
        radioOnId = this._radioOnId;
      } catch (_) {
        /* ignore */
      }
    }
    document.querySelectorAll('.rc[data-sid]').forEach((row) => {
      const on = !!sid && row.getAttribute('data-sid') === sid;
      row.classList.toggle('on', on);
      const badge = row.querySelector('.rlv');
      if (badge) badge.textContent = on ? _t('player.now_playing', '▶ 재생중') : 'LIVE';
    });
  }

  _syncRadioSelectionFromState(s) {
    if (!s) return;
    if (s.source === 'radio' && s.radio_station_id) {
      this._setRadioSelection(s.radio_station_id);
      return;
    }
    // 라디오가 아니면 선택 표시만 유지(목록 재로드 시 복원용). 강제 해제는 하지 않음.
  }

  _fillRadioList(el, stations, emptyText) {
    if (!el) return;
    el.replaceChildren();
    const list = Array.isArray(stations) ? stations : [];
    if (!list.length) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding:16px 8px;color:var(--text3);text-align:center;font-size:13px';
      empty.textContent = emptyText;
      el.appendChild(empty);
      return;
    }
    list.forEach((s) => {
      const row = this._radioStationRow(s);
      if (row) el.appendChild(row);
    });
  }

  _renderRadioStations(stations) {
    const list = Array.isArray(stations) ? stations : [];
    this._radioStationsCache = list;
    const cat = (s) => String(s?.category || 'terrestrial');
    const ground = list.filter((s) => cat(s) === 'terrestrial');
    const net = list.filter((s) => cat(s) === 'internet');
    const hires = list.filter((s) => cat(s) === 'hires');
    const groundEl = document.getElementById('rlist-ground');
    const netEl = document.getElementById('rlist-net');
    const hiresEl = document.getElementById('rlist-hires');
    // 구 UI(#rlist) 호환
    const legacyEl = document.getElementById('rlist');
    if (legacyEl && !groundEl && !netEl && !hiresEl) {
      this._fillRadioList(legacyEl, list, _t('radio.load_failed', '방송국 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.'));
      return;
    }
    this._fillRadioList(
      groundEl,
      ground,
      list.length ? _t('radio.no_terrestrial', '지상파 방송국이 없습니다.') : _t('radio.load_failed', '방송국 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.'),
    );
    this._fillRadioList(
      netEl,
      net,
      list.length ? _t('radio.no_internet', '인터넷 라디오 방송국이 없습니다.') : _t('radio.load_failed', '방송국 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.'),
    );
    this._fillRadioList(
      hiresEl,
      hires,
      list.length ? _t('radio.no_hires', 'Hi-Res 음악전문방송국이 없습니다.') : _t('radio.load_failed', '방송국 목록을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.'),
    );
  }

  async _loadRadio() {
    try {
      let stations = [];
      try {
        const data = await this.api.getRadioStations();
        stations = normalizeRadioStations(data);
      } catch (e) {
        console.warn('[WhickUI] radio fetch', e);
      }
      if (!stations.length) {
        stations = WHICK_RADIO_STATIONS_FALLBACK;
      }
      const s = this.api?.stateCache || {};
      if (s.source === 'radio' && s.radio_station_id) {
        this._radioOnId = String(s.radio_station_id);
      }
      this._renderRadioStations(stations);
    } catch (e) {
      console.warn('[WhickUI] radio', e);
      this._renderRadioStations(WHICK_RADIO_STATIONS_FALLBACK);
    }
  }

  _renderTracks(tracks, listId = 'tlist', queueIds = null) {
    const el = document.getElementById(listId);
    if (!el) return;
    if (!this._trackLists) this._trackLists = {};
    this._trackLists[listId] = tracks;
    this._checkChecked();
    this._collectionChecked();

    const isStream = (t) =>
      t.source === 'spotify' || t.source === 'tidal' || (t.stream_id && !t.track_id);
    const localItems = tracks.filter((t) => !isStream(t));
    const q = queueIds || localItems.map((t) => t.track_id);
    // 즐겨듣기 목록의 체크와 모음 편집 중 라이브러리 체크만 모음용이다.
    // 즐겨듣기 탭이 열렸다는 이유로 숨겨진 일반 라이브러리 체크까지 덮어쓰지 않는다.
    const useColl =
      listId === 'flist' ||
      listId === 'fav-detail-tracks' ||
      (typeof editingBoard !== 'undefined' && !!editingBoard);
    const checkSrc = useColl ? this._collectionChecked() : this._checkChecked();

    if (!tracks.length) {
      el.innerHTML =
        listId === 'flist'
          ? '<div style="text-align:center;padding:48px 16px;color:var(--text3)"><div style="font-size:40px;margin-bottom:12px">🤍</div><div style="font-size:13px;color:var(--text2)">' + window._t('lib.no_liked', '좋아요한 곡이 없습니다') + '</div></div>'
          : '<div style="padding:24px;color:var(--text3);text-align:center">' + window._t('lib.no_tracks', '곡 없음') + '</div>';
      return;
    }
    el.innerHTML = tracks
      .map((t, i) => {
        const tid = t.track_id;
        const streaming = isStream(t);
        const badge =
          t.source === 'spotify'
            ? '🎧 Spotify'
            : t.source === 'tidal'
              ? '🌊 Tidal'
              : WhickAPI.qualityLabel(t);
        const icon =
          t.source === 'spotify' ? '🎧' : t.source === 'tidal' ? '🌊' : '🎵';
        const checked = checkSrc.has(tid);
        const inFavCollection = listId === 'fav-detail-tracks';
        const heartAction = inFavCollection
          ? `removeTrackFromOpenFavBoard(${tid})`
          : `toggleTrackFav(${tid})`;
        const heart = inFavCollection || this.isServerFav(tid) ? '❤️' : '🤍';
        const dur = WhickAPI.formatTime(t.duration_sec || 0);
        const metaOpen = this._metaOpenKey === `${listId}:${i}`;
        return `<div class="ti2-wrap" data-tid="${tid}">
        <div class="ti2${metaOpen ? ' open' : ''}" data-idx="${i}" data-list="${listId}">
          <label class="ti2-chk" onclick="event.stopPropagation()">
            <input type="checkbox"${checked ? ' checked' : ''} onchange="window._uiBridge.toggleTrackCheck(${tid},this.checked)">
          </label>
          <div class="ti2-n" onclick="event.stopPropagation();window._uiBridge.toggleRenderedTrackMeta('${listId}',${i})">${(this._listOffset?.[listId] || 0) + i + 1}</div>
          <span style="font-size:22px;flex-shrink:0" onclick="event.stopPropagation();window._uiBridge.toggleRenderedTrackMeta('${listId}',${i})">${icon}</span>
          <div class="ti2-in" onclick="event.stopPropagation();window._uiBridge.toggleRenderedTrackMeta('${listId}',${i})">
            <div class="ti2-t">${escapeHtml(t.title)}</div>
            <div class="ti2-s">${escapeHtml(t.artist)}${t.album ? ' · ' + escapeHtml(t.album) : ''}</div>
          </div>
          <div class="ti2-r">
            <button type="button" class="ti2-fav-btn${heart === '❤️' ? ' on' : ''}" onclick="event.stopPropagation();${heartAction}" aria-label="${inFavCollection ? _t('lib.remove_from_collection', '모음에서 제거') : _t('lib.favorites', '즐겨듣기')}">${heart}</button>
            <div class="ti2-d" onclick="event.stopPropagation();window._uiBridge.toggleRenderedTrackMeta('${listId}',${i})">${dur}</div>
            <div class="ti2-q" onclick="event.stopPropagation();window._uiBridge.toggleRenderedTrackMeta('${listId}',${i})">${escapeHtml(badge)}${t.format ? ' · ' + escapeHtml(String(t.format).toUpperCase()) : ''}</div>
          </div>
        </div>
        <div class="ti2-acc${metaOpen ? '' : ' hd'}">
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_title', '곡명')}</span><span class="meta-v">${escapeHtml(t.title || '—')}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_artist', '아티스트')}</span><span class="meta-v">${escapeHtml(t.artist || '—')}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_album', '앨범')}</span><span class="meta-v">${escapeHtml(t.album || '—')}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_composer', '작곡가')}</span><span class="meta-v">${escapeHtml(t.composer || '—')}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_genre', '장르')}</span><span class="meta-v">${escapeHtml(t.genre || '—')}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_filename', '파일명')}</span><span class="meta-v">${escapeHtml(t.filename || (t.file_path ? String(t.file_path).split('/').pop() : '') || '—')}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_format', '포맷')}</span><span class="meta-v">${escapeHtml(badge)}${t.format ? ' · ' + escapeHtml(String(t.format).toUpperCase()) : ''}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_length', '길이')}</span><span class="meta-v">${dur}</span></div>
          <div class="meta-row"><span class="meta-k">${window._t('lib.meta_plays', '재생')}</span><span class="meta-v">${Number(t.play_count || 0)}${window._t('lib.meta_times', '회')}</span></div>
        </div>
      </div>`;
      })
      .join('');
    this._bindTrackListLongPress(listId);
  }

  _bindTrackListLongPress(listId) {
    const el = document.getElementById(listId);
    if (!el) return;
    // innerHTML 교체 후 리스너는 사라지므로 매 렌더마다 다시 붙인다
    const PRESS_MS = 480;
    let timer = null;
    let startX = 0;
    let startY = 0;
    let armed = false;

    const clear = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      armed = false;
    };

    const onPressStart = (ev, wrap) => {
      if (!wrap) return;
      // 체크박스·하트는 길게누르기 제외
      if (ev.target.closest('label.ti2-chk, .ti2-fav-btn, button, input')) return;
      const point = ev.touches ? ev.touches[0] : ev;
      startX = point.clientX;
      startY = point.clientY;
      armed = true;
      clear();
      timer = setTimeout(() => {
        timer = null;
        if (!armed) return;
        armed = false;
        const tid = Number(wrap.getAttribute('data-tid'));
        if (!tid) return;
        try {
          if (navigator.vibrate) navigator.vibrate(12);
        } catch {
          /* ignore */
        }
        this._openLibTrackMenu(listId, tid, {
          x: point.clientX,
          y: point.clientY,
        });
      }, PRESS_MS);
    };

    const onMove = (ev) => {
      if (!timer && !armed) return;
      const point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;
      if (Math.abs(point.clientX - startX) > 12 || Math.abs(point.clientY - startY) > 12) {
        clear();
      }
    };

    el.querySelectorAll('.ti2-wrap[data-tid]').forEach((wrap) => {
      wrap.addEventListener(
        'touchstart',
        (ev) => onPressStart(ev, wrap),
        { passive: true },
      );
      wrap.addEventListener('touchmove', onMove, { passive: true });
      wrap.addEventListener('touchend', clear);
      wrap.addEventListener('touchcancel', clear);
      wrap.addEventListener('mousedown', (ev) => {
        if (ev.button !== 0) return;
        onPressStart(ev, wrap);
      });
      wrap.addEventListener('mousemove', onMove);
      wrap.addEventListener('mouseup', clear);
      wrap.addEventListener('mouseleave', clear);
      wrap.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        const tid = Number(wrap.getAttribute('data-tid'));
        if (!tid) return;
        this._openLibTrackMenu(listId, tid, { x: ev.clientX, y: ev.clientY });
      });
    });
  }

  _hideLibTrackMenu() {
    document.getElementById('lib-ctx')?.setAttribute('hidden', '');
    document.getElementById('lib-ctx-scrim')?.setAttribute('hidden', '');
  }

  _ensureLibTrackMenuBound() {
    if (this._libCtxBound) return;
    this._libCtxBound = true;
    document.getElementById('lib-ctx-scrim')?.addEventListener('click', () => this._hideLibTrackMenu());
    document.getElementById('lib-ctx')?.addEventListener('click', (ev) => {
      const btn = ev.target.closest('button[data-act]');
      if (!btn) return;
      const act = btn.getAttribute('data-act');
      this._hideLibTrackMenu();
      if (act === 'cancel') return;
      this._runLibTrackMenuAct(act).catch((e) => {
        alert(e?.message || String(e));
      });
    });
  }

  _selectedIdsForMenu(listId, pressedTid) {
    const coll = this._isCollectionCheckMode();
    const set = coll ? this._collectionChecked() : this._checkChecked();
    let ids = [...set].map(Number).filter((n) => n > 0);
    if (!ids.length && pressedTid) {
      // 미선택 상태에서 길게 누른 곡만 대상
      ids = [Number(pressedTid)];
      if (coll) {
        this._collectionChecked().add(Number(pressedTid));
        this._syncRenderedChecks(true);
      } else {
        this._checkChecked().add(Number(pressedTid));
        this.api.setQueue([...this._checkChecked()]);
        this._syncRenderedChecks(false);
      }
    } else if (pressedTid && !ids.includes(Number(pressedTid))) {
      // 다른 곡들이 선택된 상태에서 미선택 행을 길게 누르면 그 행을 선택에 포함
      ids.push(Number(pressedTid));
      if (coll) this._collectionChecked().add(Number(pressedTid));
      else {
        this._checkChecked().add(Number(pressedTid));
        this.api.setQueue([...this._checkChecked()]);
      }
      this._syncRenderedChecks(!!coll);
    }
    return ids;
  }

  _openLibTrackMenu(listId, pressedTid, pos) {
    this._ensureLibTrackMenuBound();
    const ids = this._selectedIdsForMenu(listId, pressedTid);
    this._libMenuIds = ids;
    this._libMenuListId = listId;
    const head = document.getElementById('lib-ctx-head');
    if (head) head.textContent = `${ids.length} ${_t('unit.tracks_short', 'tracks')} ${_t('unit.selected', 'selected')}`;
    const menu = document.getElementById('lib-ctx');
    const scrim = document.getElementById('lib-ctx-scrim');
    if (!menu || !scrim) return;
    // 즐겨찾기 모음 모드면 삭제 문구 변경
    const delBtn = menu.querySelector('button[data-act="delete"]');
    if (delBtn) {
      if (this._isCollectionCheckMode()) {
        delBtn.textContent = _t('lib.unfav_selected', '선택곡 즐겨찾기에서 제거');
        delBtn.classList.remove('lib-ctx-danger');
      } else {
        delBtn.textContent = _t('lib.remove_list_only', '목록에서만 제거');
        delBtn.classList.add('lib-ctx-danger');
      }
    }
    const favBtn = menu.querySelector('button[data-act="fav"]');
    if (favBtn) favBtn.hidden = !!this._isCollectionCheckMode();
    scrim.removeAttribute('hidden');
    menu.removeAttribute('hidden');
    // 기본은 하단 중앙. 데스크톱 우클릭 시 포인터 근처
    if (pos && pos.x != null && window.matchMedia('(pointer:fine)').matches) {
      const w = menu.offsetWidth || 240;
      const h = menu.offsetHeight || 200;
      let left = pos.x - w / 2;
      let top = pos.y - h - 8;
      left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
      top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
      menu.style.bottom = 'auto';
      menu.style.transform = 'none';
    } else {
      menu.style.left = '50%';
      menu.style.top = 'auto';
      menu.style.bottom = 'calc(var(--player-h) + var(--nav-h) + 12px)';
      menu.style.transform = 'translateX(-50%)';
    }
  }

  async _runLibTrackMenuAct(act) {
    const ids = (this._libMenuIds || []).map(Number).filter((n) => n > 0);
    if (!ids.length) return;
    if (act === 'play') {
      if (this._isCollectionCheckMode()) {
        // 모음 체크는 재생 큐와 분리 — 일시적으로 재생 큐에 넣고 재생
        this._checkChecked().clear();
        ids.forEach((id) => this._checkChecked().add(id));
        this.api.setQueue([...this._checkChecked()]);
      }
      this.playCheckedTracks();
      return;
    }
    if (act === 'fav') {
      await Promise.all(
        ids.map(async (id) => {
          if (!this.isServerFav(id)) await this.toggleTrackFav(id);
        }),
      );
      if (typeof libToast === 'function') libToast(`${ids.length} ${_t('unit.tracks_short', 'tracks')} ${_t('lib.fav_added', 'added to favorites')}`);
      return;
    }
    if (act === 'delete') {
      if (this._isCollectionCheckMode()) {
        // 즐겨듣기/모음에서만 제거
        if (typeof openBoard !== 'undefined' && openBoard && openBoard.type === 'fav') {
          const b = typeof getBoard === 'function' ? getBoard(openBoard.id) : null;
          if (b) {
            b.trackIds = (b.trackIds || []).filter((tid) => !ids.some((d) => Number(d) === Number(tid)));
            if (typeof saveBoards === 'function') saveBoards();
          }
        } else {
          await Promise.all(
            ids.map(async (id) => {
              if (this.isServerFav(id)) await this.toggleTrackFav(id);
            }),
          );
        }
        this._collectionChecked().clear();
        this._syncRenderedChecks(true);
        if (typeof rFav === 'function') rFav();
        if (typeof libToast === 'function') libToast(`${ids.length} ${_t('unit.tracks_short', 'tracks')} ${_t('lib.removed', 'removed')}`);
        return;
      }
      if (
        !confirm(
          `${_t('lib.remove_shortcuts_q', 'Remove')} ${ids.length} ${_t('unit.tracks_short', 'tracks')} ${_t('lib.remove_shortcuts_only', 'from the library list (shortcuts) only?')}\n\n· 음원 파일은 그대로 남습니다\n· 실제 파일 삭제는 설정 → 파일 탐색기에서만 가능합니다\n· 다시 등록하면 목록에 돌아옵니다`,
        )
      ) {
        return;
      }
      let deleted = 0;
      try {
        const r = await this.api.deleteLibraryTracks(ids);
        deleted = Number(r.deleted || 0);
      } catch (e) {
        const msg = e?.message || String(e);
        alert(
          _t('lib.remove_failed_msg', '라이브러리 목록 제거에 실패했습니다.\n음원 파일은 건드리지 않았습니다.\n\n') + msg,
        );
        return;
      }
      ids.forEach((id) => this._checkChecked().delete(id));
      this.api.setQueue([...this._checkChecked()]);
      if (this._favIds) ids.forEach((id) => this._favIds.delete(Number(id)));
      await this._loadLibraryEssentials(this._libPage || 1);
      if (typeof libToast === 'function') {
        libToast(`${_t('lib.removed_from_list', 'Removed from list')} ${deleted || ids.length} ${_t('unit.tracks_short', 'tracks')} · ${_t('lib.files_kept', 'files kept')}`);
      }
    }
  }

  playSingleTrack(listId, index) {
    this.playRenderedTrack(listId, index);
  }

  /** 곡 행 클릭 → 메타데이터 아코디언 (▶ 버튼만 재생) */
  toggleRenderedTrackMeta(listId, index) {
    const key = `${listId}:${index}`;
    this._metaOpenKey = this._metaOpenKey === key ? null : key;
    const root = document.getElementById(listId);
    if (!root) return;
    root.querySelectorAll('.ti2-wrap').forEach((wrap) => {
      const row = wrap.querySelector('.ti2');
      const acc = wrap.querySelector('.ti2-acc');
      const idx = Number(row?.getAttribute('data-idx'));
      const open = this._metaOpenKey === `${listId}:${idx}`;
      row?.classList.toggle('open', open);
      acc?.classList.toggle('hd', !open);
    });
  }

  /** 즐겨듣기 탭·모음 수정 중 — 체크는 모음용, 재생대기열과 분리 */
  _isCollectionCheckMode() {
    return (
      this._activeLibraryTab === 'fav' ||
      (typeof libSubTab !== 'undefined' && libSubTab === 'fav') ||
      (typeof editingBoard !== 'undefined' && !!editingBoard)
    );
  }

  toggleTrackCheck(tid, checked) {
    tid = Number(tid);
    if (this._isCollectionCheckMode()) {
      const s = this._collectionChecked();
      if (checked) s.add(tid);
      else s.delete(tid);
      this._syncCheckUI();
      return;
    }
    this._checkChecked();
    if (checked) this._checkedTracks.add(tid);
    else this._checkedTracks.delete(tid);
    this.api.setQueue([...this._checkedTracks]);
    this._syncCheckUI();
  }

  _checkChecked() {
    return this._checkedTracks || (this._checkedTracks = new Set());
  }

  _collectionChecked() {
    return this._favCheckedTracks || (this._favCheckedTracks = new Set());
  }

  _syncCheckUI() {
    const playCnt = this._checkChecked().size;
    const collCnt = this._collectionChecked().size;
    const onFav =
      this._activeLibraryTab === 'fav' ||
      (typeof libSubTab !== 'undefined' && libSubTab === 'fav');
    const editing = typeof editingBoard !== 'undefined' && !!editingBoard;
    const selCnt = document.getElementById('lib-sel-cnt');
    if (selCnt) {
      const n = onFav ? 0 : playCnt;
      selCnt.textContent = n ? `${n}` : '';
      selCnt.classList.toggle('hd', onFav || !n);
    }
    const mpq = document.getElementById('mp-q');
    if (mpq && !onFav) {
      const s = this.api?.stateCache || {};
      const qlen = Array.isArray(s.queue) ? s.queue.length : playCnt;
      if (!(s.source === 'library' && s.playing && s.track_id)) {
        mpq.textContent = playCnt ? `${_t('queue.selected_n', 'Selected ')}${playCnt}` : `${_t('queue.queued_n', 'Queued ')}${qlen || 0}`;
      }
    }
    const applyBtn = document.getElementById('edit-apply-btn');
    if (applyBtn && editing) {
      applyBtn.classList.toggle('hd', false);
      applyBtn.textContent = _t('lib.reflected', '✓ 목록에 반영') + (collCnt ? ` (${collCnt}곡)` : '');
    }
  }

  /** 미니플레이어 ▶ — 선택곡이 있으면 그 큐를 재생, 재생 중이면 일시정지 */
  playOrToggleFromSelection() {
    const ids = [...this._checkChecked()];
    const s = this.api.stateCache || {};
    const tid = s.track_id != null ? Number(s.track_id) : null;
    const inSel = tid != null && ids.includes(tid);
    if (s.playing) {
      this.api.toggle();
      return;
    }
    if (ids.length) {
      if (inSel && s.source === 'library') {
        this.api.toggle();
        return;
      }
      this.playCheckedTracks();
      return;
    }
    this.api.toggle();
  }

  _syncCheckedFromQueue(state) {
    if (state?.source !== 'library' || !Array.isArray(state.queue)) return;
    const next = new Set(state.queue.map((id) => Number(id)).filter((id) => id > 0));
    this._checkedTracks = next;
    // 즐겨듣기(#lib-fav) 체크는 모음용 — 재생 큐로 덮어쓰지 않음
    document.querySelectorAll('.ti2-wrap[data-tid] input[type=checkbox]').forEach((cb) => {
      const wrap = cb.closest('.ti2-wrap');
      if (wrap?.closest('#lib-fav')) return;
      if (typeof editingBoard !== 'undefined' && editingBoard) return;
      const tid = Number(wrap?.getAttribute('data-tid'));
      cb.checked = next.has(tid);
    });
    this._syncCheckUI();
  }

  /** 현재 라이브러리 탭에서 곡 행이 그려지는 list id */
  _activeLibTrackListId() {
    const tab = typeof libSubTab !== 'undefined' && libSubTab ? libSubTab : 'all';
    if (tab === 'genre') return 'genre-tlist';
    if (tab === 'composer') return 'composer-tlist';
    return 'tlist';
  }

  /** 전체 탭: 페이지(20곡)가 아니라 라이브러리 전체 track_id */
  async _fetchAllLibraryTrackIds() {
    const perPage = 200;
    const ids = [];
    let page = 1;
    let total = Infinity;
    while (ids.length < total && page <= 200) {
      const data = await this.api.getTracks(page, 'title', perPage);
      total = Number(data.total || 0);
      const tracks = data.tracks || [];
      if (!tracks.length) break;
      for (const t of tracks) {
        const tid = Number(t?.track_id);
        if (tid > 0) ids.push(tid);
      }
      if (tracks.length < perPage) break;
      page += 1;
    }
    return ids;
  }

  /**
   * 전체선택 — 화면에 보이는 페이지만이 아니라 현재 목록(전체·장르 등)의 전곡.
   * 아티스트/앨범/작곡가 허브는 곡 행이 없으므로 UI에서 버튼을 숨긴다.
   */
  async selectAllLibraryTracks(listId) {
    const lid = listId || this._activeLibTrackListId();
    if (this._isCollectionCheckMode()) {
      this.selectAllRenderedTracks(lid);
      return;
    }
    const tab = typeof libSubTab !== 'undefined' && libSubTab ? libSubTab : 'all';
    let ids = [];
    if (lid === 'tlist' && (tab === 'all' || !tab)) {
      try {
        ids = await this._fetchAllLibraryTrackIds();
      } catch (e) {
        console.warn('[WhickUI] selectAll fetch all failed, fallback rendered', e);
        ids = ((this._trackLists && this._trackLists.tlist) || [])
          .map((t) => Number(t?.track_id))
          .filter((n) => n > 0);
      }
    } else {
      ids = ((this._trackLists && this._trackLists[lid]) || [])
        .map((t) => Number(t?.track_id))
        .filter((n) => n > 0);
    }
    this._checkChecked().clear();
    ids.forEach((tid) => this._checkChecked().add(tid));
    await this.api.setQueue([...this._checkChecked()]);
    this._syncRenderedChecks(false);
    if (typeof syncLibChrome === 'function') syncLibChrome();
  }

  selectAllRenderedTracks(listId = 'tlist') {
    if (this._isCollectionCheckMode()) {
      const tracks = (this._trackLists && this._trackLists[listId]) || [];
      const s = this._collectionChecked();
      s.clear();
      tracks.forEach((track) => {
        const tid = Number(track?.track_id);
        if (tid > 0) s.add(tid);
      });
      this._syncRenderedChecks(true);
      return;
    }
    // 재생목록 전체선택: 페이지 단위가 아니라 현재 목록 전체
    return this.selectAllLibraryTracks(listId);
  }

  clearAllRenderedTracks(listId = 'tlist') {
    void listId;
    if (this._isCollectionCheckMode()) {
      this._collectionChecked().clear();
      this._syncRenderedChecks(true);
      return;
    }
    this._checkChecked().clear();
    this.api.setQueue([...this._checkChecked()]);
    this._syncRenderedChecks(false);
  }

  _syncRenderedChecks(collectionOnly) {
    const coll = !!collectionOnly || this._isCollectionCheckMode();
    const checked = coll ? this._collectionChecked() : this._checkChecked();
    document.querySelectorAll('.ti2-wrap[data-tid] input[type=checkbox]').forEach((cb) => {
      const wrap = cb.closest('.ti2-wrap');
      const inFav = !!wrap?.closest('#lib-fav');
      if (coll && !inFav && !(typeof editingBoard !== 'undefined' && editingBoard)) return;
      if (!coll && inFav) return;
      const tid = Number(wrap?.getAttribute('data-tid'));
      cb.checked = checked.has(tid);
    });
    this._syncCheckUI();
  }

  playCheckedTracks(listId) {
    void listId;
    const ids = [...this._checkChecked()];
    if (!ids.length) return;
    this.api.playQueue(ids, ids[0]);
    this._syncCheckUI();
  }

  /** 모음용 선택만 비움 — 재생 대기열 유지 */
  clearCollectionChecked() {
    this._collectionChecked().clear();
    document.querySelectorAll('#lib-fav .ti2-wrap input[type=checkbox]:checked').forEach((cb) => {
      cb.checked = false;
    });
    if (typeof editingBoard !== 'undefined' && editingBoard) {
      document.querySelectorAll('.ti2-wrap input[type=checkbox]:checked').forEach((cb) => {
        if (!cb.closest('#lib-fav')) cb.checked = false;
      });
    }
    this._syncCheckUI();
  }

  setCollectionChecked(ids) {
    const s = this._collectionChecked();
    s.clear();
    (ids || []).forEach((id) => {
      const n = typeof id === 'string' ? parseInt(id, 10) : Number(id);
      if (n > 0) s.add(n);
    });
    this._syncRenderedChecks(true);
  }

  clearChecked() {
    this._checkChecked().clear();
    this.api.setQueue([]);
    document.querySelectorAll('.ti2-wrap[data-tid] input[type=checkbox]').forEach((cb) => {
      if (cb.closest('#lib-fav')) return;
      cb.checked = false;
    });
    try {
      if (typeof chkSet !== 'undefined') chkSet.clear();
      if (typeof chkOrder !== 'undefined') chkOrder.length = 0;
    } catch (e) {
      /* ignore */
    }
    this._syncCheckUI();
  }

  _uncheckAllBoxes() {
    document.querySelectorAll('.ti2-wrap input[type=checkbox]:checked').forEach((cb) => {
      cb.checked = false;
    });
    try {
      if (typeof chkSet !== 'undefined') chkSet.clear();
      if (typeof chkOrder !== 'undefined') chkOrder.length = 0;
      if (typeof favChkSet !== 'undefined') favChkSet.clear();
      if (typeof favChkOrder !== 'undefined') favChkOrder.length = 0;
    } catch (e) {
      /* ignore — index.html 전역이 아직 준비 안 된 경우 */
    }
  }

  _renderTrackMeta(t) {
    // metadata accordion panel — simple version
    const dur = WhickAPI.formatTime(t.duration_sec || 0);
    return '<div class="meta-row"><span class="meta-k">' + window._t('lib.meta_title', '곡명') + '</span><span class="meta-v">' + escapeHtml(t.title) + '</span></div>' +
      '<div class="meta-row"><span class="meta-k">' + window._t('lib.meta_artist', '아티스트') + '</span><span class="meta-v">' + escapeHtml(t.artist) + '</span></div>' +
      '<div class="meta-row"><span class="meta-k">' + window._t('lib.meta_album', '앨범') + '</span><span class="meta-v">' + escapeHtml(t.album || '—') + '</span></div>' +
      '<div class="meta-row"><span class="meta-k">' + window._t('lib.meta_length', '길이') + '</span><span class="meta-v">' + dur + '</span></div>';
  }

  playRenderedTrack(listId, index) {
    const tracks = (this._trackLists && this._trackLists[listId]) || [];
    const t = tracks[index];
    if (!t) return;
    const isStream =
      t.source === 'spotify' || t.source === 'tidal' || (t.stream_id && !t.track_id);
    if (isStream) {
      const streamItems = tracks.filter(
        (x) => x.source === 'spotify' || x.source === 'tidal' || (x.stream_id && !x.track_id),
      );
      this.api.playStreamingTrack(t, streamItems).catch(console.error);
      return;
    }
    // 체크된 곡이 있으면 그 목록으로, 없으면 클릭한 곡만 — 전체 목록을 몰래 queue에 넣지 않는다.
    const checked = [...this._checkChecked()].map(Number).filter((id) => id > 0);
    if (checked.length) {
      this.api.playQueue(checked, t.track_id);
      return;
    }
    this.api.playQueue([t.track_id], t.track_id);
  }

  _renderArtists(artists) {
    const el = document.getElementById('alist');
    if (!el) return;
    const colors = ['#1a3a4a', '#2a1a4a', '#0a2a4a', '#3a0a2a', '#1a3a1a', '#4a2a0a'];
    el.innerHTML = artists
      .map(
        (a, i) => `
      <div class="art-item" onclick="window._uiBridge.loadArtistTracks('${String(a.artist).replace(/'/g, "\\'")}')">
        <div class="art-avatar" style="background:linear-gradient(135deg,${colors[i % colors.length]},${colors[i % colors.length]}aa)">🎤</div>
        <div class="art-info">
          <div class="art-name">${a.artist}</div>
          <div class="art-sub">${a.track_count}${window._t('lib.song_unit', _t('unit.tracks', '곡'))} · ${a.album_count}${window._t('lib.album_unit', '개 앨범')}</div>
        </div>
        <div class="art-arrow">›</div>
      </div>`,
      )
      .join('');
  }

  _renderAlbums(albums) {
    const el = document.getElementById('algrid');
    if (!el) return;
    const jackets = ['jacket-0', 'jacket-1', 'jacket-2', 'jacket-3', 'jacket-4', 'jacket-5', 'jacket-6', 'jacket-7', 'jacket-8', 'jacket-9'];
    el.innerHTML = albums
      .map(
        (al, i) => `
      <div class="alb-card" onclick="window._uiBridge.loadAlbumTracks('${String(al.album).replace(/'/g, "\\'")}')">
        <div class="alb-jacket">
          <div class="alb-jacket-inner ${jackets[i % jackets.length]}">
            <div class="jacket-vinyl"></div><div class="jacket-vinyl2"></div>
            <div class="jacket-emoji">💿</div>
          </div>
          <div class="alb-badge">${WhickAPI.qualityLabel(al)}</div>
        </div>
        <div class="alb-info">
          <div class="alb-title">${al.album}</div>
          <div class="alb-artist">${al.artist}</div>
          <div class="alb-meta"><div class="alb-cnt">${al.track_count} ${_t('unit.tracks_short', 'tracks')}</div></div>
        </div>
      </div>`,
      )
      .join('');
  }

  async loadArtistTracks(artist) {
    const data = await this.api.getArtistTracks(artist);
    if (this._listOffset) this._listOffset.tlist = 0;
    this._hideLibPager();
    this._renderTracks(data.tracks || []);
    document.querySelectorAll('.lt').forEach((t, i) => t.classList.toggle('on', i === 0));
    document.querySelectorAll('[id^=lib-]').forEach((x) => x.classList.add('hd'));
    document.getElementById('lib-all')?.classList.remove('hd');
  }

  async loadAlbumTracks(album) {
    const data = await this.api.getAlbumTracks(album);
    const tracks = data.tracks || [];
    if (this._listOffset) this._listOffset.tlist = 0;
    this._hideLibPager();
    this._renderTracks(tracks, 'tlist', tracks.map((t) => t.track_id));
    document.querySelectorAll('.lt').forEach((t, i) => t.classList.toggle('on', i === 0));
    document.querySelectorAll('[id^=lib-]').forEach((x) => x.classList.add('hd'));
    document.getElementById('lib-all')?.classList.remove('hd');
  }

  _genreEmoji(name) {
    const raw = String(name || '');
    const low = raw.toLowerCase();
    if (typeof LIB_GENRES !== 'undefined' && Array.isArray(LIB_GENRES)) {
      for (const g of LIB_GENRES) {
        if (g.id === low || g.label === raw) return g.emoji || '🎵';
      }
    }
    if (typeof GENRE_RULES !== 'undefined' && Array.isArray(GENRE_RULES)) {
      for (const rule of GENRE_RULES) {
        if (rule.kw.some((k) => low.includes(k) || raw.includes(k))) {
          const meta = typeof GENRE_BY_ID !== 'undefined' ? GENRE_BY_ID[rule.id] : null;
          return (meta && meta.emoji) || '🎵';
        }
      }
    }
    if (low.includes('classic') || raw.includes('클래식')) return '🎻';
    if (low.includes('jazz') || raw.includes('재즈')) return '🎷';
    return '🎵';
  }

  _renderGenreHub(genres) {
    const tabs = document.getElementById('genre-ltabs');
    const listEl = document.getElementById('genre-tlist');
    if (!tabs || !listEl) return;
    this._genreList = genres || [];
    if (!this._genreList.length) {
      tabs.innerHTML = '';
      listEl.innerHTML =
        '<div style="padding:24px;color:var(--text3);text-align:center">' + window._t('lib.no_genre', '장르로 분류된 곡이 없습니다') + '</div>';
      return;
    }
    if (!this._activeGenre || !this._genreList.some((g) => g.genre === this._activeGenre)) {
      this._activeGenre = this._genreList[0].genre;
    }
    tabs.innerHTML = this._genreList
      .map((g) => {
        const on = g.genre === this._activeGenre ? ' on' : '';
        const emoji = this._genreEmoji(g.genre);
        const safe = String(g.genre).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        return `<div class="lt${on}" onclick="window._uiBridge.loadGenreTracks('${safe}')">${emoji} ${escapeHtml(g.genre)} <span style="opacity:.6;font-size:10px">${g.track_count}</span></div>`;
      })
      .join('');
    this.loadGenreTracks(this._activeGenre);
  }

  async loadGenreTracks(genre) {
    this._activeGenre = genre;
    const safe = String(genre).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    document.querySelectorAll('#genre-ltabs .lt').forEach((t) => {
      const oc = t.getAttribute('onclick') || '';
      t.classList.toggle('on', oc.includes(`'${safe}'`));
    });
    try {
      const data = await this.api.getGenreTracks(genre);
      const tracks = data.tracks || [];
      this._renderTracks(tracks, 'genre-tlist', tracks.map((t) => t.track_id));
    } catch (e) {
      console.error('[WhickUI] genre tracks', e);
      const el = document.getElementById('genre-tlist');
      if (el) {
        el.innerHTML =
          '<div style="padding:24px;color:var(--text3);text-align:center">' + window._t('lib.genre_load_fail', '장르 곡을 불러오지 못했습니다') + '</div>';
      }
    }
  }

  _renderComposers(composers) {
    const el = document.getElementById('clist');
    if (!el) return;
    if (typeof backComposer === 'function') backComposer();
    if (!composers.length) {
      el.innerHTML =
        '<div style="padding:24px;color:var(--text3);text-align:center">' + window._t('lib.no_composer', '작곡가로 분류된 곡이 없습니다') + '</div>';
      return;
    }
    const colors = ['#1a3a4a', '#2a1a4a', '#0a2a4a', '#3a0a2a', '#1a3a1a', '#4a2a0a'];
    el.innerHTML = composers
      .map((c, i) => {
        const name = c.composer || _t('genre.uncategorized', '미분류');
        const safe = String(name).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        const bg = colors[i % colors.length];
        return `
      <div class="art-item" onclick="window._uiBridge.loadComposerTracks('${safe}')">
        <div class="art-avatar" style="background:linear-gradient(135deg,${bg},${bg}aa)">🧩</div>
        <div class="art-info">
          <div class="art-name">${escapeHtml(name)}</div>
          <div class="art-sub">${c.track_count || 0} ${_t('unit.tracks_short', 'tracks')}</div>
        </div>
        <div class="art-arrow">›</div>
      </div>`;
      })
      .join('');
  }

  async loadComposerTracks(composer) {
    try {
      const data = await this.api.getComposerTracks(composer);
      const tracks = data.tracks || [];
      const det = document.getElementById('cdetail');
      if (!det) return;
      det.innerHTML =
        '<div class="lib-detail-h">' +
        '<button class="lib-back" onclick="backComposer()">‹ ' + window._t('lib.composer', '작곡가') + '</button>' +
        `<div class="lib-detail-title">🧩 ${escapeHtml(composer)}</div>` +
        `<div class="lib-detail-sub">${tracks.length}${window._t('lib.song_unit', _t('unit.tracks', '곡'))}</div>` +
        '</div>' +
        '<div class="tl" id="composer-tlist"></div>';
      document.getElementById('clist')?.classList.add('hd');
      document.querySelector('#lib-composer .lib-composer-banner')?.classList.add('hd');
      det.classList.remove('hd');
      this._renderTracks(tracks, 'composer-tlist', tracks.map((t) => t.track_id));
    } catch (e) {
      console.error('[WhickUI] composer tracks', e);
    }
  }

  async refreshLibraryStatus() {
    try {
      const st = await this.api.getLibraryStatus();
      const el = document.getElementById('lib-status-text');
      if (el) {
        el.textContent = `${st.total_tracks ?? 0} ${_t('rev2.tracks_review_note', 'tracks · import after review approval')}`;
      }
    } catch (e) {
      console.warn('[WhickUI] library status', e);
    }
  }

  async loadIncomingAudit() {
    const summary = document.getElementById('incoming-audit-summary');
    const list = document.getElementById('incoming-audit-list');
    if (!list) return;
    if (summary) summary.textContent = _t('rev2.reviewing', '검수 중…');
    try {
      const data = await this.api.getIncomingAudit();
      this.api._incomingAudit = data;
      const items = data.items || [];
      const approved = items.filter((i) => i.verdict === 'approved');
      const rejected = items.filter((i) => i.verdict === 'rejected');
      if (summary) {
        summary.textContent = items.length
          ? `${_t('rev2.approved_n', 'Approved ')}${approved.length} · ${_t('rev2.rejected_n', 'rejected ')}${rejected.length} (${_t('rev2.no_file_change', 'no file changes')})`
          : _t('rev2.no_pending', '대기 중인 incoming 파일 없음');
      }
      if (!items.length) {
        list.innerHTML =
          '<div style="padding:12px;color:var(--text3);font-size:12px;text-align:center">' + _t('rev2.no_files', 'No files to review in the incoming folder') + '</div>';
        return;
      }
      list.innerHTML =
        items
          .map(
            (it) => `
        <div class="audit-item">
          <span class="audit-verdict ${it.verdict === 'approved' ? 'ok' : 'no'}">${it.verdict === 'approved' ? _t('rev2.approve', '승인') : _t('rev2.reject', '탈락')}</span>
          <div style="flex:1;min-width:0">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${it.rel_path}</div>
            <div style="font-size:10px;color:var(--text3);margin-top:2px">${(it.reasons || []).join(', ') || it.tier || ''}</div>
          </div>
        </div>`,
          )
          .join('') +
        `<div class="audit-actions">
          <button type="button" class="audit-btn primary" id="btn-import-approved">${_t('rev2.import_approved', 'Import approved tracks')}</button>
          <button type="button" class="audit-btn" id="btn-import-rejected-pass">${_t('rev2.import_rejected_pass', 'Add rejected too (customer pass)')}</button>
          <button type="button" class="audit-btn danger" id="btn-delete-rejected">${_t('rev2.delete_rejected2', 'Delete rejected tracks')}</button>
        </div>`;
      document.getElementById('btn-import-approved')?.addEventListener('click', () =>
        this._approveIncomingImport(approved.map((i) => i.rel_path)),
      );
      document.getElementById('btn-import-rejected-pass')?.addEventListener('click', () =>
        this._approveIncomingImport(rejected.map((i) => i.rel_path)),
      );
      document.getElementById('btn-delete-rejected')?.addEventListener('click', () =>
        this._approveIncomingDelete(rejected.map((i) => i.rel_path)),
      );
    } catch (e) {
      if (summary) summary.textContent = _t('rev2.query_failed', '검수 조회 실패');
      list.innerHTML =
        '<div style="padding:12px;color:var(--red);font-size:12px">' + _t('err.check_server', 'Check the server connection') + '</div>';
    }
  }

  async _approveIncomingImport(paths) {
    if (!paths.length) {
      alert(_t('rev2.no_approve', '승인할 파일이 없습니다.'));
      return;
    }
    if (!confirm(`${_t('rev2.add_approved_q', 'Add')} ${paths.length} ${_t('rev2.approved_tracks_lib', 'approved track(s) to the library?')}`)) return;
    try {
      const r = await this.api.importIncomingApproved(paths);
      alert(`${_t('rev2.add_done', 'Added: ')}${r.imported?.moved ?? 0}`);
      await this.loadIncomingAudit();
      await this.refreshLibraryStatus();
      await this._loadDashboard();
    } catch (e) {
      alert(_t('err.import_failed', 'import 실패 — ') + (e.message || e));
    }
  }

  async _approveIncomingDelete(paths) {
    if (!paths.length) {
      alert(_t('rev2.no_rejected', '삭제할 탈락 파일이 없습니다.'));
      return;
    }
    if (!confirm(`${_t('rev2.delete_rejected_q', 'Delete')} ${paths.length} ${_t('rev2.rejected_from_incoming', 'rejected track(s) from incoming?')}\n(${_t('common.irreversible', 'Cannot be undone')})`)) return;
    try {
      const r = await this.api.deleteIncomingRejected(paths);
      alert(`${_t('rev2.delete_done', 'Deleted: ')}${r.deleted?.deleted ?? 0}`);
      await this.loadIncomingAudit();
    } catch (e) {
      alert(_t('err.delete_failed', 'delete 실패 — ') + (e.message || e));
    }
  }
}

function attachWhickNetworkListeners(api) {
  if (!api || api._networkListenersAttached) return;
  api._networkListenersAttached = true;

  window.addEventListener('online', () => {
    if (!api.wsReady) api.reconnect();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !api.wsReady) {
      api.reconnect();
    }
  });

  window.addEventListener('pagehide', () => {
    try {
      if (localStorage.getItem('whick_remote_stop_on_close') === '0') return;
      api.stop();
    } catch {
      /* best effort: page is closing */
    }
  });
}

function initWhickRemote(serverHostOrOpts) {
  let connectMode = 'auto';
  try {
    connectMode =
      new URLSearchParams(location.search).get('connect') ||
      localStorage.getItem('whick_remote_connect_mode') ||
      'auto';
  } catch {
    /* ignore */
  }
  const opts =
    serverHostOrOpts && typeof serverHostOrOpts === 'object'
      ? { ...serverHostOrOpts, connectMode }
      : { host: serverHostOrOpts, connectMode };
  const api = new WhickAPI(opts);
  const bridge = new WhickUIBridge(api);
  attachWhickNetworkListeners(api);

  window._api = api;
  window._uiBridge = bridge;
  window._whickRemoteApi = api;

  // index.html function aiSearch() 가 채팅 SSOT — 여기서 덮어쓰지 않음
  if (typeof window.aiSearch !== 'function') {
    window.aiSearch = async () => {
      const q = document.getElementById('ata')?.value?.trim();
      if (!q) return;
      try {
        const data = await api.aiChat(q, { history: [] });
        const res = document.getElementById('ai-res');
        if (res) {
          res.innerHTML =
            '<div class="airec-banner airec-banner--sm"><div class="airec-hab">' +
            escapeHtml(data.reply || '') +
            '</div></div>';
        }
      } catch (e) {
        const el = document.getElementById('ai-res');
        if (el) {
          el.innerHTML =
            '<div style="color:var(--red);padding:16px 0">' + _t('ai.chat_failed', 'AI chat failed — check server connection') + '</div>';
        }
      }
    };
  }

  window.aiSrc = (el) => {
    if (el) el.classList.toggle('on');
  };

  window.aiC = (el) => {
    const ta = document.getElementById('ata');
    if (ta && el) ta.value = el.textContent;
    window.aiSearch();
  };

  window.filterT = async (val) => {
    if (!val) {
      bridge._loadLibraryEssentials();
      return;
    }
    try {
      const data = await api.search(val);
      bridge._renderTracks(data.results || []);
    } catch (e) {
      console.warn('[Search]', e);
    }
  };

  const _origLibTab = window.libTab;
  window.libTab = (el, id) => {
    bridge._activeLibraryTab = id || 'all';
    _origLibTab(el, id);
    if (typeof syncLibChrome === 'function') syncLibChrome(id);
    if (id && id !== 'all') {
      bridge.ensureLibraryTab(id).catch(console.error);
    } else {
      // 전체 목록 복귀 시 페이지네이션 목록 다시 로드 (앨범/아티스트 드릴인 후 잔상 방지)
      bridge._loadLibraryEssentials(bridge._libPage || 1).catch(console.error);
    }
  };

  const _origGo = window.go;
  if (typeof _origGo === 'function') {
    window.go = (tab, title) => {
      _origGo(tab, title);
      if (tab === 'radio') bridge._loadRadio();
    };
  }

  window.playR = (stationId) => {
    if (bridge && typeof bridge._setRadioSelection === 'function') {
      bridge._setRadioSelection(stationId);
    }
    api.playRadio(stationId).catch(console.error);
  };

  window.togglePlay = () => bridge.playOrToggleFromSelection();
  window.handlePlayPause = () => bridge.playOrToggleFromSelection();
  window.resumeMobileAudio = () => api.resumeMobilePlayback();
  window.prev = () => api.prev();
  window.next = () => api.next();
  window.toggleShuffle = () => api.setShuffle(!api.state.shuffle);
  window.toggleRepeat = () => api.toggleRepeat();

  api.connect();
  if (typeof initWhickSpatialWizard === 'function') {
    initWhickSpatialWizard(api, 'settings-spatial-root');
    initWhickSpatialWizard(api, 'spatial-root');
    initWhickSpatialWizard(api, 'dsp-speaker-dir-root');
  }
  if (typeof initWhickStreamingWizard === 'function') {
    window._streamingWizard = initWhickStreamingWizard(api);
    api.on('connected', () => window._streamingWizard?.refreshCards());
  }
  return { api, bridge };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    WhickAPI,
    WhickUIBridge,
    initWhickRemote,
    attachWhickNetworkListeners,
    normalizeRemoteHost,
    buildRemoteUrls,
  };
}

if (typeof window !== 'undefined') {
  window.WHICK_EQ_BANDS = WHICK_EQ_BANDS;
  window.WHICK_EQ_PRESET_GAINS = WHICK_EQ_PRESET_GAINS;
}
