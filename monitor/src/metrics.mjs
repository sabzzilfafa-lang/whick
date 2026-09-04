import os from 'node:os';
import fs from 'node:fs';
import { execSync } from 'node:child_process';
import { loadRuntimeState } from '../protocol/runtime-state.mjs';

const AUDIO_EXT = new Set(['.flac', '.wav', '.aiff', '.aif', '.alac', '.mp3', '.m4a', '.ogg']);
const SSD1_MOUNT = process.env.WHICK_DISK_SSD1_MOUNT || '/';
const SSD2_MOUNT = (process.env.WHICK_DISK_SSD2_MOUNT || '/mnt/music').trim();
const SSD2_FALLBACKS = ['/mnt/music', '/var/lib/whick', '/whick-lab'];
const MUSIC_DIR_CANDIDATES = [
  process.env.WHICK_MUSIC_DIR || '/var/lib/whick/library/music',
  '/mnt/music',
];
const AUDIO_URL = (process.env.WHICK_AUDIO_URL || 'http://127.0.0.1:8787').replace(/\/$/, '');
const STATE_PATH = process.env.WHICK_STATE_PATH || '/var/lib/whick/runtime-state.json';
const HARDWARE_HEALTH_PATH =
  process.env.WHICK_HARDWARE_HEALTH_PATH || '/var/lib/whick/run/hardware-health.json';
let previousCpuSample = null;

function containerRunning(name) {
  try {
    const out = execSync(`docker inspect -f '{{.State.Running}}' ${name} 2>/dev/null`, {
      encoding: 'utf8',
      timeout: 3000,
    }).trim();
    if (out === 'true') return 'running';
    if (out === 'false') return 'stopped';
  } catch {
    /* docker unavailable */
  }
  return null;
}

async function probeAudioHealth() {
  try {
    // Node.js fetch가 host-network에서 간헐적 실패 → wget으로 대체
    const out = execSync(`wget -qO- -T 2 ${AUDIO_URL}/health 2>/dev/null`, {
      encoding: 'utf8',
      timeout: 3000,
    }).trim();
    const ok = out.includes('"ok":true') || out.includes('"ok": true');
    return ok ? 'running' : 'degraded';
  } catch {
    return 'stopped';
  }
}

function parseHeartbeatAgeMs() {
  const state = loadRuntimeState(STATE_PATH);
  const raw = state?.last_heartbeat_at;
  if (!raw) return null;
  const ts = Date.parse(String(raw));
  if (!Number.isFinite(ts)) return null;
  return Date.now() - ts;
}

function probeAgentHealth() {
  const docker = containerRunning('whick-agent');
  if (docker) return docker;

  const staleMs = Number(process.env.WHICK_AGENT_HEARTBEAT_STALE_MS || 3 * 60 * 1000);
  const heartbeatAge = parseHeartbeatAgeMs();
  if (heartbeatAge != null) {
    return heartbeatAge < staleMs ? 'running' : 'stopped';
  }

  try {
    const st = fs.statSync(STATE_PATH);
    const ageMs = Date.now() - st.mtimeMs;
    return ageMs < staleMs ? 'running' : 'stopped';
  } catch {
    return 'unknown';
  }
}

function probeMonitorHealth() {
  return containerRunning('whick-monitor') ?? 'running';
}

async function collectServiceStatus() {
  const [audio, agent] = await Promise.all([probeAudioHealth(), Promise.resolve(probeAgentHealth())]);
  return {
    'whick-agent': agent,
    'whick-monitor': probeMonitorHealth(),
    'whick-audio': audio,
    'whick-player': containerRunning('whick-player') ?? probePlayerHealth(),
  };
}

function probePlayerHealth() {
  // fallback: HTTP health check on player API (host network → 127.0.0.1)
  try {
    const out = execSync("wget -qO- -T 2 http://127.0.0.1:8080/api/state 2>/dev/null", {
      encoding: 'utf8', timeout: 3000,
    }).trim();
    return out.includes('"source"') || out.includes('"ok"') ? 'running' : 'stopped';
  } catch {
    return 'stopped';
  }
}

function readCpuCounters() {
  try {
    const parts = fs
      .readFileSync('/proc/stat', 'utf8')
      .split('\n')[0]
      .trim()
      .split(/\s+/)
      .slice(1)
      .map(Number);
    if (parts.length < 4 || parts.some((v) => !Number.isFinite(v))) return null;
    const idle = parts[3] + (parts[4] || 0);
    return { idle, total: parts.reduce((sum, value) => sum + value, 0) };
  } catch {
    return null;
  }
}

