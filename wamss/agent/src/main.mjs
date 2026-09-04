import os from 'node:os';
import dns from 'node:dns';
import { createCcClient, resolveCcUrl } from '../protocol/cc-client.mjs';
import {
  DEFAULT_STATE_PATH,
  saveRuntimeState,
  touchRuntimeStateHeartbeat,
} from '../protocol/runtime-state.mjs';
import { ensureRegistered } from './register.mjs';
import { executeCommand, notifyPlayerRemotes } from './commands.mjs';
import { networkPayload } from './network.mjs';
import { startAgentCommandWebSocket, postCommandResult } from './command-ws.mjs';
import { ensureMusicTunnel } from './music-tunnel.mjs';
import { collectAllComponentVersions } from './components.mjs';
import { execFile } from 'node:child_process';
import { access, readFile, rename, unlink } from 'node:fs/promises';

const MONITOR_CONTAINERS = ['whick-player', 'whick-audio', 'whick-agent', 'whick-monitor'];

async function containerServices() {
  try {
    const { stdout } = await new Promise((resolve, reject) => {
      execFile('docker', ['ps', '--format', '{{.Names}}\t{{.Status}}'], { timeout: 8000 }, (err, stdout, stderr) => {
        if (err) reject(err);
        else resolve({ stdout, stderr });
      });
    });
    const svc = {};
    const lines = String(stdout).trim().split('\n');
    for (const line of lines) {
      const [name, ...rest] = line.split('\t');
      if (!name) continue;
      const statusRaw = rest.join('\t').toLowerCase();
      const status = statusRaw.startsWith('up') ? 'running' : statusRaw.includes('restarting') ? 'restarting' : 'stopped';
      svc[name] = status;
    }
    // 보정: 모니터링 대상이 docker ps에 없으면 'stopped'
    for (const cn of MONITOR_CONTAINERS) {
      if (!svc[cn]) svc[cn] = 'stopped';
    }
    return svc;
  } catch {
    return {};
  }
}

const STATE_PATH = process.env.WHICK_STATE_PATH || DEFAULT_STATE_PATH;
const POLL_MS = Number(process.env.WHICK_AGENT_POLL_MS || 5000);
const POLL_FALLBACK_MS = Number(process.env.WHICK_AGENT_POLL_FALLBACK_MS || 10000);
const REGISTER_RETRY_MS = Number(process.env.WHICK_REGISTER_RETRY_MS || 10000);
const MUSIC_TUNNEL_RETRY_MS = Number(process.env.WHICK_MUSIC_TUNNEL_RETRY_MS || 60000);

dns.setDefaultResultOrder('ipv4first');

const CC_URL = await resolveCcUrl(process.env.WHICK_CC_API_URL, 'agent');

async function waitForRegister() {
  for (;;) {
    try {
      return await ensureRegistered({ ccUrl: CC_URL, statePath: STATE_PATH });
    } catch (e) {
      const detail = e.cause?.code || e.cause?.message || '';
      console.warn('[agent] register retry', e.code || '', e.message, detail);
      await new Promise((r) => setTimeout(r, REGISTER_RETRY_MS));
    }
  }
}

function buildCcClient(agentState) {
  return createCcClient({
    baseUrl: CC_URL,
    token: agentState.token,
    deviceSerial: agentState.device_serial,
    source: 'agent',
  });
}

let agentState = await waitForRegister();
let pollIntervalSec = Number(agentState.poll_interval_sec || 60);
let cc = buildCcClient(agentState);
let reRegisterPromise = null;
let heartbeatTimer = null;
let commandTimer = null;
let musicTunnelTimer = null;
let musicTunnelReady = false;
let musicTunnelPromise = null;
let commandWsConnected = false;
let stopCommandWs = null;
let ccFailStreak = 0;
let ccLinkNotifiedAt1m = false;
let ccLinkNotifiedAt5m = false;
const CC_FAIL_1M = Math.max(1, Math.ceil(60 / Math.max(1, pollIntervalSec)));
const CC_FAIL_5M = Math.max(CC_FAIL_1M, Math.ceil(300 / Math.max(1, pollIntervalSec)));
const UPDATE_RESULT_PATH = process.env.WHICK_UPDATE_RESULT_PATH || '/var/lib/whick/update-result.json';
const REINSTALL_RESULT_PATH =
  process.env.WHICK_REINSTALL_RESULT_PATH || '/var/lib/whick/reinstall-result.json';
