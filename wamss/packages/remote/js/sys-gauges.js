/** packages/remote SSOT — SSD dual-arc gauge */
/**
 * 미니PC 리모컨 — CC 대시보드 스타일 원형 게이지
 * CPU·RAM·SSD·외장 = 사용률(%) · 가동시간(uptime) · 온도
 */
(function (global) {
  const R = 22;
  const C = 2 * Math.PI * R;

  function _t(key, fallback) {
    if (typeof global.WhickI18n !== 'undefined' && typeof global.WhickI18n.t === 'function') {
      const v = global.WhickI18n.t(key);
      if (v && v !== key) return v;
    }
    return fallback;
  }

  function clampPct(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
  }

  function esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function ring(pct, color, label, center) {
    const p = clampPct(pct);
    const fill = C * (p / 100);
    const mid = center != null && center !== '' ? center : `${Math.round(p)}%`;
    return (
      '<div class="sys-gauge">' +
      '<div class="sys-gauge-wrap">' +
      '<svg viewBox="0 0 56 56" aria-hidden="true">' +
      `<circle cx="28" cy="28" r="${R}" fill="none" stroke="var(--border)" stroke-width="5"/>` +
      `<circle cx="28" cy="28" r="${R}" fill="none" stroke="${color}" stroke-width="5" ` +
      `stroke-dasharray="${fill} ${C}" stroke-linecap="round" transform="rotate(-90 28 28)"/>` +
      '</svg>' +
      `<div class="sys-gauge-val${String(mid).length > 4 ? ' sys-gauge-val--sm' : ''}">${mid}</div>` +
      '</div>' +
      `<div class="sys-gauge-lbl">${label}</div>` +
      '</div>'
    );
  }

  /** 원 그래프 없이 디지털시계 타일 (예비) */
  function digitalClock(value, label) {
    const raw = value == null ? '' : String(value);
    const lines = raw.split('\n').filter((x) => x.length);
    const clockInner =
      lines.length > 1
        ? `<div class="sys-gauge-clock sys-gauge-clock--2l">${lines
            .map((ln) => `<span>${esc(ln)}</span>`)
            .join('')}</div>`
        : `<div class="sys-gauge-clock">${esc(raw || '—')}</div>`;
    return (
      '<div class="sys-gauge sys-gauge--clock">' +
      '<div class="sys-gauge-wrap sys-gauge-wrap--clock">' +
      clockInner +
      '</div>' +
      `<div class="sys-gauge-lbl">${label}</div>` +
      '</div>'
    );
  }

  function formatGb(kb) {
    const n = Number(kb);
    if (!Number.isFinite(n) || n <= 0) return '—';
    const gb = n / (1024 * 1024);
    if (gb >= 100) return Math.round(gb) + 'G';
    if (gb >= 10) return gb.toFixed(0) + 'G';
    return gb.toFixed(1) + 'G';
  }

  /** used/total 로 사용률 계산 (pct 없을 때) */
  function usePct(pct, usedKb, totalKb) {
    if (pct != null && Number.isFinite(Number(pct))) return clampPct(pct);
    const t = Number(totalKb);
    const u = Number(usedKb);
    if (t > 0 && Number.isFinite(u) && u >= 0) return clampPct((u / t) * 100);
    return null;
  }

  /**
   * OS=/ · music=음원 파티션 — 각 파티션 사용률(%)을 따로 표시.
   * 미검출(null)은 0%로 위장하지 않고 "—".
   */
  function ssdPairRings(m) {
    const p1 = usePct(m.ssd1_pct, m.ssd1_used_kb, m.ssd1_total_kb);
    const p2 = usePct(m.ssd2_pct, m.ssd2_used_kb, m.ssd2_total_kb);
    const tip1 =
      Number(m.ssd1_total_kb) > 0
        ? 'OS ' + formatGb(m.ssd1_used_kb) + '/' + formatGb(m.ssd1_total_kb)
        : _t('sys.os_partition', 'OS partition');
    const tip2 =
      Number(m.ssd2_total_kb) > 0
        ? 'music ' + formatGb(m.ssd2_used_kb) + '/' + formatGb(m.ssd2_total_kb)
        : _t('sys.music_partition', 'music partition');
    const g1 =
      p1 != null
        ? ring(p1, 'var(--sys-g-ssd)', 'OS').replace(
            '<div class="sys-gauge">',
            '<div class="sys-gauge" title="' + esc(tip1) + '">',
          )
        : ring(0, 'var(--sys-g-ssd)', 'OS', '—');
    const g2 =
      p2 != null
        ? ring(p2, 'var(--sys-g-ext, var(--blue))', 'music').replace(
            '<div class="sys-gauge">',
            '<div class="sys-gauge" title="' + esc(tip2) + '">',
          )
        : ring(0, 'var(--sys-g-ext, var(--blue))', 'music', '—');
    return g1 + g2;
  }

  function formatHours(h) {
    if (h == null || !Number.isFinite(Number(h))) return '—';
    const n = Math.round(Number(h));
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + _t('sys.uptime_wan_unit', '0k h');
    return n.toLocaleString('ko-KR') + 'h';
  }

  /** uptime_sec → 두 줄 "06일" / "17시간" */
  function formatUptime(sec) {
    if (sec == null || !Number.isFinite(Number(sec))) return '—';
    const s = Math.max(0, Math.floor(Number(sec)));
    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    return (
      String(days).padStart(2, '0') +
      _t('sys.uptime_day_unit', '일') +
      '\n' +
      String(hours).padStart(2, '0') +
      _t('sys.uptime_hour_unit', '시간')
    );
  }

  /** 원 중앙용 — 두 줄 HTML */
  function stackCenter(lines) {
    const parts = (lines || []).filter((x) => x != null && String(x).length);
    if (!parts.length) return '—';
    if (parts.length === 1) return esc(parts[0]);
    return (
      '<span class="sys-gauge-val-stack">' +
      parts.map((ln) => `<span>${esc(ln)}</span>`).join('') +
      '</span>'
    );
  }

  function formatUptimeCenter(sec) {
    if (sec == null || !Number.isFinite(Number(sec))) return '—';
    return stackCenter(formatUptime(sec).split('\n'));
  }

  function hoursPct(h, maxH) {
    const cap = maxH || 50000;
    return clampPct((Number(h) / cap) * 100);
  }

  const UPTIME_GAUGE_MAX_DAYS = 30;

  function uptimePct(sec) {
    // 30일 = 원 가득 참 (그 이상은 100% 유지)
    return clampPct((Number(sec) / (UPTIME_GAUGE_MAX_DAYS * 86400)) * 100);
  }

  const TEMP_GAUGE_MAX = 95;

  function tempColor(tempC) {
    const t = Number(tempC);
    if (t >= 75) return 'var(--red)';
    if (t >= 60) return 'var(--amber)';
    return 'var(--sys-g-temp)';
  }

  function normalizeMetrics(raw) {
    const m = raw || {};
    const gpu = m.gpu || {};
    const extMounted = !!(m.ext_mounted || m.external_mounted);
    const ssdHours = m.ssd_hours ?? m.operating_hours ?? m.drive_hours ?? null;
    const uptimeSec =
      m.uptime_sec != null && Number.isFinite(Number(m.uptime_sec))
        ? Number(m.uptime_sec)
        : null;
    const gpuAvailable = !!(m.gpu_available || gpu.available);
    return {
      cpu_pct: m.cpu_pct ?? null,
      mem_pct: m.mem_pct ?? null,
      ssd1_pct: m.ssd1_pct ?? m.disk_pct ?? null,
      ssd2_pct: m.ssd2_pct ?? null,
      ssd1_total_kb: m.ssd1_total_kb ?? null,
      ssd1_used_kb: m.ssd1_used_kb ?? null,
      ssd2_total_kb: m.ssd2_total_kb ?? null,
      ssd2_used_kb: m.ssd2_used_kb ?? null,
      uptime_sec: uptimeSec,
      ssd_hours: ssdHours,
      operating_hours: ssdHours,
      temp_c: m.temp_c ?? null,
      ext_mounted: extMounted,
      ext_pct: extMounted ? (m.ext_pct ?? m.ext_usage_pct ?? null) : null,
      net_pct: m.net_pct ?? m.net ?? m.network_pct ?? null,
      vram_pct: m.vram_pct ?? (gpuAvailable ? gpu.vram_pct : null) ?? null,
      vram_label: m.vram_label ?? (gpuAvailable ? gpu.vram_label : null) ?? null,
      gpu_available: gpuAvailable,
    };
  }

  function buildGauges(raw) {
    const m = normalizeMetrics(raw);
    const row1 = [];
    const row2 = [];

    row1.push(
      m.cpu_pct != null
        ? ring(m.cpu_pct, 'var(--sys-g-cpu)', 'CPU')
        : ring(0, 'var(--sys-g-cpu)', 'CPU', '—'),
    );
    row1.push(
      m.mem_pct != null
        ? ring(m.mem_pct, 'var(--sys-g-ram)', 'RAM')
        : ring(0, 'var(--sys-g-ram)', 'RAM', '—'),
    );
    row1.push(ssdPairRings(m));

    if (m.uptime_sec != null) {
      row2.push(
        ring(
          uptimePct(m.uptime_sec),
          'var(--sys-g-uptime)',
          _t('sys.uptime', '가동시간'),
          formatUptimeCenter(m.uptime_sec),
        ),
      );
    } else {
      row2.push(ring(0, 'var(--sys-g-uptime)', _t('sys.uptime', '가동시간'), '—'));
    }

    if (m.temp_c != null && Number.isFinite(Number(m.temp_c))) {
      const t = Number(m.temp_c);
      // 칩(CPU/SoC) 온도 — 외기 °C와 구분해 라벨. "맑음 + 23°" 시각 혼동 방지.
      row2.push(ring(clampPct((t / TEMP_GAUGE_MAX) * 100), tempColor(t), _t('sys.temp', '칩온도'), `${Math.round(t)}°`));
    } else {
      row2.push(ring(0, 'var(--sys-g-temp)', _t('sys.temp', '칩온도'), '—'));
    }

    if (m.gpu_available && m.vram_pct != null) {
      const label = m.vram_label || `${Math.round(m.vram_pct)}%`;
      row2.push(ring(m.vram_pct, 'var(--sys-g-vram)', 'VRAM', label));
    } else {
      row2.push(ring(0, 'var(--sys-g-vram)', 'VRAM', 'N/A'));
    }

    if (m.ext_mounted && m.ext_pct != null) {
      row2.push(ring(m.ext_pct, 'var(--sys-g-ext)', _t('sys.ext', '외장')));
    } else {
      row2.push(ring(0, 'var(--sys-g-ext)', _t('sys.ext', '외장'), 'N/A'));
    }

    if (!row1.some((g) => g) && !row2.some((g) => g)) {
      return `<div class="sys-gauge-empty">${_t('sys.collecting', '메트릭 수집 중…')}</div>`;
    }

    return (
      '<div class="sys-gauge-grid">' +
      `<div class="sys-gauge-row sys-gauge-row-4">${row1.join('')}</div>` +
      `<div class="sys-gauge-row sys-gauge-row-4">${row2.join('')}</div>` +
      '</div>'
    );
  }

  function getPanelTitle() { return _t('sys.panel_title', '🖥 뮤직서버 실시간 관제'); }
  function getPanelNotice() { return _t('sys.panel_notice', '장애 발생시 AI자동조치 및 알림발송'); }

  function renderAlerts(raw) {
    const alerts = Array.isArray(raw) ? raw : [];
    if (!alerts.length) return '';
    return (
      '<div class="sys-health-alerts">' +
      alerts
        .map((alert) => {
          const recovered =
            alert.event_type === 'recovery' || alert.status === 'recovered';
          const stage = Number(alert.stage) >= 2 ? 2 : 1;
          const status =
            recovered
              ? _t('sys.alert_recovered', 'Alert cleared · recovery notification sent by email')
              : alert.severity === 'remediating'
              ? _t('sys.alert_remediating', 'Re-measuring after AI safety action')
              : stage >= 2
                ? _t('sys.alert_urgent', 'Urgent alert · email sent')
                : _t('sys.alert_unrecovered', 'Unrecovered alert · email sent');
          const value = `${alert.value ?? '—'}${alert.unit || ''}`;
          const detail = recovered
            ? alert.recovery_summary ||
              `${value} ${_t('sys.alert_recovered_after', 'recovered after')} ${alert.remediation || _t('sys.ai_action', 'AI safety action')}`
            : alert.remediation || '';
          return (
            `<div class="sys-health-alert ${recovered ? 'sys-health-alert--recovered' : `sys-health-alert--s${stage}`}">` +
            `<div><b>${esc(alert.label || alert.metric_key || _t('sys.server_status', 'Server status'))}</b> ` +
            `<span>${esc(value)}</span></div>` +
            `<div>${esc(status)}</div>` +
            `<div>${esc(detail)}</div>` +
            '</div>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function renderPanel(opts) {
    const o = opts || {};
    const online = o.online !== false;
    const title = o.title || getPanelTitle();
    const notice = o.notice != null ? o.notice : getPanelNotice();
    const badge = online
      ? `<div class="ssb"><div class="dot" style="width:5px;height:5px"></div>${o.badgeOnline || _t('sys.online', '온라인')}</div>`
      : `<div class="ssb"><div class="dot" style="background:var(--red)"></div>${o.badgeOffline || _t('sys.offline', '오프라인')}</div>`;

    if (!online) {
      let html =
        `<div class="ssh"><div class="sst sst--ops">${title}</div>${badge}</div>` +
        `<div style="font-size:11px;color:var(--text2);margin-top:4px">${o.offlineMsg || _t('sys.offline_msg', '연결을 확인해 주세요.')}</div>`;
      if (notice) html += `<div class="sys-gauge-notice">${notice}</div>`;
      return html;
    }

    let html =
      `<div class="ssh"><div class="sst sst--ops">${title}</div>${badge}</div>` +
      (o.subline ? `<div class="sys-gauge-sub">${o.subline}</div>` : '') +
      buildGauges(o.metrics) +
      renderAlerts(o.alerts);
    if (o.footer) html += `<div class="sys-gauge-foot">${o.footer}</div>`;
    if (notice) html += `<div class="sys-gauge-notice">${notice}</div>`;
    return html;
  }

  function paint(ids, html) {
    const list = Array.isArray(ids) ? ids : [ids];
    list.forEach((id) => {
      const el = typeof id === 'string' ? document.getElementById(id) : id;
      if (el) el.innerHTML = html;
    });
  }

  const WhickSysGauge = {
    get PANEL_TITLE() { return getPanelTitle(); },
    get PANEL_NOTICE() { return getPanelNotice(); },
    TEMP_GAUGE_MAX,
    ring,
    ssdDualRing: ssdPairRings,
    ssdPairRings,
    formatGb,
    formatHours,
    formatUptime,
    formatUptimeCenter,
    hoursPct,
    uptimePct,
    UPTIME_GAUGE_MAX_DAYS,
    tempColor,
    normalizeMetrics,
    buildGauges,
    renderAlerts,
    renderPanel,
    paint,
  };

  global.WhickSysGauge = WhickSysGauge;
})(typeof window !== 'undefined' ? window : globalThis);
