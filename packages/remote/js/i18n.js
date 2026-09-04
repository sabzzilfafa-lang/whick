/* Whick product remote chrome i18n — local SSOT only */
(function (global) {
  var cfg = global.WHICK_I18N_CFG || {};
  var STORAGE = cfg.storageKey || 'whick_remote_lang';
  var BASE = cfg.base || 'i18n';
  var SUPPORTED = cfg.supported || ['en', 'ko'];
  var DEFAULT_LANG = cfg.defaultLang || 'en';
  var catalog = {};
  var current = DEFAULT_LANG;
  var readyPromise = null;

  function getPath(obj, path) {
    return path.split('.').reduce(function (o, k) {
      return o && o[k] != null ? o[k] : undefined;
    }, obj);
  }

  function t(key) {
    var v = getPath(catalog, key);
    return typeof v === 'string' ? v : key;
  }

  function detect() {
    try {
      var q = new URLSearchParams(location.search).get('lang');
      if (q && SUPPORTED.indexOf(q) >= 0) return q;
    } catch (e) {}
    try {
      var s = localStorage.getItem(STORAGE);
      if (s && SUPPORTED.indexOf(s) >= 0) return s;
    } catch (e2) {}
    var nav = (navigator.languages && navigator.languages[0]) || navigator.language || DEFAULT_LANG;
    var base = String(nav).toLowerCase().slice(0, 2);
    if (SUPPORTED.indexOf(base) >= 0) return base;
    return DEFAULT_LANG;
  }

  function load(lang) {
    return fetch(BASE.replace(/\/$/, '') + '/' + lang + '.json', { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('i18n ' + lang + ' ' + r.status);
        return r.json();
      });
  }

  function applyDom() {
    document.documentElement.lang = current;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (!key) return;
      el.textContent = t(key);
    });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-html');
      if (!key) return;
      el.innerHTML = t(key);
    });
    document.querySelectorAll('[data-i18n-ph]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-ph');
      if (!key) return;
      el.setAttribute('placeholder', t(key));
    });
    document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-title');
      if (!key) return;
      el.setAttribute('title', t(key));
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-aria');
      if (!key) return;
      el.setAttribute('aria-label', t(key));
    });
    var sel = document.getElementById('lang-btn');
    if (sel) sel.textContent = current === 'en' ? 'KO' : 'EN';
    var titleEl = document.getElementById('pg-title');
    if (titleEl && titleEl.getAttribute('data-i18n-title')) {
      titleEl.textContent = t(titleEl.getAttribute('data-i18n-title'));
    }
    syncLangSelect();
  }

  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) < 0) lang = DEFAULT_LANG;
    current = lang;
    try { localStorage.setItem(STORAGE, lang); } catch (e) {}
    return load(lang).then(function (cat) {
      catalog = cat;
      applyDom();
      try {
        if (typeof global.whickOnLangChange === 'function') global.whickOnLangChange(lang);
      } catch (e2) {}
      return lang;
    });
  }

  function toggleLang() {
    return setLang(current === 'en' ? 'ko' : 'en');
  }

  function getLang() { return current; }

  // ── 언어 선택 드롭다운 (14개 언어) ──
  var LANG_LABELS = {
    en: 'English', ko: '한국어', ja: '日本語', zh: '中文',
    fr: 'Français', de: 'Deutsch', es: 'Español', it: 'Italiano',
    pt: 'Português', ru: 'Русский', hi: 'हिन्दी', id: 'Bahasa Indonesia',
    vi: 'Tiếng Việt', th: 'ไทย'
  };

  function syncLangSelect() {
    var sel = document.getElementById('lang-select');
    if (!sel) return;
    if (!sel.dataset.built) {
      SUPPORTED.forEach(function (code) {
        var opt = document.createElement('option');
        opt.value = code;
        opt.textContent = LANG_LABELS[code] || code;
        sel.appendChild(opt);
      });
      sel.addEventListener('change', function () {
        if (sel.value) setLang(sel.value);
      });
      sel.dataset.built = '1';
    }
    sel.value = current;
  }

  function initI18n() {
    readyPromise = setLang(detect()).then(function () {
      syncLangSelect();
    }).catch(function (err) {
      console.warn('[i18n]', err);
      catalog = {};
      syncLangSelect();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initI18n);
  } else {
    initI18n();
  }

  global.WhickI18n = {
    t: t,
    setLang: setLang,
    toggleLang: toggleLang,
    getLang: getLang,
    syncLangSelect: syncLangSelect,
    apply: applyDom,
    ready: readyPromise,
    get lang() { return current; }
  };
})(window);