const SYSTEM_REINSTALL_PENDING =
  process.env.WHICK_SYSTEM_REINSTALL_PENDING || '/var/lib/whick/system-reinstall-pending.json';
const OPS_DEFERRED_RESULT_PATH =
  process.env.WHICK_OPS_DEFERRED_RESULT_PATH || '/var/lib/whick/ops-deferred-result.json';

async function flushDeferredUpdateResult(components) {
  const claimPath = '/var/lib/whick/update-result.flushing.json';
  // player status flush 와 경쟁 시 rename 이 원자적 소유권 — 한쪽만 보고
  try {
    await rename(UPDATE_RESULT_PATH, claimPath);
  } catch (e) {
    if (e?.code !== 'ENOENT') console.warn('[agent] update result claim failed:', e.message);
    return;
  }
  let result;
  try {
    result = JSON.parse(await readFile(claimPath, 'utf8'));
  } catch (e) {
    console.warn('[agent] update result read failed:', e.message);
    await rename(claimPath, UPDATE_RESULT_PATH).catch(() => {});
    return;
  }
  if (!result?.update_id || typeof result.success !== 'boolean') {
    await unlink(claimPath).catch(() => {});
    return;
  }
  const message = result.message || (result.success ? '업데이트 완료' : '업데이트 실패');
  const errorCode = result.error_code || (result.success ? null : 'APPLY_FAILED');
  try {
    await cc.post(`/agent/updates/${result.update_id}/report`, {
      payload: {
        success: result.success,
        message,
        error_code: errorCode,
        detail: {
          target_version: result.target_version,
          applied_version: result.success ? result.target_version : undefined,
          software_version: result.success ? result.target_version : components?.software_version,
          components,
          command_id: result.command_id || undefined,
        },
      },
    });
    // CC reportUpdateProgress도 명령을 닫지만, command_id가 있으면 agent에서도 최종 보고 (멱등)
    if (result.command_id) {
      try {
        await postCommandResult(cc, {
          command_id: result.command_id,
          success: result.success,
          message,
          error_code: errorCode,
          detail: {
            final: true,
            deferred: false,
            update_id: result.update_id,
            target_version: result.target_version,
            recovered_from: 'update-result',
          },
        });
      } catch (e) {
        console.warn('[agent] update command final report failed:', e.message);
      }
    }
    await unlink(claimPath).catch(() => {});
    await unlink('/var/lib/whick/update-progress.json').catch(() => {});
    console.log('[agent] update final reported', result.update_id, result.success, result.command_id || '');
  } catch (e) {
    // 보고 실패 시 원본 경로로 되돌려 heartbeat/status 가 재시도 (원본이 새로 생겼으면 덮지 않음)
    try {
      await access(UPDATE_RESULT_PATH);
      await unlink(claimPath).catch(() => {});
    } catch {
      await rename(claimPath, UPDATE_RESULT_PATH).catch(() => {});
    }
    throw e;
  }
}

/** sibling Docker/시스템 재설치 최종 결과 → CC commands/result */
async function flushDeferredReinstallResult() {
  let result;
  try {
    result = JSON.parse(await readFile(REINSTALL_RESULT_PATH, 'utf8'));
  } catch (e) {
    if (e?.code !== 'ENOENT') console.warn('[agent] reinstall result read failed:', e.message);
    return;
  }
  if (!result?.command_id || typeof result.success !== 'boolean') return;
  await postCommandResult(cc, {
    command_id: result.command_id,
    success: result.success,
    message: result.message || (result.success ? '재설치 완료' : '재설치 실패'),
    error_code: result.error_code || (result.success ? null : 'REINSTALL_FAILED'),
    detail: {
      ...(result.detail || {}),
      command_type: result.command_type,
      deferred: false,
      final: true,
    },
  });
  await unlink(REINSTALL_RESULT_PATH).catch(() => {});
  await unlink('/var/lib/whick/reinstall-progress.json').catch(() => {});
  await unlink(SYSTEM_REINSTALL_PENDING).catch(() => {});
  console.log('[agent] reinstall final reported', result.command_id, result.success);
}

