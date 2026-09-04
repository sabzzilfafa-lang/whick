/**
 * WhickShare — 추천곡 공유 터널 + 게스트 경량 플레이어
 *
 * 아키텍처 (상업용 리모컨 배포 기준):
 * - 중앙관제: 24h 임시 터널·게스트 토큰 발급만 (곡 목록·음원 내용 저장 안 함)
 * - 고객 미니PC 뮤직서버: 실제 음원 스트리밍 (/api/guest/stream/…)
 * - 공유 링크 수신자: 로그인 없이 자기 기기(폰/PC) 내장 플레이어로 청취
 *
 * 페이로드 v4: { v, title, th, mb, gt, exp, tr:[{i,t,a,al,d,q,e,p}] }
 *   th — 터널 호스트 (표시·링크)
 *   mb — 음원 스트림 베이스 URL (고객 뮤직서버)
 *   p  — mb 기준 상대 스트림 경로 (게스트 토큰 포함)
 */
(function (global) {
  'use strict';

  const TTL_MS = 24 * 60 * 60 * 1000;
  /** 카톡·문자용 짧은 공유 도메인 */
  const SHARE_PUBLIC_ORIGIN = 'https://whick.org';
  /** 짧은 링크 등록 API (중앙 메타만 · 음원 데이터 아님). remote.whick.org same-origin 금지 */
  const SHARE_API_BASE = 'https://whick.org/api/v1/site';
  /** 고객 터널 게스트 플레이어 (music-N 루트) */
  const PROD_PLAYER_PATH = '/';

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function sqJs(s) {
    return "'" + String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "'";
  }

  function b64urlEncode(obj) {
    const raw = JSON.stringify(obj);
    return btoa(unescape(encodeURIComponent(raw)))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  }

  function b64urlDecode(token) {
    const pad = token.length % 4 ? '='.repeat(4 - (token.length % 4)) : '';
    const json = decodeURIComponent(
      escape(atob((token + pad).replace(/-/g, '+').replace(/_/g, '/'))),
    );
    return JSON.parse(json);
  }

  function fmtRemain(ms) {
    if (ms <= 0) return _t('share.expired', '만료됨');
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    if (h > 0) return h + _t('share.hours_suffix', '시간 ') + m + _t('share.min_left', '분 남음');
    return m + _t('share.min_left', '분 남음');
  }

  /** @param {object|null} profile deviceProfile (tunnel, tunnel_host, …) */
  function tunnelHost(profile) {
    const tun = profile && (profile.tunnel || profile.tunnel_host);
    if (tun) return String(tun).replace(/^https?:\/\//, '').replace(/\/+$/, '');
    return null;
  }

  /** 고객 뮤직서버 HTTPS 베이스 (스트림 origin) */
  function musicBase(profile) {
    const th = tunnelHost(profile);
    if (th) {
      return (th.startsWith('http') ? th : 'https://' + th).replace(/\/+$/, '');
    }
    return null;
  }

  /** 공유 링크가 열리는 페이지 URL (게스트 플레이어) */
  function sharePageUrl(profile, opts) {
    opts = opts || {};
    const th = tunnelHost(profile);
    if (!th) return null;
    return musicBase(profile).replace(/\/+$/, '') + PROD_PLAYER_PATH;
  }

  function newGuestToken() {
    return (
      Math.random().toString(36).slice(2) +
      Math.random().toString(36).slice(2) +
      Date.now().toString(36)
    ).slice(0, 24);
  }

  /** URL hash에서 전체 공유 토큰 추출 (#share=…) */
  function parseShareHash(hash) {
    const h = hash || (typeof location !== 'undefined' ? location.hash : '') || '';
    const m = h.match(/[#&]share=([^&]+)/);
    if (!m) return null;
    return { full: m[1] || null, short: null };
  }

  function resolveSharePayload(input) {
    if (!input) return null;
    const s = String(input).trim();
    try {
      return b64urlDecode(s);
    } catch (_) {
      return null;
    }
  }

  /** 트랙 → 뮤직서버 상대 스트림 경로 (고객 설치 후 /api/guest/stream 사용) */
  function trackStreamPath(track, guestToken) {
    const gt = guestToken ? encodeURIComponent(guestToken) : '';
    const appendGt = (path) => {
      if (!gt) return path;
      return path + (path.includes('?') ? '&' : '?') + 'gt=' + gt;
    };
    if (track.url && String(track.url).startsWith('/api/')) {
      return appendGt(track.url);
    }
    const id = track.id != null ? String(track.id) : '';
    if (/^\d+$/.test(id)) {
      return appendGt('/api/guest/stream/' + encodeURIComponent(id));
    }
    if (track.url) {
      const u = String(track.url);
      if (u.startsWith('/')) return u;
      return u;
    }
    return null;
  }

  function resolveStreamUrl(track, payload) {
    const path = track.p || track.u || null;
    if (!path) return null;
    if (/^https?:\/\//i.test(path)) return path;
    const base = (payload.mb || payload.musicBase || '').replace(/\/+$/, '');
    if (!base && typeof location !== 'undefined') {
      return path.startsWith('/') ? path : '/' + path;
    }
    return base + (path.startsWith('/') ? path : '/' + path);
  }

  function normalizeTracksFromPayload(p) {
    if (Array.isArray(p.tr) && p.tr.length) {
      return p.tr.map(function (x) {
        return {
          id: x.i,
          t: x.t,
          a: x.a,
          al: x.al,
          d: x.d,
          q: x.q,
          e: x.e || '🎵',
          p: x.p,
          u: x.u,
        };
      });
    }
    if (Array.isArray(p.ids) && p.ids.length) {
      return p.ids.map(function (id) {
        return { id: id, t: String(id), a: '—', al: '', d: '—', q: '', e: '🎵' };
      });
    }
    return [];
  }

  function encodePayload(board, trackList, profile) {
    const th = tunnelHost(profile);
    if (!th) return null;
    const mb = musicBase(profile);
    const gt = board.shareToken;
    const tr = (trackList || []).slice(0, 50).map(function (t) {
      return {
        i: t.id,
        t: t.t,
        a: t.a,
        al: t.al,
        d: t.d || '—',
        q: t.q || '',
        e: t.e || '🎵',
        p: trackStreamPath(t, gt),
      };
    });
    return {
      v: 4,
      title: board.title || _t('share.recommend_title', '추천곡'),
      th: th,
      mb: mb,
      gt: gt,
      exp: board.shareExp,
      tr: tr,
    };
  }

  function buildShareUrl(board, trackList, profile, opts) {
    return buildShareUrlCrossDevice(board, trackList, profile, opts);
  }

  /** 카톡·다른 기기용 — 터널 직행: https://music-N.whick.org/?gt=TOKEN */
  function buildShareUrlCrossDevice(board, trackList, profile, opts) {
    opts = opts || {};
    const th = tunnelHost(profile);
    if (th && board.shareToken) {
      const base = th.startsWith('http') ? th : 'https://' + th;
      const gt = encodeURIComponent(board.shareToken);
      return base.replace(/\/+$/, '') + '/?gt=' + gt;
    }
    return null;
  }

  /** 같은 기기 미리보기 — 고객 뮤직서버 터널 직행 */
  function buildShareUrlPreview(board, trackList, profile, opts) {
    return buildShareUrlCrossDevice(board, trackList, profile, opts);
  }

  /** 다른 기기·브라우저용 전체 링크 (#share=…) */
  function buildShareUrlFull(board, trackList, profile, opts) {
    const payload = encodePayload(board, trackList, profile);
    const page = sharePageUrl(profile, opts || {});
    if (!payload || !page) return null;
    return page + '#share=' + b64urlEncode(payload);
  }

  function escAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;');
  }

  function copyShareLink(url, toastFn) {
    if (!url) return;
    const toast = toastFn || function () {};
    if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
      global.navigator.clipboard
        .writeText(url)
        .then(function () {
          toast(_t('share.link_copied', '링크가 복사되었습니다'));
        })
        .catch(function () {
          toast(_t('share.copy_failed', '복사 실패'));
        });
    } else {
      toast(url);
    }
  }

  /** Web Share API — 클릭 핸들러에서 동기 호출 (user gesture 유지) */
  function mobileNativeShare(url, title, toastFn) {
    const toast = toastFn || function () {};
    if (!url) return;
    const shareTitle = String(title || _t('share.whick_favorites', 'Whick 즐겨듣기')).trim();
    const shareText = buildShareMessage(shareTitle, url);

    if (!global.navigator || !global.navigator.share) {
      copyShareLink(url, toast);
      toast(_t('share.no_share_sheet', '이 기기는 공유 시트를 지원하지 않습니다 · 링크를 복사했습니다'));
      return;
    }

    global.navigator
      .share({ title: shareTitle, text: shareText, url: url })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        // text+url 미지원 환경: url만 전달 (text에 URL을 넣지 않아 카톡 중복 방지)
        return global.navigator.share({ title: shareTitle, url: url });
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        return global.navigator.share({ title: shareTitle, text: shareText + '\n' + url });
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        copyShareLink(url, toast);
      });
  }

  function bindShareResultActions(root, toastFn) {
    if (!root) return;
    const body = root.querySelector('.share-result-body');
    if (!body) return;
    const url = body.getAttribute('data-share-url');
    const title = body.getAttribute('data-share-title') || '';
    if (!url) return;

    const shareBtn = root.querySelector('.share-btn--share');
    if (shareBtn && !shareBtn._whickShareBound) {
      shareBtn._whickShareBound = true;
      shareBtn.addEventListener('click', function (e) {
        e.preventDefault();
        mobileNativeShare(url, title, toastFn);
      });
    }

    const copyBtn = root.querySelector('.share-btn--copy');
    if (copyBtn && !copyBtn._whickShareBound) {
      copyBtn._whickShareBound = true;
      copyBtn.addEventListener('click', function (e) {
        e.preventDefault();
        copyShareLink(url, toastFn);
      });
    }

    const previewBtn = root.querySelector('.share-btn--preview');
    if (previewBtn && !previewBtn._whickShareBound) {
      previewBtn._whickShareBound = true;
      previewBtn.addEventListener('click', function (e) {
        e.preventDefault();
        global.open(url, '_blank');
      });
    }
  }

  function buildShareMessage(title, shortUrl) {
    // title은 navigator.share({ title })로만 전달. text에 제목을 또 넣으면 카톡 등에서 이중 표시됨.
    void title;
    void shortUrl;
    return _t('share.text_body', '🎵 Whick picks\nTap the link to play (24 hours)');
  }

  function shortLinkUrl(code) {
    return SHARE_PUBLIC_ORIGIN.replace(/\/+$/, '') + '/l/' + String(code || '').trim();
  }

  /**
   * whick.org/l/{code} — 게스트 토큰과 고객 터널 주소만 중앙 저장
   */
  async function registerShortLinkOnServer(board, trackList, profile) {
    if (!tunnelHost(profile) || !board.shareToken) return null;
    const body = {
      title: board.title || _t('share.recommend_title', '추천곡'),
      expires_at: board.shareExp || Date.now() + TTL_MS,
      guest_token: board.shareToken,
      music_base: musicBase(profile),
    };
    try {
      const resp = await fetch(SHARE_API_BASE + '/share/l', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'omit',
        body: JSON.stringify(body),
      });
      if (!resp.ok) return null;
      const json = await resp.json();
      const data = json.data || json;
      if (data && data.code) {
        board.shareShortLink = data.url || shortLinkUrl(data.code);
        return board.shareShortLink;
      }
    } catch (_) {
      /* fallback to long url */
    }
    return null;
  }

  /**
   * 소유자 리모컨 → 고객 뮤직서버에 게스트 토큰·허용 곡 등록 (POST /api/guest/shares)
   */
  async function registerGuestShareOnServer(board, trackList, profile, opts) {
    opts = opts || {};
    if (!tunnelHost(profile)) return { ok: false, skipped: 'no_tunnel' };
    const ids = (trackList || [])
      .map(function (t) {
        return t.id != null ? t.id : t.track_id;
      })
      .filter(function (id) {
        return /^\d+$/.test(String(id));
      })
      .map(Number);
    if (!ids.length) return { ok: false, skipped: 'no_numeric_tracks' };
    const gt = board.shareToken;
    if (!gt) return { ok: false, skipped: 'no_token' };

    const mb = musicBase(profile);
    const api = typeof global !== 'undefined' ? global._api : null;

    const buildHeaders = function () {
      const headers = { 'Content-Type': 'application/json' };
      if (opts.authHeaders) Object.assign(headers, opts.authHeaders);
      else if (api && api.playerToken) headers.Authorization = 'Bearer ' + api.playerToken;
      return headers;
    };

    const doPost = function () {
      return fetch(mb + '/api/guest/shares', {
        method: 'POST',
        headers: buildHeaders(),
        body: JSON.stringify({
          guest_token: gt,
          title: board.title,
          track_ids: ids,
          expires_at: board.shareExp,
        }),
      });
    };

    if (!opts.authHeaders && api && typeof api.ensurePlayerToken === 'function') {
      try {
        await api.ensurePlayerToken();
      } catch (_) {}
    }

    try {
      let resp = await doPost();
      if (resp.status === 401 && api && typeof api.ensurePlayerToken === 'function') {
        try {
          await api.ensurePlayerToken({ force: true });
          resp = await doPost();
        } catch (_) {}
      }
      if (!resp.ok) {
        let detail = resp.statusText;
        try {
          const err = await resp.json();
          if (err && err.detail) detail = err.detail;
        } catch (_) {}
        return { ok: false, status: resp.status, detail: detail };
      }
      return { ok: true, data: await resp.json() };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  }

  /* ── 게스트 경량 플레이어 ── */
  const Guest = {
    tracks: [],
    idx: 0,
    playing: false,
    payload: null,
    audio: null,
    expTimer: null,
    vol: 70,
    muted: false,
    volDrag: false,
    toastFn: null,
    keyBound: false,
  };

  function guestToast(msg) {
    if (Guest.toastFn) Guest.toastFn(msg);
  }

  function guestFmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function guestApplyVolume() {
    const a = Guest.audio;
    if (!a) return;
    a.volume = Guest.muted ? 0 : Math.max(0, Math.min(1, Guest.vol / 100));
    const fill = document.getElementById('guest-vol-f');
    const pct = document.getElementById('guest-vol-pct');
    const mic = document.getElementById('guest-vol-mute');
    if (fill) fill.style.width = Guest.vol + '%';
    if (pct) pct.textContent = Guest.muted ? _t('share.muted', '음소거') : Guest.vol + '%';
    if (mic) {
      mic.textContent = Guest.muted
        ? '🔇'
        : Guest.vol === 0
          ? '🔈'
          : Guest.vol < 35
            ? '🔈'
            : Guest.vol < 70
              ? '🔉'
              : '🔊';
    }
    try {
      localStorage.setItem('whick_guest_volume', String(Guest.vol));
      localStorage.setItem('whick_guest_muted', Guest.muted ? '1' : '0');
    } catch (_) {}
  }

  function guestSetVolume(pct) {
    Guest.muted = false;
    Guest.vol = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    guestApplyVolume();
  }

  function guestToggleMute() {
    Guest.muted = !Guest.muted;
    guestApplyVolume();
  }

  function bindGuestVolume() {
    const track = document.getElementById('guest-vol-tr');
    if (!track || track._bound) return;
    track._bound = true;
    const pctFrom = (clientX) => {
      const r = track.getBoundingClientRect();
      if (!r.width) return Guest.vol;
      return Math.max(
        0,
        Math.min(100, Math.round(((clientX - r.left) / r.width) * 100)),
      );
    };
    const apply = (clientX) => guestSetVolume(pctFrom(clientX));
    track.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      Guest.volDrag = true;
      try {
        track.setPointerCapture(e.pointerId);
      } catch (_) {}
      apply(e.clientX);
    });
    track.addEventListener('pointermove', (e) => {
      if (Guest.volDrag) apply(e.clientX);
    });
    const end = (e) => {
      if (!Guest.volDrag) return;
      Guest.volDrag = false;
      apply(e.clientX);
    };
    track.addEventListener('pointerup', end);
    track.addEventListener('pointercancel', () => {
      Guest.volDrag = false;
    });
  }

  function bindGuestKeys() {
    if (Guest.keyBound) return;
    Guest.keyBound = true;
    document.addEventListener('keydown', (e) => {
      if (!document.documentElement.classList.contains('guest-active')) return;
      if (
        e.target &&
        (e.target.matches('input,textarea,select') || e.target.isContentEditable)
      )
        return;
      if (e.key === 'ArrowUp' || e.code === 'AudioVolumeUp') {
        e.preventDefault();
        guestSetVolume(Guest.vol + 5);
      } else if (e.key === 'ArrowDown' || e.code === 'AudioVolumeDown') {
        e.preventDefault();
        guestSetVolume(Guest.vol - 5);
      } else if (e.key === 'm' || e.key === 'M' || e.code === 'AudioVolumeMute') {
        e.preventDefault();
        guestToggleMute();
      } else if (e.key === ' ') {
        e.preventDefault();
        guestToggle();
      }
    });
  }

  function guestMsgHtml(ic, title, sub) {
    return (
      '<div class="guest-top"><span class="guest-brand">WHICK</span>' +
      '<span class="guest-secure">🔒 ' + _t('share.secure_tunnel', 'Secure tunnel') + '</span></div>' +
      '<div class="guest-msg"><div class="guest-msg-ic">' +
      ic +
      '</div>' +
      '<div class="guest-msg-t">' +
      esc(title) +
      '</div><div class="guest-msg-s">' +
      sub +
      '</div></div>'
    );
  }

  function renderGuestShell() {
    const p = Guest.payload;
    const root = document.getElementById('guest');
    const rows = Guest.tracks
      .map(function (t, i) {
        return (
          '<div class="guest-row" id="grow-' +
          i +
          '" onclick="WhickShare.guestLoad(' +
          i +
          ',true)">' +
          '<div class="guest-row-ic">' +
          esc(t.e) +
          '</div>' +
          '<div class="guest-row-in">' +
          '<div class="guest-row-t">' +
          esc(t.t) +
          '</div>' +
          '<div class="guest-row-a">' +
          esc(t.a) +
          (t.al ? ' · ' + esc(t.al) : '') +
          '</div></div>' +
          '<div class="guest-row-d">' +
          esc(t.d || '') +
          '</div></div>'
        );
      })
      .join('');
    const srvLabel = p.th
      ? esc(p.th) + ' · ' + _t('share.customer_server', 'Customer music server')
      : _t('share.customer_server', 'Customer music server');
    root.innerHTML =
      '<div class="guest-top">' +
      '<span class="guest-brand">WHICK</span>' +
      '<span class="guest-secure">🔒 ' + _t('share.connected_tunnel', 'Connected via secure tunnel') + '</span>' +
      '</div>' +
      '<div class="guest-srv">📡 <b>' +
      esc(p.title || _t('share.recommend_title', '추천곡')) +
      '</b> · ' + _t('share.direct_stream', 'Streaming directly from the owner\'s music server') + '</div>' +
      '<div class="guest-srv guest-host">' +
      srvLabel +
      '</div>' +
      '<div class="guest-exp"><span class="dotw"></span><span id="guest-remain">' + _t('share.checking_validity', 'Checking validity…') + '</span></div>' +
      '<div class="guest-hero">' +
      '<div class="guest-art" id="guest-art">🎵</div>' +
      '<div class="guest-pl-title">NOW PLAYING</div>' +
      '<div class="guest-now-t" id="guest-now-t">—</div>' +
      '<div class="guest-now-a" id="guest-now-a">—</div>' +
      '</div>' +
      '<div class="guest-bar">' +
      '<div class="guest-bar-tr" id="guest-bar-tr"><div class="guest-bar-f" id="guest-bar-f"></div></div>' +
      '<div class="guest-bar-tm"><span id="guest-ct">0:00</span><span id="guest-dt">0:00</span></div>' +
      '</div>' +
      '<div class="guest-vol">' +
      '<button type="button" class="guest-vol-mute" id="guest-vol-mute" onclick="WhickShare.guestToggleMute()" aria-label="' + _t('share.muted', 'Muted') + '">🔊</button>' +
      '<div class="guest-vol-tr" id="guest-vol-tr"><div class="guest-vol-track"><div class="guest-vol-f" id="guest-vol-f"></div></div></div>' +
      '<span class="guest-vol-pct" id="guest-vol-pct">70%</span>' +
      '</div>' +
      '<div class="guest-ctrl">' +
      '<button type="button" class="guest-cb" onclick="WhickShare.guestPrev()" aria-label="' + _t('share.prev', 'Previous') + '">⏮</button>' +
      '<button type="button" class="guest-cb guest-cb--main" id="guest-pp" onclick="WhickShare.guestToggle()" aria-label="' + _t('share.play_pause', 'Play/Pause') + '">▶</button>' +
      '<button type="button" class="guest-cb" onclick="WhickShare.guestNext()" aria-label="' + _t('share.next', 'Next') + '">⏭</button>' +
      '</div>' +
      '<div class="guest-list">' +
      '<div class="guest-list-h">' + _t('share.shared_tracks', 'Shared tracks ') +
      Guest.tracks.length +
      '</div>' +
      rows +
      '</div>' +
      '<div class="guest-foot">' + _t('share.foot_note', 'Control uses <b>tunnel · link only</b>. Audio streams directly from the <b>customer music server</b> and is never stored centrally. Plays in this device\'s <b>own player</b> · <b>expires after 24 hours</b>.') + '</div>';

    const a = document.getElementById('guest-audio');
    Guest.audio = a;
    if (a && !a._guestBound) {
      a._guestBound = true;
      a.addEventListener('timeupdate', guestProgress);
      a.addEventListener('ended', guestNext);
      a.addEventListener('play', function () {
        Guest.playing = true;
        guestSyncPP();
      });
      a.addEventListener('pause', function () {
        Guest.playing = false;
        guestSyncPP();
      });
      const tr = document.getElementById('guest-bar-tr');
      if (tr) {
        tr.addEventListener('click', function (e) {
          if (!a.duration) return;
          const r = tr.getBoundingClientRect();
          a.currentTime =
            Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * a.duration;
        });
      }
    }
    bindGuestVolume();
    guestApplyVolume();
  }

  function guestLoad(i, autoplay) {
    if (i < 0 || i >= Guest.tracks.length) return;
    Guest.idx = i;
    const t = Guest.tracks[i];
    const setT = function (id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = v;
    };
    setT('guest-now-t', t.t);
    setT('guest-now-a', t.a + (t.al ? ' · ' + t.al : ''));
    const art = document.getElementById('guest-art');
    if (art) art.textContent = t.e || '🎵';
    document.querySelectorAll('.guest-row').forEach(function (r, ri) {
      r.classList.toggle('on', ri === i);
    });
    const a = Guest.audio;
    const streamUrl = resolveStreamUrl(t, Guest.payload);
    if (a) {
      if (streamUrl) {
        a.src = streamUrl;
        guestApplyVolume();
        if (autoplay !== false) a.play().catch(function () {});
      } else {
        a.removeAttribute('src');
      }
    }
    setT('guest-ct', '0:00');
    setT('guest-dt', t.d || '0:00');
    const f = document.getElementById('guest-bar-f');
    if (f) f.style.width = '0%';
    guestSyncPP();
  }

  function guestToggle() {
    const a = Guest.audio;
    if (!a) return;
    const t = Guest.tracks[Guest.idx];
    const streamUrl = t ? resolveStreamUrl(t, Guest.payload) : null;
    if (!streamUrl) {
      guestToast(_t('share.stream_failed', '스트림을 불러올 수 없습니다'));
      return;
    }
    if (a.paused) {
      if (!a.src) a.src = streamUrl;
      guestApplyVolume();
      a.play().catch(function () {});
    } else a.pause();
  }

  function guestNext() {
    guestLoad((Guest.idx + 1) % Guest.tracks.length, true);
  }
  function guestPrev() {
    guestLoad((Guest.idx - 1 + Guest.tracks.length) % Guest.tracks.length, true);
  }
  function guestSyncPP() {
    const b = document.getElementById('guest-pp');
    if (b) b.textContent = Guest.playing ? '⏸' : '▶';
  }
  function guestProgress() {
    const a = Guest.audio;
    if (!a || !a.duration) return;
    const f = document.getElementById('guest-bar-f');
    if (f) f.style.width = (a.currentTime / a.duration) * 100 + '%';
    const ct = document.getElementById('guest-ct');
    if (ct) ct.textContent = guestFmt(a.currentTime);
    const dt = document.getElementById('guest-dt');
    if (dt) dt.textContent = guestFmt(a.duration);
  }

  function startGuestExpiryTick() {
    const tick = function () {
      const el = document.getElementById('guest-remain');
      if (!el) return;
      const ms = (Guest.payload.exp || 0) - Date.now();
      if (ms <= 0) {
        if (Guest.expTimer) clearInterval(Guest.expTimer);
        const a = Guest.audio;
        if (a) a.pause();
        const root = document.getElementById('guest');
        if (root) {
          root.innerHTML = guestMsgHtml(
            '⌛',
            _t('share.expired_title', '링크가 만료되었습니다'),
            _t('share.expired_msg', '이 공유 터널은 24시간이 지나 닫혔습니다.<br>보낸 분에게 새 링크를 요청하세요.'),
          );
        }
        return;
      }
      el.textContent = _t('share.link_prefix', 'This link: ') + fmtRemain(ms) + ' · ' + _t('share.temp_tunnel', '24h temporary tunnel');
    };
    tick();
    if (Guest.expTimer) clearInterval(Guest.expTimer);
    Guest.expTimer = setInterval(tick, 30000);
  }

  function guestMusicBaseForResolve(opts) {
    opts = opts || {};
    if (opts.musicBase) return String(opts.musicBase).replace(/\/+$/, '');
    const profile = opts.profile;
    if (profile && tunnelHost(profile)) return musicBase(profile);
    if (typeof location !== 'undefined') {
      const h = location.hostname || '';
      if (/^music-\d+\./i.test(h) || h.indexOf('music-') === 0) {
        return location.origin.replace(/\/+$/, '');
      }
      // 포털(remote.whick.org)에서 직접 — 상대 경로 사용
      return location.origin.replace(/\/+$/, '');
    }
    return null;
  }

  function guestDurLabel(sec) {
    if (!sec || sec <= 0) return '—';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function startGuestWithPayload(p, opts) {
    opts = opts || {};
    Guest.toastFn = opts.toast || null;
    const root = document.getElementById('guest');
    const app = document.getElementById('app');
    document.documentElement.classList.add('guest-active');
    if (app) app.style.display = 'none';
    if (!root) return false;
    root.classList.remove('hd');
    root.setAttribute('aria-hidden', 'false');

    try {
      Guest.vol = parseInt(localStorage.getItem('whick_guest_volume'), 10);
      if (isNaN(Guest.vol)) Guest.vol = 70;
      Guest.muted = localStorage.getItem('whick_guest_muted') === '1';
    } catch (_) {}

    if (p.exp && Date.now() > p.exp) {
      root.innerHTML = guestMsgHtml(
        '⌛',
        _t('share.expired_title', '링크가 만료되었습니다'),
        _t('share.expired_msg', '이 공유 터널은 24시간이 지나 닫혔습니다.<br>보낸 분에게 새 링크를 요청하세요.'),
      );
      return true;
    }
    const tracks = normalizeTracksFromPayload(p);
    if (!tracks.length) {
      root.innerHTML = guestMsgHtml(
        '🎵',
        _t('share.no_tracks_title', '공유된 곡이 없습니다'),
        _t('share.no_tracks_msg', '이 링크에는 재생할 곡이 담겨 있지 않습니다.'),
      );
      return true;
    }
    Guest.payload = p;
    Guest.tracks = tracks;
    Guest.idx = 0;
    Guest.playing = false;
    renderGuestShell();
    bindGuestKeys();
    guestLoad(0, false);
    startGuestExpiryTick();
    return true;
  }

  function initGuestPlayer(token, opts) {
    opts = opts || {};
    const root = document.getElementById('guest');
    if (!root) return false;

    const p = resolveSharePayload(token);
    if (!p) {
      root.classList.remove('hd');
      document.documentElement.classList.add('guest-active');
      const app = document.getElementById('app');
      if (app) app.style.display = 'none';
      root.innerHTML = guestMsgHtml(
        '🔌',
        _t('share.invalid_link_title', '링크를 열 수 없습니다'),
        _t('share.invalid_link_msg', '공유 링크가 손상되었거나 형식이 올바르지 않습니다.'),
      );
      return true;
    }
    return startGuestWithPayload(p, opts);
  }

  async function initGuestFromShortLink(code, opts) {
    opts = opts || {};
    const root = document.getElementById('guest');
    if (!root) return false;
    document.documentElement.classList.add('guest-active');
    const app = document.getElementById('app');
    if (app) app.style.display = 'none';
    root.classList.remove('hd');
    root.innerHTML =
      '<div class="guest-top"><span class="guest-brand">WHICK</span></div>' +
      '<div class="guest-msg"><div class="guest-msg-ic">⏳</div>' +
      '<div class="guest-msg-t">' + _t('share.connecting', 'Connecting…') + '</div></div>';

    const c = String(code || '').trim().toLowerCase();
    try {
      const resp = await fetch(SHARE_API_BASE + '/share/l/' + encodeURIComponent(c), {
        credentials: 'omit',
      });
      if (resp.status === 410) {
        root.innerHTML = guestMsgHtml(
          '⌛',
          _t('share.expired_title', '링크가 만료되었습니다'),
          _t('share.expired_msg', '이 공유 터널은 24시간이 지나 닫혔습니다.<br>보낸 분에게 새 링크를 요청하세요.'),
        );
        return true;
      }
      if (!resp.ok) throw new Error('resolve failed');
      const json = await resp.json();
      const data = json.data || json;
      if (data.guest_token) {
        return initGuestFromGt(data.guest_token, {
          profile: opts.profile,
          toast: opts.toast,
          musicBase: data.music_base,
        });
      }
      throw new Error('empty share');
    } catch (_) {
      root.innerHTML = guestMsgHtml(
        '🔌',
        _t('share.load_failed_title', '공유를 불러올 수 없습니다'),
        _t('share.load_failed_msg', '링크가 만료되었거나 올바르지 않습니다.<br>보낸 분에게 새 링크를 요청하세요.'),
      );
      return false;
    }
  }

  async function initGuestFromGt(gt, opts) {
    opts = opts || {};
    const root = document.getElementById('guest');
    if (!root) return false;
    document.documentElement.classList.add('guest-active');
    const app = document.getElementById('app');
    if (app) app.style.display = 'none';
    root.classList.remove('hd');
    root.innerHTML =
      '<div class="guest-top"><span class="guest-brand">WHICK</span></div>' +
      '<div class="guest-msg"><div class="guest-msg-ic">⏳</div>' +
      '<div class="guest-msg-t">' + _t('share.connecting', 'Connecting…') + '</div></div>';

    const mb = guestMusicBaseForResolve(opts);
    if (!mb) {
      root.innerHTML = guestMsgHtml(
        '🔌',
        _t('share.server_unreachable_title', '뮤직서버에 연결할 수 없습니다'),
        _t('share.server_unreachable_msg', '게스트 링크는 <b>고객 뮤직서버 터널</b> 주소에서 열어야 합니다.'),
      );
      return false;
    }
    try {
      const resp = await fetch(
        mb + '/api/guest/shares/resolve?gt=' + encodeURIComponent(gt),
      );
      if (!resp.ok) throw new Error('resolve failed');
      const data = await resp.json();
      const expMs = data.expires_at
        ? new Date(data.expires_at).getTime()
        : Date.now() + TTL_MS;
      const th = tunnelHost(opts.profile) || (typeof location !== 'undefined' ? location.hostname : '');
      const payload = {
        v: 4,
        title: data.title || _t('share.recommend_title', '추천곡'),
        th: th,
        mb: mb,
        gt: gt,
        exp: expMs,
        tr: (data.tracks || []).map(function (t) {
          return {
            i: t.track_id,
            t: t.title,
            a: t.artist || '—',
            al: t.album || '',
            d: guestDurLabel(t.duration_sec),
            q: t.quality || '',
            e: '🎵',
            p: trackStreamPath({ id: t.track_id }, gt),
          };
        }),
      };
      return startGuestWithPayload(payload, opts);
    } catch (_) {
      root.innerHTML = guestMsgHtml(
        '🔌',
        _t('share.load_failed_title', '공유를 불러올 수 없습니다'),
        _t('share.load_failed_msg2', '링크가 만료되었거나 뮤직서버에 연결할 수 없습니다.<br>보낸 분에게 새 링크를 요청하세요.'),
      );
      return false;
    }
  }

  /** 공유 결과 패널 — 링크 1곳 + 하단 버튼 3개 */
  function renderShareResultHtml(board, crossUrl, profile, now, opts) {
    opts = opts || {};
    const shortUrl = opts.shortUrl || board.shareShortLink || null;
    const shareUrl = shortUrl || crossUrl;
    return (
      '<div class="share-result-body" data-share-url="' +
      escAttr(shareUrl) +
      '" data-share-title="' +
      escAttr(board.title || '') +
      '">' +
      '<div class="share-card">' +
      '<div class="share-card-title">' +
      esc(board.title) +
      '</div>' +
      '<div class="share-card-sub">' + _t('share.card_sub', '24 hours · tap the link to play') + '</div>' +
      '<div class="share-card-url" style="cursor:pointer" onclick="WhickShare.copyShareLink(\'' +
      escAttr(shareUrl) +
      '\', libToast || function(){})">' +
      esc(shareUrl) +
      '</div>' +
      '</div>' +
      '<div class="share-btns">' +
      '<button type="button" class="share-btn share-btn--pri share-btn--copy">' + _t('share.copy_link', '📋 Copy link') + '</button>' +
      '<button type="button" class="share-btn share-btn--share">' + _t('share.mobile_share', '📤 Share') + '</button>' +
      '<button type="button" class="share-btn share-btn--preview">' + _t('share.preview', '▶ Preview') + '</button>' +
      '</div></div>'
    );
  }

  global.WhickShare = {
    TTL_MS: TTL_MS,
    PROD_PLAYER_PATH: PROD_PLAYER_PATH,
    tunnelHost: tunnelHost,
    musicBase: musicBase,
    sharePageUrl: sharePageUrl,
    newGuestToken: newGuestToken,
    trackStreamPath: trackStreamPath,
    resolveStreamUrl: resolveStreamUrl,
    encodePayload: encodePayload,
    decodePayload: b64urlDecode,
    buildShareUrl: buildShareUrl,
    buildShareUrlPreview: buildShareUrlPreview,
    buildShareUrlCrossDevice: buildShareUrlCrossDevice,
    buildShareUrlFull: buildShareUrlFull,
    buildShareMessage: buildShareMessage,
    registerShortLinkOnServer: registerShortLinkOnServer,
    shortLinkUrl: shortLinkUrl,
    SHARE_PUBLIC_ORIGIN: SHARE_PUBLIC_ORIGIN,
    registerGuestShareOnServer: registerGuestShareOnServer,
    parseShareHash: parseShareHash,
    resolveSharePayload: resolveSharePayload,
    fmtRemain: fmtRemain,
    initGuestPlayer: initGuestPlayer,
    initGuestFromGt: initGuestFromGt,
    initGuestFromShortLink: initGuestFromShortLink,
    renderShareResultHtml: renderShareResultHtml,
    bindShareResultActions: bindShareResultActions,
    mobileNativeShare: mobileNativeShare,
    copyShareLink: copyShareLink,
    guestLoad: guestLoad,
    guestToggle: guestToggle,
    guestNext: guestNext,
    guestPrev: guestPrev,
    guestToggleMute: guestToggleMute,
    guestSetVolume: guestSetVolume,
  };
})(typeof window !== 'undefined' ? window : globalThis);
