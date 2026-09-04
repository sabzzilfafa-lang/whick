import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const STATE_PATH =
  process.env.WHICK_HEALTH_ALERT_STATE || '/var/lib/whick/run/health-alert-state.json';
const REQUIRED_SAMPLES = Number(process.env.WHICK_HEALTH_REQUIRED_SAMPLES || 3);
const REMEASURE_MS = Number(process.env.WHICK_HEALTH_REMEASURE_SEC || 120) * 1000;
const RECOVERY_SAMPLES = Number(process.env.WHICK_HEALTH_RECOVERY_SAMPLES || 3);

const COMMON_POLICIES = {
  // 30s tick × 2 samples ≈ 1분 지속 고점유
  cpu_pct: {
    label: 'CPU 사용률',
    stage1: 85,
    stage2: 95,
    recovery: 75,
    unit: '%',
    required_samples: 2,
  },
  mem_pct: {
    label: 'RAM 사용률',
    stage1: 85,
    stage2: 95,
    recovery: 75,
    unit: '%',
    required_samples: 2,
  },
  ssd1_pct: {
    label: '시스템 SSD',
    stage1: 80,
    stage2: 90,
    recovery: 75,
    unit: '%',
    remediation: '시스템 디스크 안전 청소(로그·미사용 이미지)',
  },
  ssd2_pct: {
    label: '음악 저장소(/mnt/music)',
    stage1: 80,
    stage2: 90,
    recovery: 75,
    unit: '%',
  },
  // Power-on hours alone is not a failure prediction. It is a lifecycle inspection reminder.
  ssd_hours: {
    label: 'SSD 누적 사용시간',
    stage1: 26280,
    stage2: 43800,
    recovery: 0,
    unit: 'h',
    informational: true,
  },
};

const CPU_THERMAL_BASELINES = [
  {
    pattern: /\b(?:Intel\(R\)\s*)?Processor\s+N(?:100|200|300|305)\b/i,
    officialMaxC: 105,
    source: 'Intel Processor and Core i3 N-Series Datasheet / Intel Product Specifications',
    sourceUrl:
      'https://edc.intel.com/content/www/us/en/design/products/platforms/processor-and-core-i3-n-series-datasheet-volume-1-of-2/001/introduction/',
  },
  {
    pattern: /\bIntel\b/i,
    officialMaxC: 100,
    source: 'Intel Product Specifications fallback; exact model verification required',
    sourceUrl: 'https://www.intel.com/content/www/us/en/products/details/processors.html',
    fallback: true,
  },
  {
    pattern: /\bAMD\b.*\bRyzen\b/i,
    officialMaxC: 95,
    source: 'AMD Ryzen product specifications fallback; exact model verification required',
    sourceUrl: 'https://www.amd.com/en/products/processors/desktops/ryzen.html',
    fallback: true,
  },
];

function thermalPolicy(cpuModel) {
  const baseline =
    CPU_THERMAL_BASELINES.find((item) => item.pattern.test(String(cpuModel || ''))) || {
      officialMaxC: 90,
      source: 'Whick conservative fallback (CPU model not identified)',
      sourceUrl: null,
      fallback: true,
    };
  return {
    label: 'CPU 온도',
    // 긴급: 모델 기준과 무관하게 90°C에서 stage2(긴급)
    stage1: Math.min(baseline.officialMaxC - 20, 80),
    stage2: Math.min(baseline.officialMaxC - 10, 90),
    recovery: Math.min(baseline.officialMaxC - 25, 70),
    unit: '°C',
    official_max_c: baseline.officialMaxC,
    baseline_source: baseline.source,
    baseline_source_url: baseline.sourceUrl,
    baseline_fallback: baseline.fallback === true,
  };
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8'));
  } catch {
    return { version: 1, episodes: {} };
  }
}