/** 시스템 재설치 후 재기동 — pending 파일이 있으면 정상 복귀로 최종 성공 보고 */
async function flushSystemReinstallPending() {
  let pending;
  try {
    pending = JSON.parse(await readFile(SYSTEM_REINSTALL_PENDING, 'utf8'));
  } catch (e) {
    if (e?.code !== 'ENOENT') console.warn('[agent] system-reinstall pending read:', e.message);
    return;
  }
  if (!pending?.command_id) return;
  await postCommandResult(cc, {
    command_id: pending.command_id,
    success: true,
    message: '시스템 재설치 완료 · 정상 가동',
    error_code: null,
    detail: {
      command_type: 'system_reinstall',
      deferred: false,
      final: true,
      recovered_from: 'system-reinstall-pending',
    },
  });
  await unlink(SYSTEM_REINSTALL_PENDING).catch(() => {});
  console.log('[agent] system reinstall recovered', pending.command_id);
}

/** docker_service_restart / full_docker_restart 등 — sibling이 남긴 최종 결과 flush */
async function flushOpsDeferredResult() {
  let result;
  try {
    result = JSON.parse(await readFile(OPS_DEFERRED_RESULT_PATH, 'utf8'));
  } catch (e) {
    if (e?.code !== 'ENOENT') console.warn('[agent] ops-deferred result read failed:', e.message);
    return;
  }
  if (!result?.command_id || typeof result.success !== 'boolean') return;
  await postCommandResult(cc, {
    command_id: result.command_id,
    success: result.success,
    message: result.message || (result.success ? '조치 완료' : '조치 실패'),
    error_code: result.error_code || (result.success ? null : 'OPS_FAILED'),
    detail: {
      ...(result.detail || {}),
      command_type: result.command_type,
      deferred: false,
      final: true,
      recovered_from: 'ops-deferred-result',
    },
  });
  await unlink(OPS_DEFERRED_RESULT_PATH).catch(() => {});
  console.log('[agent] ops deferred final reported', result.command_id, result.success);
}

async function localCcLinkNotify(kind) {
  try {
    if (kind === 'lost_1m') {
      await notifyPlayerRemotes({
        event: 'cc_link_lost',
        title: '관제 연결 불안정',
        message: '관제 서버와 연결이 끊겼습니다. 1분마다 재접속을 시도합니다.',
      });
    } else if (kind === 'lost_5m') {
      await notifyPlayerRemotes({
        event: 'cc_link_lost',
        title: '관제 연결 끊김',
        message: '관제 서버와 연결이 5분 이상 끊긴 상태입니다. 인터넷·공유기를 확인해 주세요.',
      });
    } else if (kind === 'recovered') {
      await notifyPlayerRemotes({
        event: 'cc_link_recovered',
        title: '관제 연결 복구',
        message: '관제 서버와 다시 연결되었습니다.',
      });
    }
  } catch (e) {
    console.warn('[agent] local notify', e.message || e);
  }
}

function scheduleHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(tickHeartbeat, pollIntervalSec * 1000);
}

function scheduleCommands() {
  if (commandTimer) clearInterval(commandTimer);
  const ms = commandWsConnected ? POLL_FALLBACK_MS : POLL_MS;
  commandTimer = setInterval(tickCommands, ms);
}

function scheduleMusicTunnel() {
  if (musicTunnelTimer) clearInterval(musicTunnelTimer);
  musicTunnelTimer = setInterval(tickMusicTunnel, MUSIC_TUNNEL_RETRY_MS);
}

