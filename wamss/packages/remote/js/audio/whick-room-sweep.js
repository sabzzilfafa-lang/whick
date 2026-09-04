/* OWNER SSOT: sales — do not sync across remote UIs */
(function (g) {
  'use strict';

  var F_MIN = 40;
  var F_MAX = 500;
  var DURATION_SEC = 8;
  var SWEEP_GAIN = 0.42;
  var gPlaybackCtx = null;
  var gPlaybackPrimed = false;

  function playUnlockChime(ctx) {
    if (gPlaybackPrimed || !ctx) return;
    try {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      gain.gain.value = 0.0001;
      osc.frequency.value = 440;
      osc.connect(gain);
      gain.connect(ctx.destination);
      var t = ctx.currentTime;
      osc.start(t);
      osc.stop(t + 0.02);
      gPlaybackPrimed = true;
    } catch (e) {}
  }

  function waitCtxRunning(ctx) {
    if (!ctx || ctx.state === 'running') return Promise.resolve();
    if (ctx.state === 'closed') {
      return Promise.reject(new Error(_t('au.ctx_closed', '오디오 컨텍스트가 닫혔습니다.')));
    }
    return new Promise(function (resolve, reject) {
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        ctx.removeEventListener('statechange', onChange);
        if (ctx.state === 'running') resolve();
        else reject(new Error(_t('au.play_start_failed2', 'Cannot start audio playback. Tap the page and try again.')));
      }
      function onChange() {
        if (ctx.state === 'running') finish();
      }
      ctx.addEventListener('statechange', onChange);
      var p = ctx.resume ? ctx.resume() : Promise.resolve();
      p.then(function () {
        if (ctx.state === 'running') finish();
      }).catch(reject);
      setTimeout(function () {
        if (!done && ctx.state === 'running') finish();
      }, 400);
    });
  }

  function ensurePlaybackCtx() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) {
      return Promise.reject(new Error(_t('au.no_webaudio', 'Web Audio를 사용할 수 없습니다.')));
    }
    if (!gPlaybackCtx || gPlaybackCtx.state === 'closed') {
      gPlaybackPrimed = false;
      try {
        gPlaybackCtx = new Ctx({ latencyHint: 'playback' });
      } catch (e) {
        gPlaybackCtx = new Ctx();
      }
    }
    return waitCtxRunning(gPlaybackCtx).then(function () {
      playUnlockChime(gPlaybackCtx);
      return gPlaybackCtx;
    });
  }

  function logSweepFrequency(t, duration) {
    var u = Math.min(1, Math.max(0, t / duration));
    var r = F_MAX / F_MIN;
    return F_MIN * Math.pow(r, u);
  }

  function isHandheld() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
      navigator.userAgent
    );
  }

  function micConstraints() {
    return {
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    };
  }

  function recordFromStream(stream, opts) {
    opts = opts || {};
    var recordCtx = new (window.AudioContext || window.webkitAudioContext)();
    var resume =
      recordCtx.state === 'suspended' ? recordCtx.resume() : Promise.resolve();
    return resume.then(function () {
      if (typeof opts.onRecordingStart === 'function') {
        opts.onRecordingStart();
      }
      var sampleRate = recordCtx.sampleRate;
      var chunks = [];
      var micSource = recordCtx.createMediaStreamSource(stream);
      var processor = recordCtx.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = function (e) {
        var input = e.inputBuffer.getChannelData(0);
        chunks.push(new Float32Array(input));
      };
      micSource.connect(processor);
      var silent = recordCtx.createGain();
      silent.gain.value = 0;
      processor.connect(silent);
      silent.connect(recordCtx.destination);

      return new Promise(function (resolve) {
        setTimeout(function () {
          processor.disconnect();
          micSource.disconnect();
          if (!opts.keepStream) {
            stream.getTracks().forEach(function (tr) {
              tr.stop();
            });
          }
          recordCtx.close();

          var total = chunks.reduce(function (s, c) {
            return s + c.length;
          }, 0);
          var merged = new Float32Array(total);
          var off = 0;
          chunks.forEach(function (c) {
            merged.set(c, off);
            off += c.length;
          });
          resolve({ samples: merged, sampleRate: sampleRate });
        }, (DURATION_SEC + 0.4) * 1000);
      });
    });
  }

  function micStreamFromOpts(opts) {
    opts = opts || {};
    var stream = opts.mediaStream;
    if (stream && stream.getAudioTracks && stream.getAudioTracks().length) {
      var live = stream.getAudioTracks().some(function (tr) {
        return tr.readyState === 'live';
      });
      if (live) return Promise.resolve(stream);
    }
    return navigator.mediaDevices.getUserMedia(micConstraints());
  }

  /** 스마트폰: 마이크만(스윕은 청취 스피커·PC). PC: 스윕 재생 + 마이크 녹음 */
  function runMicOnlyMeasurement(opts) {
    return micStreamFromOpts(opts).then(function (stream) {
      return recordFromStream(stream, opts);
    });
  }

  function runFullSweepMeasurement(opts) {
    opts = opts || {};
    return ensurePlaybackCtx()
      .then(function () {
        return micStreamFromOpts(opts);
      })
      .then(function (stream) {
        var playbackCtx = gPlaybackCtx;
        var recordCtx = new (window.AudioContext || window.webkitAudioContext)();
        return waitCtxRunning(recordCtx).then(function () {
          if (typeof opts.onRecordingStart === 'function') {
            opts.onRecordingStart();
          }
          var sampleRate = recordCtx.sampleRate;
          var chunks = [];
          var micSource = recordCtx.createMediaStreamSource(stream);
          var processor = recordCtx.createScriptProcessor(4096, 1, 1);
          processor.onaudioprocess = function (e) {
            var input = e.inputBuffer.getChannelData(0);
            chunks.push(new Float32Array(input));
          };
          micSource.connect(processor);
          var silent = recordCtx.createGain();
          silent.gain.value = 0;
          processor.connect(silent);
          silent.connect(recordCtx.destination);

          var osc = playbackCtx.createOscillator();
          var gain = playbackCtx.createGain();
          gain.gain.value = SWEEP_GAIN;
          osc.type = 'sine';
          osc.connect(gain);
          gain.connect(playbackCtx.destination);

          var t0 = playbackCtx.currentTime + 0.08;
          osc.frequency.setValueAtTime(F_MIN, t0);
          var steps = 80;
          for (var i = 1; i <= steps; i++) {
            var t = (i / steps) * DURATION_SEC;
            osc.frequency.setValueAtTime(logSweepFrequency(t, DURATION_SEC), t0 + t);
          }
          osc.start(t0);
          osc.stop(t0 + DURATION_SEC + 0.05);

          return new Promise(function (resolve) {
            setTimeout(function () {
              processor.disconnect();
              micSource.disconnect();
              gain.disconnect();
              osc.disconnect();
              if (!opts.keepStream) {
                stream.getTracks().forEach(function (tr) {
                  tr.stop();
                });
              }
              recordCtx.close();

              var total = chunks.reduce(function (s, c) {
                return s + c.length;
              }, 0);
              var merged = new Float32Array(total);
              var off = 0;
              chunks.forEach(function (c) {
                merged.set(c, off);
                off += c.length;
              });
              resolve({ samples: merged, sampleRate: sampleRate });
            }, (DURATION_SEC + 0.4) * 1000);
          });
        });
      });
  }

  function delayUntil(sweepAtMs) {
    var delay = Math.max(0, sweepAtMs - Date.now());
    return new Promise(function (resolve) {
      setTimeout(resolve, delay);
    });
  }

  /** PC: 스윕만 재생(마이크는 스마트폰) */
  function runSpeakerOnlyMeasurement(opts) {
    opts = opts || {};
    return ensurePlaybackCtx().then(function () {
      var playbackCtx = gPlaybackCtx;
      if (typeof opts.onRecordingStart === 'function') {
        opts.onRecordingStart();
      }
      var osc = playbackCtx.createOscillator();
      var gain = playbackCtx.createGain();
      gain.gain.value = SWEEP_GAIN;
      osc.type = 'sine';
      osc.connect(gain);
      gain.connect(playbackCtx.destination);

      var t0 = playbackCtx.currentTime + 0.08;
      osc.frequency.setValueAtTime(F_MIN, t0);
      var steps = 80;
      for (var i = 1; i <= steps; i++) {
        var t = (i / steps) * DURATION_SEC;
        osc.frequency.setValueAtTime(logSweepFrequency(t, DURATION_SEC), t0 + t);
      }
      osc.start(t0);
      osc.stop(t0 + DURATION_SEC + 0.05);

      return new Promise(function (resolve) {
        setTimeout(function () {
          gain.disconnect();
          osc.disconnect();
          resolve({ samples: new Float32Array(0), sampleRate: playbackCtx.sampleRate || 48000 });
        }, (DURATION_SEC + 0.4) * 1000);
      });
    });
  }

  function runSpeakerOnlyAt(sweepAtMs, opts) {
    return ensurePlaybackCtx().then(function () {
      return delayUntil(sweepAtMs).then(function () {
        return ensurePlaybackCtx().then(function () {
          return runSpeakerOnlyMeasurement(opts);
        });
      });
    });
  }

  function runMicOnlyAt(sweepAtMs, opts) {
    return micStreamFromOpts(opts).then(function (stream) {
      return delayUntil(sweepAtMs).then(function () {
        return recordFromStream(stream, opts);
      });
    });
  }

  function runFullSweepAt(sweepAtMs, opts) {
    return ensurePlaybackCtx().then(function () {
      return delayUntil(sweepAtMs).then(function () {
        return ensurePlaybackCtx().then(function () {
          return runFullSweepMeasurement(opts);
        });
      });
    });
  }

  function runSweepMeasurement(opts) {
    if (opts && opts.syncRole === 'speaker') {
      return opts.sweepAtMs
        ? runSpeakerOnlyAt(opts.sweepAtMs, opts)
        : runSpeakerOnlyMeasurement(opts);
    }
    if (opts && opts.syncRole === 'mic') {
      return opts.sweepAtMs
        ? runMicOnlyAt(opts.sweepAtMs, opts)
        : runMicOnlyMeasurement(opts);
    }
    if (opts && opts.playOnDevice) {
      return opts.sweepAtMs
        ? runFullSweepAt(opts.sweepAtMs, opts)
        : runFullSweepMeasurement(opts);
    }
    if (isHandheld()) {
      return runMicOnlyMeasurement(opts);
    }
    return runFullSweepMeasurement(opts);
  }

  g.WhickRoomSweep = {
    run: runSweepMeasurement,
    runSpeakerOnly: runSpeakerOnlyMeasurement,
    playSweepNow: runSpeakerOnlyMeasurement,
    runMicOnly: runMicOnlyMeasurement,
    runSpeakerOnlyAt: runSpeakerOnlyAt,
    runMicOnlyAt: runMicOnlyAt,
    unlockPlayback: ensurePlaybackCtx,
    isHandheld: isHandheld,
    isMicOnlyMode: isHandheld,
    durationSec: function () {
      return DURATION_SEC;
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