function readCpuBusyPct() {
  const current = readCpuCounters();
  if (!current) return null;
  const previous = previousCpuSample;
  previousCpuSample = current;
  if (!previous) return null;
  const totalDelta = current.total - previous.total;
  const idleDelta = current.idle - previous.idle;
  if (totalDelta <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((1 - idleDelta / totalDelta) * 1000) / 10));
}

function readCpuModel() {
  try {
    const text = fs.readFileSync('/proc/cpuinfo', 'utf8');
    const line = text
      .split('\n')
      .find((item) => /^(model name|hardware)\s*:/i.test(item));
    return line ? line.split(':').slice(1).join(':').trim() || null : null;
  } catch {
    return null;
  }
}

function readHardwareHealth() {
  try {
    const data = JSON.parse(fs.readFileSync(HARDWARE_HEALTH_PATH, 'utf8'));
    return {
      ssd_hours: Number.isFinite(Number(data.ssd_hours)) ? Number(data.ssd_hours) : null,
      ssd_model: data.ssd_model || null,
      smart_status: data.smart_status || 'unknown',
    };
  } catch {
    return { ssd_hours: null, ssd_model: null, smart_status: 'unavailable' };
  }
}

function memPct() {
  try {
    const text = fs.readFileSync('/proc/meminfo', 'utf8');
    let total = 0;
    let avail = 0;
    for (const line of text.split('\n')) {
      if (line.startsWith('MemTotal:')) total = Number(line.split(/\s+/)[1]);
      else if (line.startsWith('MemAvailable:')) avail = Number(line.split(/\s+/)[1]);
    }
    if (!total) return null;
    return Math.round(((total - avail) / total) * 1000) / 10;
  } catch {
    return null;
  }
}

function mountUsable(mount) {
  try {
    return fs.existsSync(mount) && fs.statSync(mount).isDirectory();
  } catch {
    return false;
  }
}

function isMountPoint(mount) {
  try {
    if (!mountUsable(mount)) return false;
    const st = fs.statSync(mount);
    const parent = fs.statSync(mount === '/' ? '/' : `${mount}/..`);
    return st.dev !== parent.dev || mount === '/';
  } catch {
    return false;
  }
}

function sameFilesystem(a, b) {
  try {
    return fs.statSync(a).dev === fs.statSync(b).dev;
  } catch {
    return true;
  }
}

function diskStatsForMount(mount) {
  try {
    const out = execSync(`df -Pk ${mount} | tail -1`, { encoding: 'utf8' });
    const parts = out.trim().split(/\s+/);
    if (parts.length < 5) return null;
    const total_kb = Number(parts[1]);
    const used_kb = Number(parts[2]);
    const avail_kb = Number(parts[3]);
    const pct = Number(String(parts[4]).replace('%', ''));
    // 리모트 host_metrics 와 동일 — 정수 %
    const pctInt = Number.isFinite(pct) ? Math.round(pct) : null;
    if (!Number.isFinite(total_kb) || total_kb <= 0 || pctInt == null) return null;
    return { pct: pctInt, total_kb, used_kb, avail_kb, mount };
  } catch {
    return null;
  }
}

function diskPctForMount(mount) {
  const st = diskStatsForMount(mount);
  return st ? st.pct : null;
}

function resolveSsd2Mount(ssd1 = SSD1_MOUNT) {
  const candidates = [];
  if (SSD2_MOUNT) candidates.push(SSD2_MOUNT);
  for (const m of SSD2_FALLBACKS) {
    if (!candidates.includes(m)) candidates.push(m);
  }
  const ssd1Stats = diskStatsForMount(ssd1);
  for (const m of candidates) {
    if (!isMountPoint(m) && !mountUsable(m)) continue;
    try {
      if (!fs.statSync(m).isDirectory()) continue;
    } catch {
      continue;
    }
    // 별도 파티션(dev 다름) 우선
    if (!sameFilesystem(m, ssd1)) return m;
    // bind(/mnt/music/whick-data → /var/lib/whick) 는 컨테이너에서 같은 FS로
    // 보이는 경우가 있어, df 총용량이 OS(/)와 다르면 music 디스크로 인정
    const st = diskStatsForMount(m);
    if (
      st &&
      ssd1Stats &&
      Number.isFinite(st.total_kb) &&
      Number.isFinite(ssd1Stats.total_kb) &&
      Math.abs(st.total_kb - ssd1Stats.total_kb) > 1024 * 1024 // >1GiB 차이
    ) {
      return m;
    }
  }
  return null;
}