function startCommandSocket() {
  if (stopCommandWs) stopCommandWs();
  stopCommandWs = startAgentCommandWebSocket({
    ccUrl: CC_URL,
    token: agentState.token,
    onCommand: handleRemoteCommand,
    onConnectionChange: (connected) => {
      const prev = commandWsConnected;
      commandWsConnected = connected;
      if (prev !== connected) scheduleCommands();
      // 재접속 직후 즉시 heartbeat → CC가 온라인 인식
      if (!prev && connected) {
        void tickHeartbeat();
      }
    },
  });
}

async function reRegister() {
  if (reRegisterPromise) return reRegisterPromise;
  reRegisterPromise = (async () => {
    console.warn('[agent] token invalid — clearing state and re-registering');
    saveRuntimeState({ token: null, device_id: null }, STATE_PATH);
    agentState = await waitForRegister();
    pollIntervalSec = Number(agentState.poll_interval_sec || pollIntervalSec);
    cc = buildCcClient(agentState);
    musicTunnelReady = false;
    scheduleHeartbeat();
    scheduleMusicTunnel();
    startCommandSocket();
    console.log('[agent] re-registered device_id', agentState.device_id);
  })();
  try {
    await reRegisterPromise;
  } finally {
    reRegisterPromise = null;
  }
}

async function onAgentError(e) {
  if (e?.code === 'AGENT_AUTH_INVALID') {
    await reRegister();
    return true;
  }
  return false;
}

function resolveHealth(services) {
  const player = services['whick-player'];
  const audio = services['whick-audio'];
  if (player === 'stopped' && audio === 'stopped') return 'critical';
  if (player === 'stopped' || audio === 'stopped') return 'warning';
  return 'normal';
}

async function heartbeat() {
  const services = await containerServices();
  let components = null;
  try {
    components = await collectAllComponentVersions();
  } catch (e) {
    console.warn('[agent] component version collect failed:', e.message);
  }
  await cc.post('/agent/heartbeat', {
    type: 'heartbeat',
    payload: {
      health: resolveHealth(services),
      uptime_sec: Math.floor(os.uptime()),
      software_version: components?.software_version || process.env.WHICK_SOFTWARE_VERSION || 'unknown',
      metrics: {},
      network: networkPayload(),
      device_class: process.env.WHICK_DEVICE_CLASS || undefined,
      runtime: {
        agent: 'running',
        command_ws: commandWsConnected ? 'connected' : 'poll',
        services,
      },
      components: components ? {
        software_version: components.software_version,
        docker_engine: components.docker_engine,
        images: components.images,
        host: components.host,
        manifest: components.manifest,
      } : null,
    },
  });
  await flushDeferredUpdateResult(components).catch((e) =>
    console.warn('[agent] update flush', e.message),
  );
  await flushDeferredReinstallResult().catch((e) =>
    console.warn('[agent] reinstall flush', e.message),
  );
  await flushSystemReinstallPending().catch((e) =>
    console.warn('[agent] system-reinstall pending flush', e.message),
  );
  await flushOpsDeferredResult().catch((e) =>
    console.warn('[agent] ops-deferred flush', e.message),
  );
  touchRuntimeStateHeartbeat(STATE_PATH);
}

// 같은 command_id가 WS push·poll 양쪽으로 오거나 poll이 겹쳐도 1회만 실행 (중복 조치 방지)
const handledCommands = new Set();
const HANDLED_MAX = 500;

// 장시간 명령은 poll/WS 핸들러를 블로킹하지 않도록 백그라운드 실행 (heartbeat·poll 유지)
const LONG_RUNNING_COMMANDS = new Set([
  'network_test',
  'full_docker_restart',
  'docker_service_restart',
  'rebuild',
  'runtime_reinstall',
  'system_reinstall',
  'dev_pull',
  'diagnose_apt',
  'disk_cleanup',
  'collect_diag_logs',
  // sibling compose 대기(최대 수 분) — poll/WS 핸들러 블로킹 방지
  'music_tunnel_apply',
]);

