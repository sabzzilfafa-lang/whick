/* Whick Remote Portal i18n — local SSOT only (no shared file with remote/trial/demo) */
(function (global) {
  var cfg = global.WHICK_PORTAL_I18N_CFG || {};
  var STORAGE = cfg.storageKey || 'whick_sales_remote_lang';
  var BASE = cfg.base || 'i18n';
  var SUPPORTED = cfg.supported || ['en', 'ko'];
  var DEFAULT_LANG = cfg.defaultLang || 'en';
  var catalog = {};
  var current = DEFAULT_LANG;
  var readyPromise = null;
  var listeners = [];

  function getPath(obj, path) {
    return path.split('.').reduce(function (o, k) {
      return o && o[k] != null ? o[k] : undefined;
    }, obj);
  }

  function t(key, vars) {
    var v = getPath(catalog, key);
    var s = typeof v === 'string' ? v : key;
    if (vars && typeof vars === 'object') {
      Object.keys(vars).forEach(function (k) {
        s = s.split('{' + k + '}').join(String(vars[k]));
      });
    }
    return s;
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
    var lb = document.getElementById('lang-toggle');
    if (lb) lb.textContent = current === 'en' ? 'KO' : 'EN';
  }

  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) < 0) lang = DEFAULT_LANG;
    current = lang;
    try { localStorage.setItem(STORAGE, lang); } catch (e) {}
    return load(lang).then(function (cat) {
      catalog = cat;
      applyDom();
      syncLangSelect();
      listeners.forEach(function (fn) {
        try { fn(lang); } catch (e) {}
      });
      return lang;
    }).catch(function (err) {
      console.warn('[portal-i18n]', err);
      // keep existing catalog + HTML defaults; do not overwrite with raw keys
      syncLangSelect();
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

  function onLangChange(fn) {
    if (typeof fn === 'function') listeners.push(fn);
  }

  function initI18n() {
    readyPromise = setLang(detect()).then(function () {
      syncLangSelect();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initI18n);
  } else {
    initI18n();
  }

  global.WhickPortalI18n = {
    t: t,
    setLang: setLang,
    toggleLang: toggleLang,
    getLang: getLang,
    syncLangSelect: syncLangSelect,
    onLangChange: onLangChange,
    apply: applyDom,
    ready: readyPromise,
    get lang() { return current; }
  };
})(window);