/** 별도 music 파티션이 없을 때 — 음원 디렉터리 점유율(/ 전체 대비) */
function directoryUsage(dirPath) {
  try {
    if (!fs.existsSync(dirPath) || !fs.statSync(dirPath).isDirectory()) return null;
    const out = execSync(`du -sk ${JSON.stringify(dirPath)} 2>/dev/null`, {
      encoding: 'utf8',
      timeout: 8000,
    });
    const used_kb = Number(String(out).trim().split(/\s+/)[0]);
    if (!Number.isFinite(used_kb) || used_kb <= 0) return null;
    const st = diskStatsForMount(dirPath);
    if (!st?.total_kb) return null;
    let pct = Math.round((used_kb / st.total_kb) * 100);
    if (pct < 1) pct = 1;
    return {
      pct: Math.min(100, pct),
      used_kb,
      total_kb: st.total_kb,
    };
  } catch {
    return null;
  }
}

function readTempC() {
  try {
    const zones = fs.readdirSync('/sys/class/thermal').filter((z) => z.startsWith('thermal_zone'));
    const temps = [];
    for (const z of zones) {
      const p = `/sys/class/thermal/${z}/temp`;
      if (!fs.existsSync(p)) continue;
      const v = Number(fs.readFileSync(p, 'utf8').trim());
      if (v > 0) temps.push(v / 1000);
    }
    if (!temps.length) return null;
    return Math.round(Math.max(...temps) * 10) / 10;
  } catch {
    return null;
  }
}

export async function collectMetrics() {
  const cpu_pct = readCpuBusyPct();
  const cpu_model = readCpuModel();
  const mem_pct = memPct();
  const ssd1 = diskStatsForMount(SSD1_MOUNT);
  let ssd2Mount = resolveSsd2Mount(SSD1_MOUNT);
  let ssd2 = ssd2Mount ? diskStatsForMount(ssd2Mount) : null;
  const ssd1_pct = ssd1 ? ssd1.pct : null;
  let ssd2_pct = ssd2 ? ssd2.pct : null;
  if (ssd2 && Number(ssd2.used_kb) > 0 && ssd2_pct === 0) ssd2_pct = 1;
  if (ssd2_pct == null) {
    for (const p of MUSIC_DIR_CANDIDATES) {
      const usage = directoryUsage(p);
      if (usage != null) {
        ssd2_pct = usage.pct;
        ssd2Mount = p;
        ssd2 = { pct: usage.pct, used_kb: usage.used_kb, total_kb: usage.total_kb };
        break;
      }
    }
  }
  const temp_c = readTempC();
  const hardware = readHardwareHealth();
  const disk_pct = ssd1_pct;

  let health = 'normal';
  if ((cpu_pct ?? 0) >= 90 || (mem_pct ?? 0) >= 92) health = 'warning';
  if ((ssd1_pct ?? 0) >= 92 || (ssd2_pct ?? 0) >= 92) health = 'warning';

  const services = await collectServiceStatus();
  if (services['whick-audio'] === 'stopped' || services['whick-agent'] === 'stopped') {
    health = health === 'warning' ? 'warning' : 'degraded';
  }

  return {
    health,
    cpu_pct,
    cpu_model,
    mem_pct,
    disk_pct,
    ssd1_pct,
    ssd2_pct,
    ssd1_total_kb: ssd1 ? ssd1.total_kb : null,
    ssd1_used_kb: ssd1 ? ssd1.used_kb : null,
    ssd2_total_kb: ssd2 ? ssd2.total_kb : null,
    ssd2_used_kb: ssd2 ? ssd2.used_kb : null,
    ssd2_mount: ssd2Mount,
    temp_c,
    ssd_hours: hardware.ssd_hours,
    ssd_model: hardware.ssd_model,
    smart_status: hardware.smart_status,
    services,
  };
}

export function isAudioFile(name) {
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  return AUDIO_EXT.has(ext);
}