async function handleRemoteCommand(cmd) {
  const id = cmd?.command_id;
  if (!id) return;
  if (handledCommands.has(id)) return;
  handledCommands.add(id);
  if (handledCommands.size > HANDLED_MAX) {
    handledCommands.delete(handledCommands.values().next().value);
  }

  const type = (cmd.command_type || '').toLowerCase();
  const finish = async (success, message, error_code, detail) => {
    await postCommandResult(cc, {
      command_id: id,
      success,
      message,
      error_code,
      detail,
    });
  };

  if (LONG_RUNNING_COMMANDS.has(type)) {
    executeCommand(cmd)
      .then((result) => {
        const message = result.message || 'ok';
        console.log('[agent] cmd', cmd.command_type, cmd.command_id, message);
        const detail = {
          ...(result || {}),
          deferred: result?.deferred === true,
          final: result?.final === true,
        };
        // deferred 시작은 success=true + deferred → CC가 running 유지
        return finish(true, message, null, detail);
      })
      .catch((e) => {
        console.warn('[agent] cmd fail', cmd.command_type, e.message);
        return finish(false, e.message, 'CMD_FAILED', { final: true, deferred: false });
      });
    return;
  }

  let success = true;
  let message = 'ok';
  let error_code = null;
  let detail = null;
  try {
    const result = await executeCommand(cmd);
    message = result.message || message;
    detail = result;
    console.log('[agent] cmd', cmd.command_type, cmd.command_id, message);
  } catch (e) {
    success = false;
    message = e.message;
    error_code = 'CMD_FAILED';
    console.warn('[agent] cmd fail', cmd.command_type, e.message);
  }
  await finish(success, message, error_code, detail);
}

async function pollCommands() {
  const data = await cc.get('/agent/commands/poll');
  const commands = data.commands || [];
  for (const cmd of commands) {
    await handleRemoteCommand(cmd);
  }
}

async function tickMusicTunnel() {
  if (musicTunnelReady || musicTunnelPromise) return;
  musicTunnelPromise = (async () => {
    const result = await ensureMusicTunnel(cc);
    if (result?.available) {
      musicTunnelReady = true;
      console.log('[agent] music tunnel', result.message || result.tunnel_host || 'ready');
    } else {
      console.log('[agent] music tunnel pending', result?.reason || 'not_ready');
    }
  })();
  try {
    await musicTunnelPromise;
  } catch (e) {
    if (!(await onAgentError(e))) {
      console.warn('[agent] music tunnel', e.code || '', e.message);
    }
  } finally {
    musicTunnelPromise = null;
  }
}

async function tickHeartbeat() {
  try {
    await heartbeat();
    const wasFailing = ccFailStreak > 0 || ccLinkNotifiedAt1m || ccLinkNotifiedAt5m;
    ccFailStreak = 0;
    if (wasFailing && (ccLinkNotifiedAt1m || ccLinkNotifiedAt5m)) {
      await localCcLinkNotify('recovered');
    }
    ccLinkNotifiedAt1m = false;
    ccLinkNotifiedAt5m = false;
  } catch (e) {
    if (await onAgentError(e)) return;
    ccFailStreak += 1;
    console.warn('[agent] heartbeat', e.code || '', e.message);
    if (!ccLinkNotifiedAt1m && ccFailStreak >= CC_FAIL_1M) {
      ccLinkNotifiedAt1m = true;
      await localCcLinkNotify('lost_1m');
    }
    if (!ccLinkNotifiedAt5m && ccFailStreak >= CC_FAIL_5M) {
      ccLinkNotifiedAt5m = true;
      await localCcLinkNotify('lost_5m');
    }
  }
}

async function tickCommands() {
  try {
    await pollCommands();
  } catch (e) {
    if (await onAgentError(e)) return;
    console.warn('[agent] poll', e.code || '', e.message);
  }
}

console.log('[agent] start serial', (agentState.device_serial || '').slice(0, 12) + '…');
console.log('[agent] heartbeat every', pollIntervalSec, 's · commands poll', POLL_MS, 'ms');

await tickHeartbeat();
await tickMusicTunnel();
startCommandSocket();
await tickCommands();

scheduleHeartbeat();
scheduleMusicTunnel();
scheduleCommands();
