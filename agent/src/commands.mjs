import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { promisify } from 'node:util';
import { applyRuntimeUpdateDeferred, dockerComposeRestart, dockerComposeRestartDeferred, dockerComposeRebuild, dockerComposeRebuildDeferred, runNetworkTest, runtimeReinstallDeferred, composeProjectName } from './docker-ops.mjs';
import {
  applyHostPowerPolicy,
  devPullUpdate,
  devExec,
  hostReboot,
  rescueReboot,
} from './dev-ops.mjs';
import {
  diagnoseDisk,
  diagnoseApt,
  diagnoseDocker,
  diskCleanupSafe,
  collectDiagLogs,
  dockerServiceRestartDeferred,
} from './diagnose-ops.mjs';
import { ensureMusicTunnel } from './music-tunnel.mjs';
import { collectAllComponentVersions } from './components.mjs';
import { createCcClient, resolveCcUrl } from '../protocol/cc-client.mjs';
import { loadRuntimeState, DEFAULT_STATE_PATH } from '../protocol/runtime-state.mjs';

const exec = promisify(execFile);

// agent 는 network_mode:host — compose 서비스 DNS(whick-player) 불가, 호스트 publish 포트 사용
const AUDIO_URL = process.env.WHICK_AUDIO_URL || 'http://127.0.0.1:8787';
const PLAYER_URL = process.env.WHICK_PLAYER_URL || 'http://127.0.0.1:8080';

async function agentCcClient() {
  const state = loadRuntimeState(process.env.WHICK_STATE_PATH || DEFAULT_STATE_PATH);
  const token = state?.token || process.env.WHICK_AGENT_TOKEN || '';
  if (!token) throw new Error('agent token missing');
  return createCcClient({
    baseUrl: await resolveCcUrl(process.env.WHICK_CC_API_URL, 'agent'),
    token,
    deviceSerial: state?.device_serial || process.env.WHICK_DEVICE_SERIAL || null,
    source: 'agent',
  });
}