function saveState(state) {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  const tmp = `${STATE_PATH}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, STATE_PATH);
}

function episodeId(metricKey, now) {
  return crypto
    .createHash('sha256')
    .update(`${metricKey}:${now}:${crypto.randomUUID()}`)
    .digest('hex')
    .slice(0, 24);
}

function stageFor(value, policy) {
  if (!Number.isFinite(Number(value))) return 0;
  if (Number(value) >= policy.stage2) return 2;
  if (Number(value) >= policy.stage1) return 1;
  return 0;
}

function publicAlert(metricKey, episode, policy, value, now) {
  const elapsed = now - Date.parse(episode.remediation_started_at || episode.first_seen_at);
  const notify = episode.stage >= 2 || elapsed >= REMEASURE_MS;
  return {
    episode_id: episode.episode_id,
    metric_key: metricKey,
    label: policy.label,
    stage: episode.stage,
    severity: episode.stage >= 2 ? 'critical' : notify ? 'warning' : 'remediating',
    value: Number(value),
    unit: policy.unit,
    threshold_stage1: policy.stage1,
    threshold_stage2: policy.stage2,
    first_seen_at: episode.first_seen_at,
    remediation_started_at: episode.remediation_started_at,
    remediation: episode.remediation,
    notify,
    informational: policy.informational === true,
    official_max_c: policy.official_max_c ?? null,
    baseline_source: policy.baseline_source || 'Whick resource policy',
    baseline_source_url: policy.baseline_source_url || null,
    baseline_fallback: policy.baseline_fallback === true,
  };
}

function publicRecovery(metricKey, episode, policy, value, nowIso) {
  return {
    episode_id: episode.episode_id,
    event_type: 'recovery',
    status: 'recovered',
    metric_key: metricKey,
    label: policy.label,
    stage: Number(episode.stage || 1),
    severity: 'recovered',
    value: Number(value),
    recovered_value: Number(value),
    peak_value: Number(episode.peak_value ?? episode.last_value ?? value),
    unit: policy.unit,
    threshold_stage1: policy.stage1,
    threshold_stage2: policy.stage2,
    recovery_threshold: policy.recovery,
    first_seen_at: episode.first_seen_at,
    remediation_started_at: episode.remediation_started_at,
    warning_issued_at: episode.warning_issued_at,
    recovered_at: nowIso,
    remediation: episode.remediation,
    recovery_summary:
      `${episode.remediation || '안전조치 후 재측정'} 결과 ` +
      `${policy.label}이(가) 최고 ${Number(episode.peak_value ?? value)}${policy.unit}에서 ` +
      `${Number(value)}${policy.unit}(으)로 회복되었습니다.`,
    notify: true,
    informational: policy.informational === true,
    official_max_c: policy.official_max_c ?? null,
    baseline_source: policy.baseline_source || 'Whick resource policy',
    baseline_source_url: policy.baseline_source_url || null,
    baseline_fallback: policy.baseline_fallback === true,
  };
}

export function evaluateHealth(metrics, nowMs = Date.now()) {
  const state = readState();
  state.episodes ||= {};
  const nowIso = new Date(nowMs).toISOString();
  const policies = {
    ...COMMON_POLICIES,
    temp_c: thermalPolicy(metrics.cpu_model),
  };
  const alerts = [];
  let suppressNonessentialJobs = false;

  for (const [metricKey, policy] of Object.entries(policies)) {
    const value = metrics[metricKey];
    if (!Number.isFinite(Number(value))) continue;
    const observedStage = stageFor(value, policy);
    let episode = state.episodes[metricKey];

    if (observedStage === 0) {
      if (!episode) continue;
      if (policy.informational || Number(value) > Number(policy.recovery)) {
        episode.recovery_samples = 0;
        episode.last_value = Number(value);
        episode.last_seen_at = nowIso;
        alerts.push(publicAlert(metricKey, episode, policy, value, nowMs));
        continue;
      }
      episode.recovery_samples = (episode.recovery_samples || 0) + 1;
      episode.last_value = Number(value);
      episode.last_seen_at = nowIso;
      if (episode.recovery_samples >= RECOVERY_SAMPLES) {
        if (episode.warning_issued_at) {
          alerts.push(publicRecovery(metricKey, episode, policy, value, nowIso));
        }
        delete state.episodes[metricKey];
      }
      continue;
    }

    if (!episode) {
      episode = {
        episode_id: episodeId(metricKey, nowIso),
        first_seen_at: nowIso,
        consecutive_samples: 0,
        recovery_samples: 0,
        stage: 0,
      };
      state.episodes[metricKey] = episode;
    }
    episode.consecutive_samples = (episode.consecutive_samples || 0) + 1;
    episode.recovery_samples = 0;
    episode.last_value = Number(value);
    episode.peak_value = Math.max(Number(value), Number(episode.peak_value || value));
    episode.last_seen_at = nowIso;

    if (observedStage >= 2 || episode.consecutive_samples >= (policy.required_samples || REQUIRED_SAMPLES)) {
      episode.stage = Math.max(episode.stage || 0, observedStage);
      if (!episode.remediation_started_at) {
        episode.remediation_started_at = nowIso;
        episode.remediation = policy.remediation
          || (policy.informational
            ? 'SSD 데이터 백업 및 상태·교체시기 점검 안내'
            : '비필수 AI·라이브러리 작업 일시 보류 후 재측정');
      }
      if (!policy.informational) suppressNonessentialJobs = true;
      const alert = publicAlert(metricKey, episode, policy, value, nowMs);
      if (alert.notify && !episode.warning_issued_at) {
        episode.warning_issued_at = nowIso;
      }
      alerts.push(alert);
    }
  }

  state.updated_at = nowIso;
  state.cpu_model = metrics.cpu_model || null;
  state.metrics = {
    cpu_pct: metrics.cpu_pct ?? null,
    mem_pct: metrics.mem_pct ?? null,
    ssd1_pct: metrics.ssd1_pct ?? null,
    ssd2_pct: metrics.ssd2_pct ?? null,
    temp_c: metrics.temp_c ?? null,
    ssd_hours: metrics.ssd_hours ?? null,
  };
  state.alerts = alerts;
  state.suppress_nonessential_jobs = suppressNonessentialJobs;
  saveState(state);
  return { alerts, suppress_nonessential_jobs: suppressNonessentialJobs };
}

export function healthStatePath() {
  return STATE_PATH;
}
