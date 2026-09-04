/**
 * Whick Remote — Spotify · Tidal 연결 마법사 (소비자 친화 UX)
 * SSOT: 3_product/docs/EXTERNAL-PROVIDERS-DESIGN.md
 */
(function (global) {
  'use strict';

  const PROVIDER_META = {
    spotify: {
      name: 'Spotify',
      icon: '🎧',
      color: '#1DB954',
      premium: _t('str.spotify_premium', 'Spotify Premium 구독이 필요합니다'),
    },
    tidal: {
      name: 'Tidal',
      icon: '🌊',
      color: '#000000',
      premium: _t('str.tidal_premium', 'Tidal HiFi 또는 HiFi Plus 구독이 필요합니다'),
    },
  };

  const PRODUCT_FULLPLAY_NOTE =
    _t('str.fullplay_note', 'Personal <strong>paid account</strong> (Spotify Premium · Tidal HiFi/Plus) auth enables <strong>full playback</strong> · mini PC DSP · DAC output');

  function el(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/"/g, '&quot;');
  }

  function statusBadge(status) {
    const map = {
      connected: { t: _t('str.connected', '연결됨'), cls: 'str-badge--ok' },
      awaiting_connect: { t: _t('str.awaiting_connect', '연결 대기'), cls: 'str-badge--wait' },
      awaiting_code: { t: _t('str.awaiting_code', '코드 입력 대기'), cls: 'str-badge--wait' },
      disconnected: { t: _t('str.disconnected', '미연결'), cls: 'str-badge--off' },
    };
    const m = map[status] || map.disconnected;
    return `<span class="str-badge ${m.cls}">${m.t}</span>`;
  }

  class WhickStreamingWizard {
    constructor(api) {
      this.api = api;
      this._provider = null;
      this._pollTimer = null;
      this._status = null;
    }

    async refreshCards() {
      const wrap = el('streaming-providers');
      if (!wrap) return;
      try {
        const data = await this.api.getStreamingStatus();
        if (!data.ok) return;
        this._status = data;
        this._renderCards(data);
      } catch (e) {
        if (String(e.message || e).includes('503') || String(e.message || e).includes('NOT_CONFIGURED')) {
          this._status = {
            ok: true,
            providers: {
              spotify: { status: 'disconnected', account_label: PROVIDER_META.spotify.premium },
              tidal: { status: 'disconnected', account_label: PROVIDER_META.tidal.premium },
            },
          };
          this._renderCards(this._status);
        } else {
          wrap.innerHTML =
            '<p class="str-hint str-hint--err">' + _t('str.status_failed', 'Could not load status · check the server connection') + '</p>';
        }
      }
    }

    _renderCards(data) {
      const wrap = el('streaming-providers');
      if (!wrap) return;
      const ps = data.providers || {};
      wrap.innerHTML = ['spotify', 'tidal']
        .map((id) => {
          const meta = PROVIDER_META[id];
          const p = ps[id] || {};
          const label = p.account_label || meta.premium;
          const productNote = `<p class="str-wiz-tip" style="margin-top:8px">${PRODUCT_FULLPLAY_NOTE}</p>`;
          const actions =
            p.status === 'connected'
              ? `<button type="button" class="str-btn str-btn--ghost" data-action="manage" data-provider="${id}">${_t('str.manage', 'Manage')}</button>`
              : `<button type="button" class="str-btn str-btn--primary" data-action="connect" data-provider="${id}">${
                  id === 'tidal' ? _t('str.connect_code', 'Connect with code') : _t('str.connect', 'Connect')
                }</button>`;
          return `
        <div class="str-card" data-provider="${id}">
          <div class="str-card-head">
            <span class="str-card-ic">${meta.icon}</span>
            <div class="str-card-titles">
              <div class="str-card-name">${meta.name}</div>
              <div class="str-card-sub">${esc(label)}</div>
            </div>
            ${statusBadge(p.status)}
          </div>
          <div class="str-card-actions">${actions}</div>
          ${productNote}
        </div>`;
        })
        .join('');

      wrap.querySelectorAll('[data-action]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const prov = btn.getAttribute('data-provider');
          const act = btn.getAttribute('data-action');
          if (act === 'connect') this.openWizard(prov);
          else this.openWizard(prov, true);
        });
      });
    }

    openWizard(provider, manage) {
      this._provider = provider;
      this._stopPoll();
      const ov = el('streaming-wizard-overlay');
      if (!ov) return;
      ov.classList.add('open');
      ov.setAttribute('data-provider', provider);
      if (manage) this._renderManage(provider);
      else if (provider === 'spotify') this._startSpotify();
      else if (provider === 'tidal') this._startTidal();
    }

    closeWizard() {
      this._stopPoll();
      el('streaming-wizard-overlay')?.classList.remove('open');
      this.refreshCards();
    }

    _stopPoll() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    }

    _setWizardBody(html) {
      const body = el('streaming-wizard-body');
      if (body) body.innerHTML = html;
    }

    _renderSteps(steps, current) {
      return (
        '<ol class="str-steps">' +
        steps
          .map(
            (s, i) =>
              `<li class="str-step${i + 1 === current ? ' str-step--on' : i + 1 < current ? ' str-step--done' : ''}"><span class="str-step-n">${i + 1}</span><span class="str-step-t">${esc(s)}</span></li>`,
          )
          .join('') +
        '</ol>'
      );
    }

    _renderManage(provider) {
      const meta = PROVIDER_META[provider];
      const p = this._status?.providers?.[provider] || {};
      this._setWizardBody(`
        <div class="str-wiz-head">
          <span class="str-wiz-ic">${meta.icon}</span>
          <h3>${_t('str.manage_title', 'Manage')} ${meta.name}</h3>
        </div>
        <p class="str-wiz-lead">${statusBadge(p.status)} · ${esc(p.account_label || _t('str.connected', '연결됨'))}</p>
        <p class="str-wiz-note">${PRODUCT_FULLPLAY_NOTE}</p>
        <div class="str-wiz-actions">
          <button type="button" class="str-btn str-btn--ghost" id="str-wiz-close">' + _t('common.close', 'Close') + '</button>
          <button type="button" class="str-btn str-btn--danger" id="str-wiz-disconnect">' + _t('str.disconnect', 'Disconnect') + '</button>
        </div>
      `);
      el('str-wiz-close')?.addEventListener('click', () => this.closeWizard());
      el('str-wiz-disconnect')?.addEventListener('click', () => this._disconnect(provider));
    }

    async _disconnect(provider) {
      if (!confirm(_t('str.disconnect_confirm', 'Disconnect') + ' ' + PROVIDER_META[provider].name + '?')) return;
      try {
        if (provider === 'spotify') await this.api.disconnectSpotify();
        else await this.api.disconnectTidal();
        this.closeWizard();
      } catch (e) {
        alert(_t('str.disconnect_failed', 'Disconnect failed — ') + (e.message || e));
      }
    }

    async _startSpotify() {
      const meta = PROVIDER_META.spotify;
      const device = this._status?.spotify_device_name || 'Whick Player';
      this._setWizardBody(`
        <div class="str-wiz-head"><span class="str-wiz-ic">${meta.icon}</span><h3>${meta.name} ${_t('str.connect_title', 'connection')}</h3></div>
        <p class="str-wiz-lead">${_t('str.spotify_lead', 'Connect with just the <strong>Spotify app</strong> — no password needed.')}<br><span class="str-muted">${PRODUCT_FULLPLAY_NOTE}</span></p>
        <div class="str-loading">' + _t('str.preparing', 'Preparing…') + '</div>
      `);
      try {
        const data = await this.api.startSpotifyConnect();
        if (data.already_connected) {
          this._renderManage('spotify');
          return;
        }
        const steps = data.steps || [
          _t('str.step1', '폰에서 Spotify 앱을 여세요'),
          _t('str.step2', '재생 화면에서 「기기로 재생」(Connect)을 탭하세요'),
          `${_t('str.step3_prefix', 'Select')} "${device}"`,
          _t('str.step4', '아래 「연결 확인」을 누르세요'),
        ];
        this._setWizardBody(`
          <div class="str-wiz-head"><span class="str-wiz-ic">${meta.icon}</span><h3>${meta.name} ${_t('str.connect_title', 'connection')}</h3></div>
          <p class="str-wiz-lead">${_t('str.follow_steps', 'Follow the steps below.')} <span class="str-muted">${meta.premium}</span></p>
          ${this._renderSteps(steps, 2)}
          <div class="str-device-box">
            <div class="str-device-lbl">${_t('str.device_label', 'Device name shown on the mini PC')}</div>
            <div class="str-device-name">${esc(device)}</div>
          </div>
          <p class="str-wiz-tip">💡 ${_t('str.connect_icon_tip', 'The Connect icon looks like a speaker/TV at the bottom of the play screen.')}</p>
          <div class="str-wiz-actions">
            <button type="button" class="str-btn str-btn--ghost" id="str-wiz-cancel">' + _t('common.cancel', 'Cancel') + '</button>
            <button type="button" class="str-btn str-btn--primary" id="str-wiz-spotify-check">' + _t('str.check_connection', 'Check connection') + '</button>
          </div>
        `);
        el('str-wiz-cancel')?.addEventListener('click', () => this.closeWizard());
        el('str-wiz-spotify-check')?.addEventListener('click', () => this._completeSpotify());
      } catch (e) {
        this._setWizardBody(
          `<p class="str-hint str-hint--err">${_t('str.start_failed', 'Start failed — ')}${esc(e.message || e)}</p>`,
        );
      }
    }

    async _completeSpotify() {
      const btn = el('str-wiz-spotify-check');
      if (btn) {
        btn.disabled = true;
        btn.textContent = _t('str.checking', '확인 중…');
      }
      try {
        const data = await this.api.completeSpotifyConnect();
        if (data.connected) {
          await this._maybeSpotifyOAuth();
        } else {
          if (btn) {
            btn.disabled = false;
            btn.textContent = _t('str.check_connection', '연결 확인');
          }
          alert(
            data.message ||
              _t('str.not_connected_yet', 'Not connected yet.\nIn the Spotify app: Devices → select Whick Player, then check again.'),
          );
        }
      } catch (e) {
        if (btn) {
          btn.disabled = false;
          btn.textContent = _t('str.check_connection', '연결 확인');
        }
        alert(_t('str.check_failed', 'Check failed — ') + (e.message || e));
      }
    }

    async _maybeSpotifyOAuth() {
      try {
        const oauth = await this.api.getSpotifyOAuthStatus();
        if (oauth.web_api_connected || !oauth.oauth_available) {
          const doneMsg = _t('str.spotify_done_msg', 'You can now control search & playback from the Whick remote.<br>Tracks play via the librespot → CamillaDSP → DAC path.');
          this._setWizardBody(`
            <div class="str-success">✓ ${_t('str.spotify_done_short', 'Spotify connected')}</div>
            <p class="str-wiz-lead">${doneMsg}</p>
            <div class="str-wiz-actions"><button type="button" class="str-btn str-btn--primary" id="str-wiz-done">' + _t('common.ok', 'OK') + '</button></div>
          `);
          el('str-wiz-done')?.addEventListener('click', () => this.closeWizard());
          return;
        }
        const start = await this.api.startSpotifyOAuth();
        this._setWizardBody(`
          <div class="str-success">✓ ${_t('str.connect_done_short', 'Spotify Connect complete')}</div>
          <p class="str-wiz-lead">${_t('str.oauth_lead2', 'One more Spotify approval is needed for search & playback in Whick.<br>Your password is never stored in Whick.')}</p>
          ${this._renderSteps(start.steps || [_t('str.oauth_step1', '브라우저에서 Spotify 로그인'), '승인 후 이 화면으로 돌아오기'], 1)}
          <div class="str-wiz-actions">
            <button type="button" class="str-btn str-btn--ghost" id="str-wiz-oauth-skip">' + _t('str.later', 'Later') + '</button>
            <a class="str-btn str-btn--primary" id="str-wiz-oauth-open" href="${esc(start.auth_url)}" target="_blank" rel="noopener">${_t('str.spotify_login', 'Spotify login')}</a>
          </div>
          <p class="str-wiz-tip" id="str-oauth-poll-msg">${_t('str.oauth_poll', 'Will complete automatically after approval…')}</p>
        `);
        el('str-wiz-oauth-skip')?.addEventListener('click', () => this.closeWizard());
        this._pollSpotifyOAuth();
      } catch (e) {
        this._setWizardBody(`
          <div class="str-success">✓ ${_t('str.connect_done_short', 'Spotify Connect complete')}</div>
          <p class="str-hint str-hint--err">${_t('str.webapi_check', 'Web API config check — ')}${esc(e.message || e)}</p>
          <div class="str-wiz-actions"><button type="button" class="str-btn str-btn--primary" id="str-wiz-done">' + _t('common.ok', 'OK') + '</button></div>
        `);
        el('str-wiz-done')?.addEventListener('click', () => this.closeWizard());
      }
    }

    _pollSpotifyOAuth() {
      this._stopPoll();
      const poll = async () => {
        try {
          const st = await this.api.getSpotifyOAuthStatus();
          if (st.web_api_connected) {
            this._stopPoll();
            this._setWizardBody(`
              <div class="str-success">✓ ${_t('str.search_ready', 'Spotify search & playback ready')}</div>
              <p class="str-wiz-lead">${_t('str.search_ready_msg', 'Spotify results can now be played in Whick AI Search.')}</p>
              <div class="str-wiz-actions"><button type="button" class="str-btn str-btn--primary" id="str-wiz-done">' + _t('common.ok', 'OK') + '</button></div>
            `);
            el('str-wiz-done')?.addEventListener('click', () => this.closeWizard());
          }
        } catch (e) {
          const msg = el('str-oauth-poll-msg');
          if (msg) msg.textContent = _t('str.oauth_checking', 'Checking approval…');
        }
      };
      poll();
      this._pollTimer = setInterval(poll, 3000);
    }

    async _startTidal() {
      const meta = PROVIDER_META.tidal;
      this._setWizardBody(`
        <div class="str-wiz-head"><span class="str-wiz-ic">${meta.icon}</span><h3>${meta.name} ${_t('str.connect_title', 'connection')}</h3></div>
        <p class="str-wiz-lead">${_t('str.tidal_lead', 'Link your Tidal account with a <strong>device code</strong>, like a TV app.')} 비밀번호는 Whick에 저장하지 않습니다.<br><span class="str-muted">${PRODUCT_FULLPLAY_NOTE}</span></p>
        <div class="str-loading">${_t('str.code_issuing', 'Issuing code…')}</div>
      `);
      try {
        const data = await this.api.startTidalConnect();
        if (data.ok === false) {
          const err = String(data.error || '');
          const msg = err.includes('WHICK_TIDAL_CLIENT_ID') || err.includes('missing_client_id')
            ? _t('str.tidal_not_ready', 'Tidal connection is not ready yet. Customers connect with just a paid Tidal account — no API key needed.')
            : err || _t('str.tidal_start_failed', 'Cannot start Tidal connection');
          this._setWizardBody(
            `<p class="str-hint str-hint--err">${esc(msg)}</p>`,
          );
          return;
        }
        if (data.already_connected) {
          this._renderManage('tidal');
          return;
        }
        const t = data.tidal || {};
        const steps = data.steps || [
          _t('str.step_code', '아래 코드를 확인하세요'),
          _t('str.step_tidal_login', 'link.tidal.com 에서 Tidal 로그인'),
          _t('str.step_tidal_approve', '코드 입력 후 승인'),
          _t('str.step_tidal_auto', '자동으로 연결 완료'),
        ];
        this._setWizardBody(`
          <div class="str-wiz-head"><span class="str-wiz-ic">${meta.icon}</span><h3>${meta.name} ${_t('str.connect_title', 'connection')}</h3></div>
          <p class="str-wiz-lead"><span class="str-muted">${meta.premium}</span></p>
          ${this._renderSteps(steps, 2)}
          <div class="str-code-box">
            <div class="str-code-lbl">${_t('str.code_label', 'Code to enter')}</div>
            <div class="str-code-val" id="str-tidal-code">${esc(t.user_code || '----')}</div>
            <button type="button" class="str-btn str-btn--link" id="str-tidal-copy">${_t('str.copy_code', 'Copy code')}</button>
          </div>
          <a class="str-btn str-btn--primary str-btn--block" id="str-tidal-open" href="${esc(t.verification_uri_complete || 'https://link.tidal.com')}" target="_blank" rel="noopener">${_t('str.open_link_tidal', 'Open link.tidal.com')}</a>
          <p class="str-wiz-tip" id="str-tidal-poll-msg">${_t('str.tidal_poll', 'Waiting for approval… keep this screen open')}</p>
          <div class="str-wiz-actions">
            <button type="button" class="str-btn str-btn--ghost" id="str-wiz-tidal-cancel">' + _t('common.cancel', 'Cancel') + '</button>
          </div>
        `);
        el('str-wiz-tidal-cancel')?.addEventListener('click', () => this.closeWizard());
        el('str-tidal-copy')?.addEventListener('click', () => {
          const code = t.user_code || '';
          if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(code.replace(/-/g, '')).then(
              () => alert(_t('str.code_copied', '코드가 복사되었습니다')),
              () => alert(code),
            );
          } else {
            alert(code);
          }
        });
        this._pollTidal(Number(t.poll_interval || 5) * 1000);
      } catch (e) {
        this._setWizardBody(
          `<p class="str-hint str-hint--err">${_t('str.start_failed', 'Start failed — ')}${esc(e.message || e)}</p>`,
        );
      }
    }

    _pollTidal(intervalMs) {
      this._stopPoll();
      const poll = async () => {
        try {
          const data = await this.api.pollTidalConnect();
          if (data.connected) {
            this._stopPoll();
            this._setWizardBody(`
              <div class="str-success">✓ ${_t('str.tidal_done_short', 'Tidal connected')}</div>
              <p class="str-wiz-lead">${_t('str.tidal_done_msg', 'HiFi tracks play through the mini PC DSP path.')}</p>
              <p class="str-wiz-tip">${_t('str.tidal_full_note', 'Authenticated with a paid account — full playback available.')}</p>
              <div class="str-wiz-actions"><button type="button" class="str-btn str-btn--primary" id="str-wiz-done">' + _t('common.ok', 'OK') + '</button></div>
            `);
            el('str-wiz-done')?.addEventListener('click', () => this.closeWizard());
          } else if (data.ok === false && data.error) {
            this._stopPoll();
            this._setWizardBody(
              `<p class="str-hint str-hint--err">${esc(data.error)}</p>`,
            );
          }
        } catch (e) {
          const msg = el('str-tidal-poll-msg');
          if (msg) msg.textContent = _t('str.checking_conn', 'Checking connection…') + ' (' + (e.message || _t('common.retry', '재시도')) + ')';
        }
      };
      poll();
      this._pollTimer = setInterval(poll, Math.max(intervalMs, 3000));
    }
  }

  function initWhickStreamingWizard(api) {
    const wizard = new WhickStreamingWizard(api);
    el('streaming-wizard-close')?.addEventListener('click', () => wizard.closeWizard());
    el('streaming-wizard-overlay')?.addEventListener('click', (ev) => {
      if (ev.target?.id === 'streaming-wizard-overlay') wizard.closeWizard();
    });
    api.on('connected', () => wizard.refreshCards());
    return wizard;
  }

  global.WhickStreamingWizard = WhickStreamingWizard;
  global.initWhickStreamingWizard = initWhickStreamingWizard;
})(typeof window !== 'undefined' ? window : globalThis);