async function audioRequest(method, path, body) {
  const res = await fetch(`${AUDIO_URL}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(12_000),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(json.error || res.statusText);
  }
  return json;
}

async function playerRequest(method, path, body) {
  const headers = body ? { 'Content-Type': 'application/json' } : {};
  // player device_auth SSOT: WHICK_PLAYER_DEVICE_TOKEN 또는 /var/lib/whick/remote-device-token
  // (구 player-token 경로는 legacy fallback)
  const tokenCandidates = [
    process.env.WHICK_PLAYER_TOKEN_PATH,
    process.env.WHICK_DEVICE_TOKEN_PATH,
    '/var/lib/whick/remote-device-token',
    '/var/lib/whick/player-token',
  ].filter(Boolean);
  let bearer = String(process.env.WHICK_PLAYER_DEVICE_TOKEN || '').trim();
  if (!bearer) {
    for (const tokenPath of tokenCandidates) {
      try {
        const raw = (await readFile(tokenPath, 'utf-8')).trim();
        if (raw) {
          bearer = raw;
          break;
        }
      } catch {
        /* try next */
      }
    }
  }
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  const res = await fetch(`${PLAYER_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(12_000),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(json.error || json.detail || res.statusText);
  }
  return json;
}

/** 로컬 리모컨 토스트 — CC 링크 끊김/복구 등 (에이전트 → player → remotes) */
export async function notifyPlayerRemotes({ event, title, message, data = {} }) {
  return playerRequest('POST', '/api/notify', {
    event: event || 'notify',
    title: title || '',
    message: message || '',
    data,
  });
}

/**
 * @param {{ command_id: string, command_type: string, params?: object }} cmd
 */
export async function executeCommand(cmd) {
  const type = (cmd.command_type || '').toLowerCase();
  const params = cmd.params || {};

  switch (type) {
    case 'play':
    case 'remote_play':
      return audioRequest('POST', '/play', params);
    case 'pause':
    case 'remote_pause':
      return audioRequest('POST', '/pause', params);
    case 'stop':
    case 'remote_stop':
      return audioRequest('POST', '/stop', params);
    case 'volume':
    case 'remote_volume':
      return audioRequest('POST', '/volume', params);
    case 'docker_restart':
      return dockerComposeRestart(['player']);
    case 'service_restart':
      return dockerComposeRestart(['player', 'agent']);
    case 'full_docker_restart':
      return dockerComposeRestartDeferred([], { commandId: cmd.command_id });
    case 'rebuild':
      return dockerComposeRebuildDeferred();
    case 'runtime_reinstall':
      return runtimeReinstallDeferred({ commandId: cmd.command_id });
    case 'network_test':
      return runNetworkTest();
    case 'dev_pull':
      return devPullUpdate();
    case 'dev_exec':
      return devExec(params.command || params.shell);
    case 'host_reboot':
      return hostReboot(params.delay_sec ?? params.delaySec ?? 30);
    case 'apply_power_policy':
      return applyHostPowerPolicy();
    case 'system_reinstall':
      throw new Error(
        'system_reinstall(rescue) removed — use VIP USB Live for full OS reinstall; runtime_reinstall for Docker only',
      );
    case 'apply_update':
      return applyOtaUpdate(cmd);
    case 'health_check':
      return fullHealthCheck();
    case 'install_verify':
      return installVerifySmoke();
    case 'music_tunnel_apply':
      return ensureMusicTunnel(await agentCcClient());
    case 'consent_notify':
      return playerRequest('POST', '/api/notify', {
        event: params.event || 'consent_request',
        title: params.title || '원격 조치 동의 요청',
        message: params.message || params.text || '',
        data: params.data || {},
      });
    case 'diagnose_disk':
      return diagnoseDisk();
    case 'diagnose_apt':
      return diagnoseApt();
    case 'diagnose_docker':
      return diagnoseDocker();
    case 'disk_cleanup':
      return diskCleanupSafe();
    case 'collect_diag_logs':
      return collectDiagLogs();
    case 'docker_service_restart':
      return dockerServiceRestartDeferred({ commandId: cmd.command_id });
    default:
      throw new Error(`unsupported command_type: ${cmd.command_type}`);
  }
}

export async function audioHealth() {
  return audioRequest('GET', '/health');
}

export async function playerHealth() {
  return playerRequest('GET', '/health');
}

function playerReadiness(player) {
  if (player?.status !== 'ok') return { ok: false, reason: 'player_api_not_ok' };
  if (player?.mpd !== true) return { ok: false, reason: 'mpd_not_ready' };
  if (player?.dac?.connected !== true) return { ok: false, reason: 'dac_not_connected' };
  return { ok: true, reason: 'ready' };
}

/** health_check — audio + player 양쪽 상태 확인 + 컴포넌트 버전 보고 */
export async function fullHealthCheck() {
  const [audio, player, components] = await Promise.allSettled([
    audioHealth(),
    playerHealth(),
    collectAllComponentVersions(),
  ]);
  const audioOk = audio.status === 'fulfilled';
  const playerOk = player.status === 'fulfilled';
  const compOk = components.status === 'fulfilled';
  const playback = playerOk
    ? playerReadiness(player.value)
    : { ok: false, reason: 'player_unreachable' };

  return {
    ok: audioOk && playerOk && playback.ok,
    audio: audioOk ? audio.value : { error: String(audio.reason) },
    player: playerOk ? player.value : { error: String(player.reason) },
    playback,
    components: compOk ? components.value : { error: String(components.reason) },
    message: `health audio=${audioOk} player=${playerOk} playback=${playback.reason} version=${compOk ? components.value.software_version : 'unknown'}`,
  };
}

/** 설치 후 검증 — audio + player health + whick-audio 컨테이너 Up + 컴포넌트 버전 + DAC 상태 */
export async function installVerifySmoke() {
  const [health, playerHealthResult, components] = await Promise.allSettled([
    audioHealth(),
    playerHealth(),
    collectAllComponentVersions(),
  ]);
  const healthResult = health.status === 'fulfilled' ? health.value : { error: String(health.reason) };
  const playerResult = playerHealthResult.status === 'fulfilled' ? playerHealthResult.value : { error: String(playerHealthResult.reason) };
  const compResult = components.status === 'fulfilled' ? components.value : null;

  const runtime = process.env.WHICK_COMPOSE_DIR || '/opt/whick/runtime';
  const composeFile = `${runtime}/compose.yaml`;
  const project = composeProjectName();
  const { stdout } = await exec(
    'docker',
    ['compose', '-p', project, '-f', composeFile, 'ps', '--format', '{{.Name}}:{{.Status}}'],
    { timeout: 45000, cwd: runtime },
  ).catch((e) => ({ stdout: String(e.message || e) }));
  const out = String(stdout || '');
  const playerUp = /whick-player/i.test(out) && /up/i.test(out);
  const audioUp = /whick-audio/i.test(out) && /up/i.test(out);
  if (!playerUp || !audioUp) {
    throw new Error(`whick-player/whick-audio not running: ${out.slice(0, 400)}`);
  }
  const playback = playerReadiness(playerResult);
  if (healthResult?.ok !== true) {
    throw new Error(`whick-audio health failed: ${JSON.stringify(healthResult).slice(0, 300)}`);
  }
  if (!playback.ok) {
    throw new Error(
      `player playback not ready: ${playback.reason} ${JSON.stringify(playerResult).slice(0, 300)}`,
    );
  }
  return {
    message: `install_verify ok player=${playerUp} audio=${audioUp} mpd=ready dac=connected version=${compResult?.software_version || 'unknown'} health=${JSON.stringify(healthResult).slice(0, 200)} ps=${out.slice(0, 300)}`,
    health: healthResult,
    player: playerResult,
    playback,
    components: compResult,
  };
}

/** OTA 업데이트 적용 — CC가 서명한 immutable runtime bundle만 검증·적용. */
export async function applyOtaUpdate(cmd) {
  const params = cmd.params || {};
  const targetVersion = params.target_version || 'latest';
  const installedVersion = params.installed_version || 'unknown';
  const updateId = params.update_id;
  const pkg = params.package || {};

  try {
    if (!updateId || !pkg.url || !pkg.sha256) {
      throw new Error('서명된 업데이트 패키지 정보가 없습니다');
    }
    const ccBase = await resolveCcUrl(process.env.WHICK_CC_API_URL, 'agent');
    const packageUrl = new URL(pkg.url, ccBase).toString();
    return applyRuntimeUpdateDeferred({
      updateId,
      targetVersion,
      packageUrl,
      sha256: pkg.sha256,
      sizeBytes: Number(pkg.size_bytes) || 0,
      commandId: cmd.command_id || null,
    });
  } catch (e) {
    if (updateId) {
      try {
        const cc = await agentCcClient();
        await cc.post(`/agent/updates/${updateId}/report`, {
          payload: {
            success: false,
            message: e.message,
            error_code: 'APPLY_FAILED',
            detail: {
              installed_version: installedVersion,
              target_version: targetVersion,
              current_version: installedVersion,
            },
          },
        });
      } catch (reportErr) {
        console.warn('[agent] update fail report failed:', reportErr.message);
      }
    }
    throw new Error(`업데이트 시작 실패: ${e.message}`);
  }
}
