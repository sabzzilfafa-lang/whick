/**
 * 파일 탐색기 — 내장(music) · 외장(/media)
 * 상단: 전체선택 · 전체선택해제 + (선택 시) 검수·추가 / 바로추가
 * 길게 누르기: 새폴더·이름변경·삭제·복사·이동·붙여넣기·라이브러리추가
 */
(function () {
  const LONG_MS = 480;

  function fmtBytes(n) {
    const v = Number(n) || 0;
    if (v < 1024) return v + ' B';
    if (v < 1048576) return (v / 1024).toFixed(1) + ' KB';
    if (v < 1073741824) return (v / 1048576).toFixed(1) + ' MB';
    return (v / 1073741824).toFixed(2) + ' GB';
  }

  function rootLabel(root) {
    return root === 'music' ? _t('fs.my_music', '내폴더') : _t('fs.external', '외장');
  }

  function uiRel(root, path) {
    let p = String(path || '').trim();
    if (root === 'music') {
      if (p === 'music' || p === '') return '';
      if (p.startsWith('music/')) return p.slice(6);
      return p.replace(/^\/+/, '');
    }
    if (p === '/media' || p === 'media' || p === '') return '';
    if (p.startsWith('/media/')) return p.slice(7);
    if (p.startsWith('media/')) return p.slice(6);
    return p.replace(/^\/+/, '');
  }

  class LibraryFsExplorer {
    constructor(api) {
      this.api = api;
      this.root = 'media';
      this.path = '';
      this.entries = [];
      this.selected = new Set();
      this.clipboard = null;
      this.mode = 'browse';
      this._bound = false;
      this._pressTimer = null;
      this._pressMoved = false;
      this._suppressClick = false;
      this._systemHidden = new Set(['system volume information', '$recycle.bin', 'lost+found', 'imported', 'tones']);
    }

    open(opts = {}) {
      this.root = opts.root === 'music' ? 'music' : 'media';
      this.path = uiRel(this.root, opts.path || '');
      this.mode = opts.mode || 'browse';
      this.selected.clear();
      this._ensureDom();
      this._bind();
      document.getElementById('fs-explorer-overlay')?.classList.add('open');
      this.refresh();
    }

    close() {
      this._hideCtx();
      document.getElementById('fs-explorer-overlay')?.classList.remove('open');
    }

    _ensureDom() {
      if (document.getElementById('fs-explorer-overlay')) {
        this._ensureLongpressHint();
        return;
      }
      const el = document.createElement('div');
      el.id = 'fs-explorer-overlay';
      el.className = 'fs-ov';
      el.innerHTML = `
        <div class="fs-card" role="dialog" aria-modal="true" aria-label=_t('fs.title', '파일 탐색기')>
          <div class="fs-top">
            <div class="fs-roots">
              <button type="button" class="fs-root-btn" data-root="media">' + _t('fs.external', 'External') + '</button>
              <button type="button" class="fs-root-btn" data-root="music">' + _t('fs.my_music', 'My Music') + '</button>
              <span class="fs-longpress-hint" aria-hidden="true">' + _t('fs.hint_longpress', 'Menu button or long-press') + '</span>
            </div>
            <button type="button" class="fs-close" id="fs-close" aria-label=_t('fs.close', '닫기')>×</button>
          </div>
          <div class="fs-path-row">
            <button type="button" class="fs-up-mini" id="fs-up" title=_t('fs.up', '상위')>↑</button>
            <div class="fs-path" id="fs-path"></div>
            <button type="button" class="fs-menu-btn" id="fs-menu-btn" title=_t('fs.menu', '메뉴')>☰ 메뉴</button>
          </div>
          <div class="fs-selbar">
            <button type="button" class="fs-sel-mini" id="fs-sel-all">' + _t('fs.select_all', 'Select all') + '</button>
            <button type="button" class="fs-sel-mini" id="fs-sel-none">' + _t('fs.deselect_all', 'Deselect all') + '</button>
            <span class="fs-sel-count" id="fs-sel-count" hidden>0</span>
            <button type="button" class="fs-act-btn primary" id="fs-act-audit" hidden>' + _t('fs.add_with_audit', 'Review & add') + '</button>
            <button type="button" class="fs-act-btn" id="fs-act-register" hidden>' + _t('fs.add_now', 'Add now') + '</button>
          </div>
          <div class="fs-list" id="fs-list"></div>
          <div class="fs-status" id="fs-status"></div>
        </div>
        <div id="fs-ctx" class="fs-ctx" hidden>
          <button type="button" data-act="mkdir">' + _t('fs.mkdir', 'New folder') + '</button>
          <button type="button" data-act="rename">' + _t('fs.rename', 'Rename') + '</button>
          <button type="button" data-act="delete">' + _t('fs.delete', 'Delete') + '</button>
          <button type="button" data-act="copy">' + _t('fs.copy', 'Copy') + '</button>
          <button type="button" data-act="cut">' + _t('fs.move', 'Move') + '</button>
          <button type="button" data-act="paste">' + _t('fs.paste', 'Paste') + '</button>
          <button type="button" data-act="audit-register">' + _t('fs.add_with_audit', 'Review & add') + '</button>
          <button type="button" data-act="register">' + _t('fs.add_no_audit', 'Add now (skip review)') + '</button>
          <button type="button" class="fs-ctx-cancel" data-act="cancel">' + _t('common.cancel', 'Cancel') + '</button>
        </div>
        <div id="fs-ctx-scrim" class="fs-ctx-scrim" hidden></div>`;
      document.body.appendChild(el);
      const menuBtn = el.querySelector('#fs-menu-btn');
      if (menuBtn) {
        menuBtn.addEventListener('click', () => {
          // 길게누름이 어려운 환경(일부 폰 웹뷰)을 위한 우회 — 화면 중앙에 컨텍스트 메뉴
          this._showCtx(window.innerWidth / 2, window.innerHeight / 3);
        });
      }
    }

    _ensureLongpressHint() {
      const roots = document.querySelector('#fs-explorer-overlay .fs-roots');
      if (!roots || roots.querySelector('.fs-longpress-hint')) return;
      const hint = document.createElement('span');
      hint.className = 'fs-longpress-hint';
      hint.setAttribute('aria-hidden', 'true');
      hint.textContent = _t('fs.hint_longpress', '메뉴 버튼 또는 길게 누름');
      roots.appendChild(hint);
    }

    _bind() {
      if (this._bound) return;
      this._bound = true;
      document.getElementById('fs-close')?.addEventListener('click', () => this.close());
      document.getElementById('fs-up')?.addEventListener('click', () => this.goUp());
      document.getElementById('fs-sel-all')?.addEventListener('click', () => this.selectAll());
      document.getElementById('fs-sel-none')?.addEventListener('click', () => this.selectNone());
      document.getElementById('fs-act-audit')?.addEventListener('click', () => this.registerSelected({ audit: true }));
      document.getElementById('fs-act-register')?.addEventListener('click', () => this.registerSelected({ audit: false }));
      document.querySelectorAll('.fs-root-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          this.root = btn.getAttribute('data-root') === 'music' ? 'music' : 'media';
          this.path = '';
          this.selected.clear();
          this.refresh();
        });
      });
      document.getElementById('fs-ctx-scrim')?.addEventListener('click', () => this._hideCtx());
      document.getElementById('fs-ctx')?.addEventListener('click', (ev) => {
        const btn = ev.target.closest('button[data-act]');
        if (!btn) return;
        const act = btn.getAttribute('data-act');
        this._hideCtx();
        if (act === 'cancel') return;
        this._runAct(act);
      });
    }

    _status(msg) {
      const el = document.getElementById('fs-status');
      if (el) el.textContent = msg || '';
    }

    selectAll() {
      this.entries.forEach((e) => {
        const rel = uiRel(this.root, e.path);
        this.selected.add(`${this.root}:${rel}`);
      });
      this._renderList();
    }

    selectNone() {
      this.selected.clear();
      this._renderList();
    }

    _syncSelActions() {
      const n = this.selected.size;
      const countEl = document.getElementById('fs-sel-count');
      const auditBtn = document.getElementById('fs-act-audit');
      const regBtn = document.getElementById('fs-act-register');
      if (countEl) {
        countEl.hidden = n < 1;
        countEl.textContent = `${n} ${_t('fs.selected_suffix', 'selected')}`;
      }
      if (auditBtn) auditBtn.hidden = n < 1;
      if (regBtn) regBtn.hidden = n < 1;
    }

    async refresh() {
      document.querySelectorAll('.fs-root-btn').forEach((b) => {
        b.classList.toggle('on', b.getAttribute('data-root') === this.root);
      });
      const pathEl = document.getElementById('fs-path');
      const label = rootLabel(this.root);
      if (pathEl) pathEl.textContent = this.path ? `${label} / ${this.path}` : label;
      const up = document.getElementById('fs-up');
      if (up) up.disabled = !this.path;

    try {
      const data = await this.api.fsBrowse(this.root, this.path);
      const raw = data.entries || [];
      this.entries = raw.filter((e) => {
        const n = String(e?.name || '').trim().toLowerCase();
        return n && !this._systemHidden.has(n) && !n.startsWith('.');
      });
      this._renderList();
        const free = data.free_bytes != null ? ` · ${fmtBytes(data.free_bytes)}${_t('fs.free_suffix', ' free')}` : '';
        const clip = this.clipboard
          ? ` · ${this.clipboard.mode === 'cut' ? _t('fs.move', _t('fs.move', 'Move')) : _t('fs.copy', _t('fs.copy', 'Copy'))}대기 ${this.clipboard.items.length}`
          : '';
        this._status(
          `${this.entries.length} ${_t('fs.items_suffix', 'items')}${free}${clip} · ${_t('fs.status_hint', 'Select, then Review & add or ☰ Menu')}`,
        );
        this._syncSelActions();
      } catch (e) {
        this._status(_t('fs.list_failed', '목록 실패: ') + (e.message || e));
      }
    }

    _clearPress() {
      if (this._pressTimer) {
        clearTimeout(this._pressTimer);
        this._pressTimer = null;
      }
    }

    _bindLongPress(row) {
      const start = (clientX, clientY) => {
        this._pressMoved = false;
        this._pressStart = { x: clientX, y: clientY };
        this._clearPress();
        this._pressTimer = setTimeout(() => {
          this._pressTimer = null;
          this._suppressClick = true;
          const key = row.getAttribute('data-key');
          if (key && !this.selected.has(key)) {
            // 길게 누른 행이 미선택이면 그 행만 선택
            this.selected.clear();
            this.selected.add(key);
            const chk = row.querySelector('.fs-chk');
            if (chk) chk.checked = true;
          }
          this._showCtx(clientX, clientY);
        }, LONG_MS);
      };
      const move = (ev) => {
        // 12px 이내 미세 이동은 유지 (모바일 터치 떨림 허용) — 초과 시에만 취소
        const t = ev.touches ? ev.touches[0] : null;
        if (!t || !this._pressStart) return;
        const dx = Math.abs(t.clientX - this._pressStart.x);
        const dy = Math.abs(t.clientY - this._pressStart.y);
        if (dx > 12 || dy > 12) {
          this._pressMoved = true;
          this._clearPress();
        }
      };
      const end = () => this._clearPress();

      row.addEventListener('touchstart', (ev) => {
        const t = ev.touches[0];
        if (t) start(t.clientX, t.clientY);
      }, { passive: true });
      row.addEventListener('touchmove', move, { passive: true });
      row.addEventListener('touchend', end);
      row.addEventListener('touchcancel', end);

      row.addEventListener('mousedown', (ev) => {
        if (ev.button !== 0) return;
        start(ev.clientX, ev.clientY);
      });
      row.addEventListener('mousemove', move);
      row.addEventListener('mouseup', end);
      row.addEventListener('mouseleave', end);

      row.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        const key = row.getAttribute('data-key');
        if (key && !this.selected.has(key)) {
          this.selected.clear();
          this.selected.add(key);
          const chk = row.querySelector('.fs-chk');
          if (chk) chk.checked = true;
        }
        this._showCtx(ev.clientX, ev.clientY);
      });
    }

    _showCtx(x, y) {
      const menu = document.getElementById('fs-ctx');
      const scrim = document.getElementById('fs-ctx-scrim');
      if (!menu || !scrim) return;
      menu.hidden = false;
      scrim.hidden = false;
      // 화면 안쪽으로
      const pad = 8;
      menu.style.left = '0px';
      menu.style.top = '0px';
      const mw = menu.offsetWidth;
      const mh = menu.offsetHeight;
      let left = (x || window.innerWidth / 2) - mw / 2;
      let top = (y || window.innerHeight / 2) - 20;
      left = Math.max(pad, Math.min(left, window.innerWidth - mw - pad));
      top = Math.max(pad, Math.min(top, window.innerHeight - mh - pad));
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
    }

    _hideCtx() {
      const menu = document.getElementById('fs-ctx');
      const scrim = document.getElementById('fs-ctx-scrim');
      if (menu) menu.hidden = true;
      if (scrim) scrim.hidden = true;
    }

    _runAct(act) {
      if (act === 'mkdir') return this.mkdir();
      if (act === 'rename') return this.rename();
      if (act === 'delete') return this.remove();
      if (act === 'copy') return this.setClipboard('copy');
      if (act === 'cut') return this.setClipboard('cut');
      if (act === 'paste') return this.paste();
      if (act === 'audit-register') return this.registerSelected({ audit: true });
      if (act === 'register') return this.registerSelected({ audit: false });
    }

    _renderList() {
      const list = document.getElementById('fs-list');
      if (!list) return;
      this._syncSelActions();
      if (!this.entries.length) {
        list.innerHTML = '<div class="fs-empty">' + _t('fs.empty_folder', 'Empty folder') + '<br><small>' + _t('fs.empty_hint', 'Long-press empty space for new folder/paste') + '</small></div>';
        list.onclick = null;
        this._bindEmptyLongPress(list);
        return;
      }
      list.innerHTML = this.entries
        .map((e) => {
          const rel = uiRel(this.root, e.path);
          const key = `${this.root}:${rel}`;
          const checked = this.selected.has(key) ? 'checked' : '';
          const icon = e.type === 'dir' ? '📁' : e.is_audio ? '🎵' : '📄';
          const size = e.type === 'dir' ? '' : fmtBytes(e.size_bytes);
          return `<div class="fs-row" data-key="${key}" data-rel="${rel}" data-type="${e.type}">
            <input type="checkbox" class="fs-chk" data-key="${key}" ${checked} />
            <button type="button" class="fs-open">${icon} <span class="fs-name">${e.name}</span></button>
            <span class="fs-size">${size}</span>
          </div>`;
        })
        .join('');

      list.querySelectorAll('.fs-chk').forEach((chk) => {
        chk.addEventListener('change', () => {
          const k = chk.getAttribute('data-key');
          if (chk.checked) this.selected.add(k);
          else this.selected.delete(k);
          this._syncSelActions();
        });
      });

      list.querySelectorAll('.fs-row').forEach((row) => {
        this._bindLongPress(row);
        const openBtn = row.querySelector('.fs-open');
        openBtn?.addEventListener('click', (ev) => {
          if (this._suppressClick) {
            this._suppressClick = false;
            ev.preventDefault();
            return;
          }
          if (row.getAttribute('data-type') === 'dir') {
            this.path = row.getAttribute('data-rel') || '';
            this.selected.clear();
            this.refresh();
          }
        });
      });
    }

    _bindEmptyLongPress(list) {
      // 배경(빈 곳) 길게누름 — 터치에서도 확실히 동작하도록 3중 지원 (2026-09-03)
      //  1) pointerdown(기존) 2) touchstart(스크롤 미세이동 허용: 10px slop) 3) contextmenu(데스크톱 우클릭)
      const start = (x, y) => {
        this._clearPress();
        this._pressStart = { x, y };
        this._pressTimer = setTimeout(() => {
          this._pressTimer = null;
          this._showCtx(x, y);
        }, LONG_MS);
      };
      const slop = (ev) => {
        if (!this._pressStart) return false;
        const t = ev.touches ? ev.touches[0] : ev;
        if (!t) return false;
        const dx = Math.abs((t.clientX || 0) - this._pressStart.x);
        const dy = Math.abs((t.clientY || 0) - this._pressStart.y);
        return dx > 12 || dy > 12; // 12px 이내 미세이동은 누름 유지
      };
      const isBg = (ev) => {
        const t = ev.target;
        if (t === list || (t && (t.classList?.contains('fs-empty') || t.classList?.contains('fs-longpress-hint')))) return true;
        // row 내부가 아니면 배경으로 본다 (리스트 아래 여백 포함)
        return !t.closest || !t.closest('.fs-row');
      };
      list.onpointerdown = (ev) => {
        if (!isBg(ev)) return;
        start(ev.clientX, ev.clientY);
      };
      list.onpointerup = () => this._clearPress();
      list.onpointercancel = () => this._clearPress();
      list.onpointerleave = () => this._clearPress();
      list.addEventListener('touchstart', (ev) => {
        if (!isBg(ev)) return;
        start(ev.touches[0].clientX, ev.touches[0].clientY);
      }, { passive: true });
      list.addEventListener('touchmove', (ev) => {
        if (this._pressTimer && slop(ev)) this._clearPress();
      }, { passive: true });
      list.addEventListener('touchend', () => this._clearPress());
      list.addEventListener('touchcancel', () => this._clearPress());
      list.oncontextmenu = (ev) => {
        ev.preventDefault();
        this._showCtx(ev.clientX, ev.clientY);
      };
    }

    goUp() {
      if (!this.path) return;
      const parts = this.path.split('/').filter(Boolean);
      parts.pop();
      this.path = parts.join('/');
      this.selected.clear();
      this.refresh();
    }

    _selectedItems() {
      return [...this.selected].map((k) => {
        const [root, ...rest] = k.split(':');
        return { root, path: rest.join(':') };
      });
    }

    async mkdir() {
      const name = prompt(_t('fs.new_folder_name', '새 폴더 이름'));
      if (!name) return;
      try {
        await this.api.fsMkdir(this.root, this.path, name.trim());
        await this.refresh();
      } catch (e) {
        alert(_t('fs.mkdir_failed', '폴더 만들기 실패: ') + (e.message || e));
      }
    }

    async rename() {
      const items = this._selectedItems();
      if (items.length !== 1) {
        alert(_t('fs.rename_one', '이름 변경할 항목을 하나만 선택하세요.'));
        return;
      }
      const cur = items[0].path.split('/').pop();
      const name = prompt(_t('fs.new_name', '새 이름'), cur);
      if (!name || name === cur) return;
      try {
        await this.api.fsRename(items[0].root, items[0].path, name.trim());
        this.selected.clear();
        await this.refresh();
      } catch (e) {
        alert(_t('fs.rename_failed', '이름 변경 실패: ') + (e.message || e));
      }
    }

    async remove() {
      const items = this._selectedItems();
      if (!items.length) {
        alert(_t('fs.delete_select', '삭제할 항목을 선택하세요.'));
        return;
      }
      const where = rootLabel(this.root);
      if (
        !confirm(
          `${_t('fs.del_confirm_prefix', 'Permanently delete')} ${items.length} ${_t('fs.del_confirm_from', 'item(s) from')} ${where}?\n\n· ${_t('fs.del_note_files', 'Music files will be permanently deleted')}\n· ${_t('fs.del_note_lib', 'Library shortcuts will be removed too')}\n· ${_t('fs.del_note_irreversible', 'This cannot be undone')}`,
        )
      ) {
        return;
      }
      try {
        const r = await this.api.fsDelete(
          this.root,
          items.map((i) => i.path),
        );
        this.selected.clear();
        await this.refresh();
        if (window._uiBridge?._loadLibrary) window._uiBridge._loadLibrary();
        const nFiles = Array.isArray(r?.deleted) ? r.deleted.length : items.length;
        const nTracks = Number(r?.tracks_removed || 0);
        this._status(
          `${nFiles} ${_t('fs.files_deleted', 'file(s) deleted')}` + (nTracks ? ` · ${nTracks} ${_t('fs.tracks_removed', 'track(s) removed from library')}` : ''),
        );
      } catch (e) {
        alert(_t('fs.delete_failed', 'Delete failed: ') + (e.message || e));
      }
    }

    setClipboard(mode) {
      const items = this._selectedItems();
      if (!items.length) {
        alert(_t('fs.select_first', '항목을 선택하세요.'));
        return;
      }
      this.clipboard = { mode, items };
      const from = rootLabel(items[0].root);
      this._status(
        mode === 'cut'
          ? `${items.length} ${_t('fs.move_pending', 'move pending')} (${from}) — ${_t('fs.paste_hint', 'long-press destination to paste')}`
          : `${items.length} ${_t('fs.copy_pending', 'copy pending')} (${from}) — ${_t('fs.paste_hint', 'long-press destination to paste')}`,
      );
    }

    async paste() {
      if (!this.clipboard?.items?.length) {
        alert(_t('fs.clipboard_empty', '복사/이동할 항목이 없습니다.'));
        return;
      }
      const move = this.clipboard.mode === 'cut';
      let sources = this.clipboard.items;
      let destRoot = this.root;
      let destPath = this.path;
      // 외장(/media) 루트에 붙여넣기 → USB 볼륨 자동 결정 (2026-09-03)
      // 볼륨 1개면 그 볼륨으로 바로, 여러 개면 선택 프롬프트.
      if (destRoot === 'media' && !destPath) {
        const vols = (this.entries || []).filter((e) => e && e.type === 'dir' && /^whick-usb-/.test(e.name || ''));
        if (!vols.length) {
          alert(_t('fs.no_usb', '연결된 외장 USB가 없습니다. USB를 꽂은 뒤 다시 시도해 주세요.'));
          return;
        }
        let vol = vols[0].name;
        if (vols.length > 1) {
          const pick = prompt(
            _t('fs.select_volume', 'Select an external volume to paste into:\n') +
              vols.map((v, i) => `${i + 1}. ${v.name}`).join('\n'),
            '1',
          );
          if (!pick) return;
          const idx = parseInt(pick, 10) - 1;
          if (!(idx >= 0 && idx < vols.length)) return;
          vol = vols[idx].name;
        }
        destPath = vol;
      }
      const destLabel = destPath
        ? `${rootLabel(destRoot)} / ${destPath}`
        : rootLabel(destRoot);
      try {
        const pre = await this.api.fsPreflight(sources, destRoot, destPath);
        if (!pre.ok) {
          alert(
            `${_t('fs.no_space', 'Not enough space')} (${destLabel})\n${_t('fs.need_prefix', 'Need ')}${fmtBytes(pre.need_bytes)} / ${_t('fs.free_prefix2', 'free ')}${fmtBytes(pre.free_bytes)}`,
          );
          return;
        }
        const verb = move ? _t('fs.move', 'Move') : _t('fs.copy', 'Copy');
        const cross = sources.some((s) => s.root !== destRoot)
          ? `\n(${rootLabel(sources[0].root)} → ${rootLabel(destRoot)})`
          : '';
        if (
          !confirm(
            `${verb} ${sources.length} ${_t('fs.paste_confirm_to', 'item(s) to')} ${destLabel}?${cross}` +
              (move ? '\n' + _t('fs.move_note', '(Moving removes the originals)') : ''),
          )
        ) {
          return;
        }
        const copyRes = await this.api.fsCopy(sources, destRoot, destPath, move);
        // 개별 항목 실패가 있으면 완료로 표시하지 않는다 (2026-09-03: 외장 복사 실패가 "완료"로 표시되던 버그)
        const failed = (copyRes?.results || []).filter((r) => r && r.error);
        if (failed.length) {
          const okCount = (copyRes?.results || []).length - failed.length;
          await this.refresh();
          alert(
            `${verb} ${_t('fs.failed_suffix', 'failed:')} ${failed.length} ${_t('fs.items_suffix', 'items')}\n` +
              failed.map((f) => `• ${f.path}: ${f.error}`).join('\n') +
              (okCount > 0 ? `\n(${okCount} ${_t('fs.succeeded_suffix', 'succeeded')})` : ''),
          );
          this._status(`${verb} ${_t('fs.failed_n', 'failed (')} ${failed.length})`);
          return;
        }
        this.clipboard = null;
        this.selected.clear();
        await this.refresh();
        this._status(`${verb} ${_t('fs.done_arrow', 'done →')} ${destLabel}`);
        if (window._uiBridge?._loadLibrary) window._uiBridge._loadLibrary();
      } catch (e) {
        alert((move ? _t('fs.move', '이동') : _t('fs.copy', '복사')) + ' 실패: ' + (e.message || e));
      }
    }

    async registerSelected({ audit = false } = {}) {
      const items = this._selectedItems();
      if (!items.length) {
        alert(_t('fs.add_select', '라이브러리에 추가할 폴더/곡을 선택하세요.'));
        return;
      }
      const auditLabel = audit
        ? _t('fs.audit_desc', '검수로봇 기준을 적용한 뒤 통과 곡만 라이브러리에 추가')
        : _t('fs.no_audit_desc', '검수 없이 선택한 경로를 바로 라이브러리에 추가');
      if (
        !confirm(
          `${items.length} ${_t('fs.add_confirm', 'path(s) selected for')} ${auditLabel}?\n` +
            `${_t('fs.add_note_nocopy', '(Files are not copied; unplayable once the drive is removed)')}\n\n` +
            `${_t('fs.add_note_norm', '⚠️ Volume normalization runs in the background (track by track) after adding.')}\n` +
            `${_t('fs.add_note_pause', 'Playback pauses while playing and for 5 minutes after; large imports may take a while.')}`,
        )
      ) {
        return;
      }
      try {
        const root = items[0].root;
        const paths = items.filter((i) => i.root === root).map((i) => i.path);
        this._status(audit ? _t('fs.auditing', '검수·등록 중…') : _t('fs.importing', '라이브러리 등록 중…'));
        let r = await this.api.fsRegister(root, paths, audit);
        const upserted = Number(r.upserted || 0);
        const skipped = Number(r.skipped || 0);
        if (audit && upserted === 0 && skipped > 0) {
          if (
            confirm(
              `0 ${_t('rev2.passed', 'passed')} · ${skipped} ${_t('rev2.rejected_suffix', 'rejected.')}\n${_t('rev2.add_rejected_q', 'Rules may have filtered everything. Add rejected tracks to the library too?')}`,
            )
          ) {
            r = await this.api.fsRegister(root, paths, false);
            alert(`${_t('fs.add_done_prefix', 'Add complete — ')}${r.upserted || 0}${_t('unit.tracks_short', ' tracks')}`);
          } else {
            alert(
              `${_t('rev2.none_added', 'No tracks added (')} ${skipped} ${_t('rev2.rejected_suffix', 'rejected).')}\n${_t('rev2.lower_note', 'Lower the review threshold in Settings → Library import and retry.')}`,
            );
          }
        } else {
          alert(
            audit
              ? `${_t('fs.audit_done', 'Review & add done — ')}${upserted}${_t('unit.tracks_short', ' tracks')}` + (skipped ? ` · ${skipped} ${_t('rev2.rejected_short', 'rejected')}` : '')
              : `${_t('fs.import_done', 'Library import done — ')}${upserted}${_t('unit.tracks_short', ' tracks')}`,
          );
        }
        if (window._uiBridge?._loadLibrary) window._uiBridge._loadLibrary();
        this._status(`${Number(r.upserted || 0)}${_t('fs.imported_suffix', ' imported')}`);
      } catch (e) {
        alert(_t('fs.import_failed', '등록 실패: ') + (e.message || e));
      }
    }
  }

  window.WhickLibraryFsExplorer = LibraryFsExplorer;
})();
