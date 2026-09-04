/**
 * Whick Remote — 공간음향 마법사 (모바일 SSOT)
 * 스마트폰 마이크 + 뮤직서버 스윕 재생
 */
(function (g) {
  'use strict';

  var Sweep = g.WhickRoomSweep;
  var Analyze = g.WhickRoomAnalyze;

  function _t(key, fb) {
    if (g.WhickI18n && typeof g.WhickI18n.t === 'function') {
      var v = g.WhickI18n.t(key);
      if (v && v !== key) return v;
    }
    return fb;
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function detectMicPlatform() {
    var ua = navigator.userAgent || '';
    var isIOS =
      /iPad|iPhone|iPod/i.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    var isAndroid = /Android/i.test(ua);
    return { isIOS: isIOS, isAndroid: isAndroid, host: location.hostname || _t('sp.remote', '리모컨') };
  }

  function getUserMedia(constraints) {
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      return navigator.mediaDevices.getUserMedia(constraints);
    }
    return Promise.reject(new Error(_t('sp.no_mic', '마이크를 지원하지 않는 브라우저입니다.')));
  }

  function RemoteSpatialWizard(api, rootEl) {
    this.api = api;
    this.root = rootEl && rootEl.id !== 'dsp-speaker-dir-root' ? rootEl : null;
    this._roots = this.root ? [this.root] : [];
    this._speakersRoot = rootEl && rootEl.id === 'dsp-speaker-dir-root' ? rootEl : null;
    this.phase = 'hub';
    this.busy = false;
    this.error = '';
    this.l1PointIndex = 0;
    this.l1PointTotal = 5;
    this.l1Runs = [];
    this.result = null;
    this.micStream = null;
    this.micReady = false;
    this._micPerm = 'unknown';
    this._activeRunId = '';
    this._measureGen = 0;
    this.swapChannels = false;
    this._toneBusy = '';
    this.positions = (Analyze && Analyze.positions) || [
      { n: 1, label: _t('sp.pos1', '① 코 바로앞') },
      { n: 2, label: _t('sp.pos2', '② 왼쪽 30cm') },
      { n: 3, label: _t('sp.pos3', '③ 오른쪽 30cm') },
      { n: 4, label: _t('sp.pos4', '④ 앞쪽 50cm') },
      { n: 5, label: _t('sp.pos5', '⑤ 뒤쪽 50cm') },
    ];
    this.deviceProfile = Analyze && Analyze.detectDevice ? Analyze.detectDevice() : { id: 'generic', label: _t('sp.generic', '일반') };

    var self = this;
    this._onSpatial = function (st) {
      self.onSpatialEvent(st);
    };
    this.api.on('spatial', this._onSpatial);
    if (rootEl) this._bindRoot(rootEl);
    if (this.api.getDspProfile) {
      this.api
        .getDspProfile()
        .then(function (prof) {
          var dsp = (prof && prof.dsp) || {};
          if (dsp.swapChannels) {
            self.swapChannels = true;
            self.render();
          }
        })
        .catch(function () {});
    }
    this.render();
  }

  RemoteSpatialWizard.prototype._bindRoot = function (el) {
    if (!el || el._spatialBound) return;
    el._spatialBound = true;
    var self = this;
    el.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-sp-action]');
      if (!btn || btn.disabled || !el.contains(btn)) return;
      self.onAction(btn.getAttribute('data-sp-action'));
    });
  };

  RemoteSpatialWizard.prototype.addRoot = function (el) {
    if (!el) return;
    if (el.id === 'dsp-speaker-dir-root') {
      this._speakersRoot = el;
      this._bindRoot(el);
      this.render();
      return;
    }
    if (this._roots.indexOf(el) < 0) {
      this._roots.push(el);
      this._bindRoot(el);
    }
    if (!this.root) this.root = el;
    this.render();
  };

  RemoteSpatialWizard.prototype.posLabel = function () {
    var p = this.positions[this.l1PointIndex];
    return p ? p.label : _t('sp.measure_pos', '측정 위치 ') + (this.l1PointIndex + 1);
  };

  RemoteSpatialWizard.prototype.renderPosCallout = function () {
    return (
      '<div class="sp-pos-callout">' +
      '<span class="sp-pos-callout__step">' + _t('sp.measure', '측정 ') +
      (this.l1PointIndex + 1) +
      ' / ' +
      this.l1PointTotal +
      '</span>' +
      '<p class="sp-pos-callout__label">' +
      esc(this.posLabel()) +
      '</p>' +
      '<p class="sp-pos-callout__hint">' + _t('sp.measure_here', '이 위치에서 측정하세요') + '</p>' +
      '</div>'
    );
  };

  RemoteSpatialWizard.prototype.setError = function (msg) {
    this.error = msg || '';
    this.render();
  };

  RemoteSpatialWizard.prototype.setPhase = function (p) {
    this.phase = p;
    this.render();
  };

  RemoteSpatialWizard.prototype.stopMic = function () {
    if (this.micStream) {
      this.micStream.getTracks().forEach(function (t) {
        t.stop();
      });
      this.micStream = null;
    }
    this.micReady = false;
  };

  RemoteSpatialWizard.prototype.micStillLive = function () {
    if (!this.micStream || !this.micStream.getAudioTracks) return false;
    return this.micStream.getAudioTracks().some(function (tr) {
      return tr.readyState === 'live';
    });
  };

  /** 진행 중 측정·분석 콜백 무효화 (스윕 중 초기화 시 필수) */
  RemoteSpatialWizard.prototype.abortMeasure = function () {
    this._measureGen += 1;
    this._activeRunId = '';
    this.busy = false;
  };

  /** 측정 진행 초기화 — 마이크는 유지하고 1포인트부터 다시 */
  RemoteSpatialWizard.prototype.resetProgress = function () {
    this.abortMeasure();
    this.l1Runs = [];
    this.l1PointIndex = 0;
    this.result = null;
    this.error = '';
    if (this.api.spatialReset) this.api.spatialReset();
    if (this.micStillLive()) {
      this.micReady = true;
      this.setPhase('points');
    } else {
      this.stopMic();
      this.setPhase('hub');
    }
  };

  RemoteSpatialWizard.prototype._armResetGuard = function (ms) {
    this._resetGuardUntil = Date.now() + (ms || 600);
  };

  RemoteSpatialWizard.prototype.onAction = function (action) {
    var self = this;
    this.error = '';
    if (action === 'tone-left') {
      this.playTestTone('left');
      return;
    }
    if (action === 'tone-right') {
      this.playTestTone('right');
      return;
    }
    if (action === 'speakers-apply') {
      this.confirmSpeakers();
      return;
    }
    if (action === 'multi5') {
      this.abortMeasure();
      this.l1PointTotal = 5;
      this.l1PointIndex = 0;
      this.l1Runs = [];
      this.result = null;
      this.setPhase('points');
      return;
    }
    if (action === 'single1') {
      this.abortMeasure();
      this.l1PointTotal = 1;
      this.l1PointIndex = 0;
      this.l1Runs = [];
      this.result = null;
      this.setPhase('points');
      return;
    }
    if (action === 'mic-prepare') {
      this.prepareMic();
      return;
    }
    if (action === 'measure') {
      this.startMeasure();
      return;
    }
    if (action === 'apply') {
      this.applyPeq();
      return;
    }
    if (action === 'reset') {
      // 측정 직후 레이아웃 전환으로 초기화 버튼이 탭에 맞으면 비프가 끊김
      if (this._resetGuardUntil && Date.now() < this._resetGuardUntil) {
        return;
      }
      this.resetProgress();
      return;
    }
    if (action === 'hub') {
      this.setPhase('hub');
    }
    if (action === 'speakers-back') {
      if (typeof g.openSgAcc === 'function') g.openSgAcc('sec-dsp');
      var spEl = document.getElementById('dsp-speaker-dir-root');
      if (spEl) spEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // 테스트 톤 정리
      if (self.api.stop) self.api.stop().catch(function(){});
      return;
    }
  };

  RemoteSpatialWizard.prototype.playTestTone = function (channel) {
    var self = this;
    if (!this.api.playTestTone) {
      this.setError(_t('sp.tone_unavailable', '테스트 톤 API를 사용할 수 없습니다.'));
      return;
    }
    this._toneBusy = channel === 'right' ? 'right' : 'left';
    this.busy = true;
    this.render();
    // 서버가 프로필 swap으로 파일을 선반전하면 Camilla와 이중적용되어 토글이 안 들림.
    // 명시적으로 false — Camilla mixer만 적용 (구버전 플레이어 호환).
    this.api
      .playTestTone(channel, { swapChannels: false })
      .then(function () {
        self.busy = false;
        self._toneBusy = '';
        self.render();
      })
      .catch(function (err) {
        self.busy = false;
        self._toneBusy = '';
        self.setError(err.message || _t('sp.tone_failed', '테스트 톤 재생 실패'));
      });
  };

  RemoteSpatialWizard.prototype.confirmSpeakers = function () {
    var self = this;
    if (!this.api.saveChannelSetup) {
      this.render();
      return;
    }
    this.busy = true;
    this.render();
    this.api
      .saveChannelSetup({ swapChannels: this.swapChannels })
      .then(function () {
        self.busy = false;
        self.render();
      })
      .catch(function (err) {
        self.busy = false;
        self.setError(err.message || _t('sp.channel_save_failed', '채널 설정 저장 실패'));
      });
  };

  RemoteSpatialWizard.prototype.prepareMic = function () {
    var self = this;
    this.busy = true;
    this.render();
    if (Sweep && Sweep.unlockPlayback) {
      Sweep.unlockPlayback().catch(function () {});
    }
    getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } })
      .then(function (stream) {
        if (self.micStream) {
          self.micStream.getTracks().forEach(function (t) {
            t.stop();
          });
        }
        self.micStream = stream;
        self.micReady = true;
        self._micPerm = 'granted';
        self.busy = false;
        self.setPhase('points');
      })
      .catch(function (err) {
        self.busy = false;
        self.micReady = false;
        self._micPerm = 'denied';
        self.setPhase('mic-denied');
        self.setError(err.message || _t('sp.mic_permission', '마이크 허용이 필요합니다.'));
      });
  };

  RemoteSpatialWizard.prototype.startMeasure = function () {
    var self = this;
    if (!this.micReady || !this.micStream) {
      this.setError(_t('sp.mic_first', '먼저 마이크 준비를 완료해 주세요.'));
      return;
    }
    if (!Sweep || !Analyze) {
      this.setError(_t('sp.audio_module_failed', '오디오 모듈을 불러오지 못했습니다.'));
      return;
    }
    if (this.busy && this.phase === 'measure') {
      return;
    }
    this._measureGen += 1;
    this._activeRunId = '';
    this.busy = true;
    this.setPhase('measure');
    var started = false;
    var begin = function () {
      // then(begin).catch(begin) 은 begin 이 reject Promise 를 반환하면 두 번 호출됨
      // → spatial_sweep_start 중복 → 스윕 중 mpc clear/재시작(2~3초 끊김)
      if (started) return;
      started = true;
      self.api.spatialSweepStart(self.l1PointIndex, self.l1PointTotal);
    };
    if (Sweep.unlockPlayback) {
      Sweep.unlockPlayback().then(begin, begin);
    } else {
      begin();
    }
  };

  RemoteSpatialWizard.prototype.onSpatialEvent = function (st) {
    var self = this;
    if (!st || st.phase !== 'sweeping' || !st.sweep_at_ms) return;
    if (this._activeRunId === st.run_id) return;
    this._activeRunId = st.run_id;
    if (!this.micStream || this.phase !== 'measure') return;

    var gen = this._measureGen;
    // 폰·서버 벽시계 어긋나면 절대 sweep_at_ms 로 녹음이 너무 일찍 끝남
    // → 이벤트 수신 시각 + lead 로 맞춤
    var leadMs =
      typeof st.sweep_lead_ms === 'number' && st.sweep_lead_ms >= 0
        ? st.sweep_lead_ms
        : Math.max(0, st.sweep_at_ms - Date.now());
    var sweepOpts = {
      sweepAtMs: Date.now() + leadMs,
      mediaStream: this.micStream,
      keepStream: true,
      syncRole: 'mic',
    };

    Sweep.run(sweepOpts)
      .then(function (rec) {
        if (gen !== self._measureGen) return null;
        return self.api
          .analyzeSpatialPoint(rec.samples, rec.sampleRate, {
            deviceProfileId: self.deviceProfile.id,
          })
          .then(function (analyzed) {
            if (gen !== self._measureGen) return;
            self.l1Runs.push(analyzed);
            self.l1PointIndex += 1;
            self.api.spatialPointDone(self.l1Runs.length);
            self._armResetGuard(800);
            if (self.l1Runs.length >= self.l1PointTotal) {
              return self.api
                .averageSpatialRuns(self.l1Runs, self.l1PointTotal)
                .then(function (avg) {
                  if (gen !== self._measureGen) return;
                  self.result = avg;
                  self.busy = false;
                  self.setPhase('result');
                });
            }
            self.busy = false;
            self.setPhase('points');
          });
      })
      .catch(function (err) {
        if (gen !== self._measureGen) return;
        self.busy = false;
        self._armResetGuard(800);
        self.setPhase('points');
        self.setError(err.message || _t('sp.measure_failed', '측정 실패'));
      });
  };

  RemoteSpatialWizard.prototype.applyPeq = function () {
    var self = this;
    if (!this.result || !this.result.peaking) {
      this.setError(_t('sp.no_result', '측정 결과가 없습니다.'));
      return;
    }
    this.busy = true;
    this.render();
    this.api
      .saveRoomCorrection(this.result.peaking)
      .then(function () {
        self.busy = false;
        self.setPhase('applied');
        self.api.spatialSetPhase('applied');
      })
      .catch(function (err) {
        self.busy = false;
        self.setError(err.message || _t('sp.peq_save_failed', 'PEQ 저장 실패'));
      });
  };

  RemoteSpatialWizard.prototype.renderSpeakers = function () {
    var busyLeft = this.busy && this._toneBusy === 'left';
    var busyRight = this.busy && this._toneBusy === 'right';
    var applyDisabled = this.busy ? ' disabled' : '';
    var swapOn = this.swapChannels;
    return (
      '<div class="sp-hero">' +
      '<div class="sp-hero__ic">🔊</div>' +
      '<h2 class="sp-hero__t">' + _t('sp.dirtest_title', '스피커 방향 테스트') + '</h2>' +
      '<p class="sp-hero__d">' + _t('sp.dirtest_desc', '왼쪽·오른쪽을 눌러 소리 방향을 확인하세요. 방향이 반대로 들리면 바로 아래 <strong>스피커 좌우 반전</strong>을 켠 뒤 다시 확인하세요.') + '</p>' +
      '</div>' +
      '<div class="sp-speaker-block">' +
      '<div class="sp-speaker-dir sp-speaker-dir--2">' +
      '<button type="button" class="sp-btn sp-btn--dir' +
      (busyLeft ? ' sp-btn--busy' : '') +
      '" data-sp-action="tone-left"' +
      (this.busy ? ' disabled' : '') +
      '>' +
      (busyLeft ? _t('sp.playing', '재생…') : _t('sp.left', '왼쪽')) +
      '</button>' +
      '<button type="button" class="sp-btn sp-btn--dir' +
      (busyRight ? ' sp-btn--busy' : '') +
      '" data-sp-action="tone-right"' +
      (this.busy ? ' disabled' : '') +
      '>' +
      (busyRight ? _t('sp.playing', '재생…') : _t('sp.right', '오른쪽')) +
      '</button>' +
      '</div>' +
      (swapOn
        ? '<p class="sp-hint sp-hint--ok">' + _t('sp.swap_on', '스피커 좌우 반전 켜짐') + '</p>'
        : '<p class="sp-hint">' + _t('sp.swap_hint', '좌우 반전은 바로 아래 토글에서 조절합니다.') + '</p>') +
      '<button type="button" class="sp-btn sp-btn--primary" data-sp-action="speakers-apply"' +
      applyDisabled +
      '>' + _t('sp.ok', '확인') + '</button>' +
      '</div>'
    );
  };

  RemoteSpatialWizard.prototype.renderHub = function () {
    var wizard = this;
    var hubDesc = _t('sp.hub_desc', '스마트폰에서 측정한 데이터가 뮤직서버에 저장됩니다.');
    var speakerLabel = _t('sp.server_speaker', '서버 스피커');
    return (
      '<div class="sp-hero">' +
      '<div class="sp-hero__ic">🔮</div>' +
      '<h2 class="sp-hero__t">' + _t('sp.wizard_title', '공간음향 마법사') + '</h2>' +
      '<p class="sp-hero__d">' +
      hubDesc +
      '</p>' +
      '</div>' +
      '<div class="sp-pill-row">' +
      '<span class="sp-pill on"><span class="dot"></span> ' +
      esc(speakerLabel) +
      '</span>' +
      '<span class="sp-pill"><span class="dot"></span> ' +
      esc(this.deviceProfile.label || _t('sp.smartphone', '스마트폰')) +
      '</span>' +
      (function () {
        var swapOn = wizard.swapChannels;
        return swapOn
          ? '<span class="sp-pill on"><span class="dot"></span> L/R ' + _t('sp.swap', '반전') + '</span>'
          : '<span class="sp-pill"><span class="dot"></span> L/R ' + _t('sp.normal', '정상') + '</span>';
      })() +
      '</div>' +
      '<div class="sp-actions">' +
      '<button type="button" class="sp-btn sp-btn--primary" data-sp-action="multi5">' + _t('sp.multi5', '5포인트 측정 (권장)') + '</button>' +
      '<button type="button" class="sp-btn sp-btn--ghost" data-sp-action="single1">' + _t('sp.single1', '1회 빠른 측정') + '</button>' +
      '<button type="button" class="sp-btn sp-btn--ghost sp-btn--sm" data-sp-action="speakers-back">' + _t('sp.dir_check', '스피커 방향 다시 확인') + '</button>' +
      '</div>' +
      '<p class="sp-note">' + _t('sp.room_note', '20~300Hz 룸모드 · CamillaDSP PEQ 자동 생성 · 원음 파일은 변경하지 않습니다.') + '</p>'
    );
  };

  RemoteSpatialWizard.prototype.renderPoints = function () {
    var sweepHint =
      _t('sp.sweep_hint', '마이크 허용 후, 청취 위치에서 「측정 시작」을 반복하세요. 스윕은 서버 스피커에서 재생됩니다.');
    var html =
      this.renderPosCallout() +
      '<div class="sp-progress">' +
      '<div class="sp-progress__bar"><span style="width:' +
      Math.round((this.l1PointIndex / this.l1PointTotal) * 100) +
      '%"></span></div>' +
      '</div>';

    if (!this.micReady) {
      html +=
        '<p class="sp-hint">' + sweepHint + '</p>' +
        '<button type="button" class="sp-btn sp-btn--primary" data-sp-action="mic-prepare"' +
        (this.busy ? ' disabled' : '') +
        '>' + _t('sp.mic_prepare', '마이크 준비 (허용)') + '</button>';
    } else {
      html +=
        '<p class="sp-hint sp-hint--ok">' + _t('sp.mic_ready', '마이크 준비 완료 · 「측정 시작」만 누르세요.') + '</p>' +
        '<button type="button" class="sp-btn sp-btn--primary" data-sp-action="measure"' +
        (this.busy ? ' disabled' : '') +
        '>' +
        (this.busy ? _t('sp.measuring', '측정 중…') : _t('sp.measure_start', '측정 시작')) +
        '</button> ' +
        '<button type="button" class="sp-btn sp-btn--ghost sp-btn--sm" data-sp-action="reset">' +
        _t('sp.reset_progress', '초기화') +
        '</button> ' +
        '<button type="button" class="sp-btn sp-btn--ghost sp-btn--sm" data-sp-action="mic-prepare">' + _t('sp.mic_again', '마이크 다시') + '</button>';
    }
    return html;
  };

  RemoteSpatialWizard.prototype.renderResult = function () {
    var rows = '';
    (this.result.peaking || []).forEach(function (b) {
      rows +=
        '<tr><td>' +
        b.freq +
        '</td><td>' +
        b.gainDb +
        ' dB</td><td>Q ' +
        b.q +
        '</td></tr>';
    });
    return (
      '<div class="sp-result">' +
      '<h3 class="sp-result__t">' + _t('sp.measure_done', '측정 완료') + '</h3>' +
      '<p class="sp-hint">' +
      esc(this.result.note || '') +
      '</p>' +
      '<table class="sp-table"><thead><tr><th>Hz</th><th>Gain</th><th>Q</th></tr></thead><tbody>' +
      rows +
      '</tbody></table>' +
      '<button type="button" class="sp-btn sp-btn--primary" data-sp-action="apply"' +
      (this.busy ? ' disabled' : '') +
      '>' + _t('sp.apply_peq', 'PEQ 적용 · 재생 경로 반영') + '</button> ' +
      '<button type="button" class="sp-btn sp-btn--ghost" data-sp-action="reset">' + _t('sp.remeasure', '다시 측정') + '</button></div>'
    );
  };

  RemoteSpatialWizard.prototype.render = function () {
    if (!this.root && !this._speakersRoot) return;
    var body = '';
    if (this.phase === 'hub') body = this.renderHub();
    else if (this.phase === 'points' || this.phase === 'mic-denied') body = this.renderPoints();
    else if (this.phase === 'measure')
      body =
        '<div class="sp-measure"><div class="sp-measure__pulse"></div><p class="sp-measure__status">' + _t('sp.sweep_recording', 'Playing log sweep · recording with mic…') + '</p>' +
        this.renderPosCallout() +
        '<p class="sp-hint">' +
        _t('sp.measure_wait', '스윕이 끝날 때까지 기다려 주세요. 초기화는 측정 사이에 가능합니다.') +
        '</p></div>';
    else if (this.phase === 'result') body = this.renderResult();
    else if (this.phase === 'applied')
      body =
        '<div class="sp-done">' +
        '<div class="sp-done__ic">✅</div>' +
        '<h3>' + _t('sp.room_applied', 'Room correction applied') + '</h3>' +
        '<p class="sp-hint">' + _t('sp.room_applied_msg', 'CamillaDSP yaml saved. PEQ applies to local playback.') + '</p>' +
        '<button type="button" class="sp-btn sp-btn--ghost" data-sp-action="reset">' +
        _t('sp.measure_new', '새로 측정') +
        '</button></div>';
    else if (this.phase === 'speakers') body = this.renderHub();

    if (this.phase === 'mic-denied') {
      body =
        '<div class="sp-alert">' + _t('sp.mic_blocked', 'Microphone is blocked. Allow this site\'s microphone in browser settings and try again.') + '</div>' +
        body;
    }

    var errBlock = this.error ? '<div class="sp-alert" role="alert">' + esc(this.error) + '</div>' : '';

    if (this._speakersRoot) {
      this._speakersRoot.innerHTML =
        '<div class="sp-wizard sp-wizard--dsp">' + errBlock + this.renderSpeakers() + '</div>';
    }

    var html = '<div class="sp-wizard">' + errBlock + body + '</div>';
    (this._roots || []).forEach(function (r) {
      if (r) r.innerHTML = html;
    });
  };

  RemoteSpatialWizard.prototype.destroy = function () {
    if (this.api && this._onSpatial) this.api.off('spatial', this._onSpatial);
    this.stopMic();
  };

  g.WhickRemoteSpatialWizard = RemoteSpatialWizard;

  g.initWhickSpatialWizard = function (api, rootId) {
    var el = document.getElementById(rootId || 'spatial-root');
    if (!el || !api) return null;
    if (el._spatialWizard) return el._spatialWizard;
    if (g._sharedSpatialWizard) {
      g._sharedSpatialWizard.addRoot(el);
      el._spatialWizard = g._sharedSpatialWizard;
      return g._sharedSpatialWizard;
    }
    var w = new RemoteSpatialWizard(api, el);
    if (!w.root && !w._speakersRoot) return null;
    g._sharedSpatialWizard = w;
    el._spatialWizard = w;
    return w;
  };
})(typeof window !== 'undefined' ? window : globalThis);
