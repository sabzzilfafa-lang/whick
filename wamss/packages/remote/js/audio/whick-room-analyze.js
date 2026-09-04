(function (g) {
  'use strict';

  var ROOM_MODE_BANDS = [20, 40, 63, 80, 100, 125, 200, 250, 300];
  var LEGACY_BANDS = [63, 125, 250, 500];

  var DEVICE_PROFILES = {
    generic: { id: 'generic', label: _t('au.generic_phone', '일반 스마트폰 (자동)'), bandCorrectionDb: {} },
    'iphone-15': {
      id: 'iphone-15',
      label: _t('au.iphone15', 'iPhone 15 계열'),
      bandCorrectionDb: { 63: 1.2, 125: 0.8, 200: -0.5, 250: -1 },
    },
    'iphone-16': {
      id: 'iphone-16',
      label: _t('au.iphone16', 'iPhone 16 계열'),
      bandCorrectionDb: { 63: 1, 125: 0.6, 200: -0.4, 250: -0.8 },
    },
    'galaxy-s24': {
      id: 'galaxy-s24',
      label: _t('au.galaxy24', 'Galaxy S24 계열'),
      bandCorrectionDb: { 40: -1.5, 63: -0.8, 125: 0.5, 200: 1 },
    },
    'galaxy-s25': {
      id: 'galaxy-s25',
      label: _t('au.galaxy25', 'Galaxy S25 계열'),
      bandCorrectionDb: { 40: -1.2, 63: -0.6, 125: 0.4, 200: 0.8 },
    },
  };

  var SMARTPHONE_POSITIONS = [
    { n: 1, label: _t('sp.pos1', '① 코 바로앞') },
    { n: 2, label: _t('sp.pos2', '② 왼쪽 30cm') },
    { n: 3, label: _t('sp.pos3', '③ 오른쪽 30cm') },
    { n: 4, label: _t('sp.pos4', '④ 앞쪽 50cm') },
    { n: 5, label: _t('sp.pos5', '⑤ 뒤쪽 50cm') },
  ];

  function detectDeviceProfile() {
    var ua = navigator.userAgent || '';
    if (/iPhone/i.test(ua)) {
      if (/OS 18|iPhone16/i.test(ua)) return DEVICE_PROFILES['iphone-16'];
      return DEVICE_PROFILES['iphone-15'];
    }
    if (/Galaxy S25|SM-S92/i.test(ua)) return DEVICE_PROFILES['galaxy-s25'];
    if (/Galaxy S24|SM-S928/i.test(ua)) return DEVICE_PROFILES['galaxy-s24'];
    return DEVICE_PROFILES.generic;
  }

  function applyDeviceProfileToBands(bandLevelsDb, profileId) {
    var profile = DEVICE_PROFILES[profileId] || DEVICE_PROFILES.generic;
    return bandLevelsDb.map(function (b) {
      return {
        freq: b.freq,
        db: b.db - (profile.bandCorrectionDb[b.freq] || 0),
      };
    });
  }

  function bandEnergy(samples, sampleRate, centerHz) {
    var windowSize = 2048;
    var hop = 1024;
    var sum = 0;
    var count = 0;
    var omega = (2 * Math.PI * centerHz) / sampleRate;
    for (var i = 0; i + windowSize < samples.length; i += hop) {
      var re = 0;
      var im = 0;
      for (var j = 0; j < windowSize; j++) {
        var w = 0.5 * (1 - Math.cos((2 * Math.PI * j) / (windowSize - 1)));
        var s = samples[i + j] * w;
        re += s * Math.cos(omega * j);
        im += s * Math.sin(omega * j);
      }
      sum += re * re + im * im;
      count++;
    }
    return count > 0 ? sum / count : 0;
  }

  function peakingFromBandLevels(bandLevelsDb, level, roomOnly) {
    var focus = roomOnly
      ? bandLevelsDb.filter(function (b) {
          return b.freq >= 20 && b.freq <= 300;
        })
      : bandLevelsDb;
    var ref =
      focus.reduce(function (s, b) {
        return s + b.db;
      }, 0) / (focus.length || 1);
    var peaking = [];
    var threshold = roomOnly ? 2 : 2.5;
    focus.forEach(function (b) {
      var excess = b.db - ref;
      if (excess > threshold) {
        peaking.push({
          freq: b.freq,
          q: b.freq < 100 ? 1.2 : b.freq < 200 ? 1.4 : 1.5,
          gainDb: Math.max(-8, Math.min(-1, -Math.round(excess * 0.55 * 10) / 10)),
        });
      }
    });
    if (!peaking.length) {
      peaking.push({ freq: roomOnly ? 80 : 125, q: 1.2, gainDb: -1.5 });
    }
    return peaking.slice(0, roomOnly ? 6 : 8);
  }

  function analyzeRoomRecording(samples, sampleRate, level, opts) {
    opts = opts || {};
    var roomOnly = opts.roomModeOnly !== false && level === 'smartphone';
    var bands = roomOnly ? ROOM_MODE_BANDS : LEGACY_BANDS;
    var bandLevelsDb = bands.map(function (freq) {
      var energy = bandEnergy(samples, sampleRate, freq);
      return { freq: freq, db: 10 * Math.log10(energy + 1e-12) };
    });
    if (level === 'smartphone' && opts.deviceProfileId) {
      bandLevelsDb = applyDeviceProfileToBands(bandLevelsDb, opts.deviceProfileId);
    }
    var peaking = peakingFromBandLevels(bandLevelsDb, level, roomOnly);
    return {
      level: level,
      peaking: peaking,
      bandLevelsDb: bandLevelsDb,
      note:
        level === 'smartphone'
          ? _t('au.phone_mic_desc', '스마트폰 마이크 · 20~300Hz 룸모드 PEQ')
          : _t('au.umik', 'UMIK 측정'),
    };
  }

  function averageRoomMeasurements(runs, opts) {
    if (!runs.length) throw new Error(_t('au.no_data', '측정 데이터가 없습니다.'));
    var freqSet = {};
    runs.forEach(function (r) {
      r.bandLevelsDb.forEach(function (b) {
        freqSet[b.freq] = true;
      });
    });
    var freqs = Object.keys(freqSet)
      .map(Number)
      .sort(function (a, b) {
        return a - b;
      });
    var bandLevelsDb = freqs.map(function (freq) {
      var vals = runs
        .map(function (r) {
          var hit = r.bandLevelsDb.find(function (b) {
            return b.freq === freq;
          });
          return hit ? hit.db : undefined;
        })
        .filter(function (v) {
          return v !== undefined;
        });
      var avg =
        vals.reduce(function (s, v) {
          return s + v;
        }, 0) / (vals.length || 1);
      return { freq: freq, db: Math.round(avg * 10) / 10 };
    });
    return {
      level: 'smartphone',
      peaking: peakingFromBandLevels(bandLevelsDb, 'smartphone', true),
      bandLevelsDb: bandLevelsDb,
      note: _t('au.phone_note_prefix', 'Phone ') + opts.pointCount + _t('au.phone_note_suffix', '-point average · 20-300Hz room-mode PEQ'),
    };
  }

  g.WhickRoomAnalyze = {
    analyze: analyzeRoomRecording,
    average: averageRoomMeasurements,
    detectDevice: detectDeviceProfile,
    profiles: DEVICE_PROFILES,
    positions: SMARTPHONE_POSITIONS,
    STORAGE_KEY: 'whick-room-spatial-peq-v1',
  };
})(typeof window !== 'undefined' ? window : globalThis);
