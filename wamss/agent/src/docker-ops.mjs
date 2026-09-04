import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { access } from 'node:fs/promises';
import path from 'node:path';
import { loadRuntimeState, DEFAULT_STATE_PATH } from '../protocol/runtime-state.mjs';

const exec = promisify(execFile);

const COMPOSE_DIR = process.env.WHICK_COMPOSE_DIR || '/opt/whick/runtime';
const COMPOSE_FILE = process.env.WHICK_COMPOSE_FILE || path.join(COMPOSE_DIR, 'compose.yaml');
const COMPOSE_OVERRIDE_FILE =
  process.env.WHICK_COMPOSE_OVERRIDE_FILE || path.join(COMPOSE_DIR, 'compose.override.yaml');
const ENV_FILE = process.env.WHICK_ENV_FILE || path.join(COMPOSE_DIR, '.env');
const COMPOSE_PROJECT = process.env.WHICK_COMPOSE_PROJECT || 'whick-runtime';
const CUSTOMER_RUNTIME_SERVICES = (process.env.WHICK_RUNTIME_SERVICES || 'agent,player,monitor')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);
const HOST_TMP = process.env.WHICK_HOST_TMP || '/tmp';

export function composeProjectName() {
  return COMPOSE_PROJECT;
}

// 일반 speedtest(speedtest.net·fast.com)와 동일하게 멀티스트림 + 수 초 sustained 전송으로 측정한다.
// 단발 256KB probe는 TLS/CF 오버헤드·TCP slow-start 때문에 회선속도를 심하게 과소 측정 → 폐기.
const NET_RTT_SAMPLES = 5;
// ⚠️ 일부 미니PC의 USB NIC(r8152/mt7921u 등)는 회선을 sustained 포화시키면 드라이버/펌웨어가
// wedge되어 heartbeat가 끊기고 소프트 재부팅으로도 안 풀린다(현장: power cycle 필요).
// → 정확도보다 "회선을 끊지 않는 것"을 우선해 매우 보수적으로 측정한다.
//   (모두 WHICK_NET_* 환경변수로 재정의 가능 — 재빌드 없이 .env만으로 조정)
const NET_PARALLEL = Number(process.env.WHICK_NET_PARALLEL) || 1; // 단일 스트림 (포화 회피)
const NET_WARMUP_MS = Number(process.env.WHICK_NET_WARMUP_MS) || 500; // TCP slow-start 무시 구간
const NET_MEASURE_MS = Number(process.env.WHICK_NET_MEASURE_MS) || 1200; // 정상상태 측정 구간(짧게)
const NET_DL_CHUNK = Number(process.env.WHICK_NET_DL_CHUNK) || 4 * 1024 * 1024; // 다운로드 요청당 바이트
const NET_UL_CHUNK = Number(process.env.WHICK_NET_UL_CHUNK) || 1 * 1024 * 1024; // 업로드 요청당 바이트(작게)
const NET_MAX_BYTES = Number(process.env.WHICK_NET_MAX_BYTES) || 48 * 1024 * 1024; // 방향당 안전 상한(대폭 축소)
const NET_TRANSFER_TIMEOUT_MS = Number(process.env.WHICK_NET_TRANSFER_TIMEOUT_MS) || 6000;
const NET_WORKER_DRAIN_MS = Number(process.env.WHICK_NET_WORKER_DRAIN_MS) || 1500;
// 각 전송 사이에 짧은 유휴를 둬 heartbeat/제어 패킷이 빠져나갈 틈을 준다(포화 완화).
const NET_PACING_MS = Number(process.env.WHICK_NET_PACING_MS) || 40;
const UPLOAD_BODY = new Uint8Array(NET_UL_CHUNK); // 업로드 페이로드 재사용

// ── 회선 실측(speedtest) 모드 ─────────────────────────────────────────────
// 기본 'cdn': 근거리 CDN(Cloudflare) 다중 스트림 → NIA/speedtest와 동일한 "실제 회선속도" 표시.
// 총 소요 목표 ≤10초(지연~1s + 다운~3.3s + 업~3.3s). 미니PC는 2.5G 내장 랜 기준.
// 'hq': 레거시(본사 관제서버 처리량). WHICK_SPEED_MODE=hq
const SPEED_MODE = (process.env.WHICK_SPEED_MODE || 'cdn').toLowerCase();
const SPEED_ENDPOINT = (process.env.WHICK_SPEED_ENDPOINT || 'https://speed.cloudflare.com').replace(/\/$/, '');
const SPEED_PARALLEL = Number(process.env.WHICK_SPEED_PARALLEL) || 4;
const SPEED_WARMUP_MS = Number(process.env.WHICK_SPEED_WARMUP_MS) || 300;
const SPEED_MEASURE_MS = Number(process.env.WHICK_SPEED_MEASURE_MS) || 2500;
// 업로드는 청크 완료가 측정창 밖으로 밀릴 수 있어 drain을 넉넉히(저녁 혼잡·중속 회선 대비)
const SPEED_DRAIN_MS = Number(process.env.WHICK_SPEED_DRAIN_MS) || 4000;
const SPEED_GAP_MS = Number(process.env.WHICK_SPEED_GAP_MS) || 200;
// 25MB×6 병렬은 Cloudflare 429를 자주 유발 → 청크를 낮춰 안정 실측
const SPEED_DL_CHUNK = Number(process.env.WHICK_SPEED_DL_CHUNK) || 8 * 1024 * 1024;
const SPEED_UL_CHUNK = Number(process.env.WHICK_SPEED_UL_CHUNK) || 4 * 1024 * 1024;
const SPEED_MAX_BYTES = Number(process.env.WHICK_SPEED_MAX_BYTES) || 200 * 1024 * 1024;
const SPEED_TRANSFER_TIMEOUT_MS = Number(process.env.WHICK_SPEED_TRANSFER_TIMEOUT_MS) || 12000;
const SPEED_RTT_SAMPLES = Number(process.env.WHICK_SPEED_RTT_SAMPLES) || 3;
let SPEED_UPLOAD_BODY = null; // 지연 할당(필요 시에만 메모리 점유)
const speedUploadBody = () => (SPEED_UPLOAD_BODY ??= new Uint8Array(SPEED_UL_CHUNK));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function composeArgs(extra) {
  await access(COMPOSE_FILE);
  const args = ['compose', '-p', COMPOSE_PROJECT, '-f', COMPOSE_FILE];
  try {
    await access(COMPOSE_OVERRIDE_FILE);
    args.push('-f', COMPOSE_OVERRIDE_FILE);
  } catch {
    /* optional customer override */
  }
  try {
    await access(ENV_FILE);
    args.push('--env-file', ENV_FILE);
  } catch {
    /* optional .env */
  }
  args.push(...extra);
  return args;
}

/** agent 컨테이너 내부 경로(/opt/whick/runtime)가 아니라 호스트 실제 경로 — docker -v·compose -f용 */
export async function resolveHostRuntimeDir() {
  const fromEnv = process.env.WHICK_HOST_RUNTIME_DIR?.trim();
  if (fromEnv) return fromEnv;
  try {
    const { stdout } = await exec(
      'docker',
      [
        'inspect',
        'whick-agent',
        '--format',
        '{{range .Mounts}}{{if eq .Destination "/opt/whick/runtime"}}{{.Source}}{{end}}{{end}}',
      ],
      { timeout: 15000 },
    );
    const dir = stdout.trim();
    if (dir && dir !== '.') return dir;
  } catch {
    /* fall through */
  }
  return COMPOSE_DIR;
}

async function resolveAgentImage() {
  try {
    const { stdout } = await exec('docker', ['inspect', 'whick-agent', '--format', '{{.Config.Image}}'], {
      timeout: 15000,
    });
    const img = stdout.trim();
    if (img && img !== '<no value>') return img;
  } catch {
    /* fall through */
  }
  return 'docker:27-cli';
}

/**
 * agent 자신을 stop/rebuild하는 작업은 agent 컨테이너 안에서 돌리면 자기 종료 시 스크립트도 죽는다.
 * → 분리된 sibling 컨테이너(detached)에서 실행한다. 실제 docker.sock 마운트로 restart·build 모두 가능하고,
 *   agent가 재기동돼도 sibling은 독립적으로 작업을 끝낸다.
 * @param {string} name 컨테이너 이름 suffix (whick-selfop-<name>)
 * @param {string} innerScript sh -c 본문
 * @param {{ hostDir?: string|null, rw?: boolean }} [opts]
 * @returns {Promise<string>} sibling 컨테이너 이름
 */
export async function spawnSiblingOp(
  name,
  innerScript,
  { hostDir = null, rw = false, mountState = false, network = null } = {},
) {
  const img = await resolveAgentImage();
  const cname = `whick-selfop-${name}`;
  await exec('docker', ['rm', '-f', cname], { timeout: 20000 }).catch(() => {});
  const args = ['run', '-d', '--name', cname, '-v', '/var/run/docker.sock:/var/run/docker.sock'];
  // 기본(bridge) 네트워크는 host 127.0.0.1 published 포트에 닿지 않는다.
  // player /health 처럼 호스트 포트를 확인해야 하는 sibling만 명시적으로 host network를 쓴다.
  if (network) args.push('--network', network);
  if (hostDir) args.push('-v', `${hostDir}:${hostDir}${rw ? '' : ':ro'}`);
  if (mountState) {
    const { stdout } = await exec(
      'docker',
      [
        'inspect',
        'whick-agent',
        '--format',
        '{{range .Mounts}}{{if eq .Destination "/var/lib/whick"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}',
      ],
      { timeout: 15000 },
    );
    const stateSource = stdout.trim();
    if (!stateSource) throw new Error('whick state volume not found');
    args.push('-v', `${stateSource}:/var/lib/whick`);
  }
  args.push('-v', `${HOST_TMP}:${HOST_TMP}`);
  args.push(img, 'sh', '-c', innerScript);
  await exec('docker', args, {
    timeout: 30000,
    env: { ...process.env, PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' },
  });
  return cname;
}

/**
 * sibling 종료 대기 후 제거. exit code 반환 (timeout/inspect 실패 시 1).
 * @param {string} cname
 * @param {{ timeoutMs?: number }} [opts]
 */
export async function waitSiblingOp(cname, { timeoutMs = 300_000 } = {}) {
  const name = String(cname || '').trim();
  if (!name) return 1;
  try {
    const { stdout } = await exec('docker', ['wait', name], {
      timeout: Math.max(30_000, Number(timeoutMs) || 300_000),
      env: { ...process.env, PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' },
    });
    const code = Number(String(stdout || '').trim());
    await exec('docker', ['rm', '-f', name], { timeout: 20000 }).catch(() => {});
    return Number.isFinite(code) ? code : 1;
  } catch (e) {
    await exec('docker', ['rm', '-f', name], { timeout: 20000 }).catch(() => {});
    console.warn('[agent] waitSiblingOp failed', name, e.message || e);
    return 1;
  }
}

function shQuote(value) {
  return `'${String(value ?? '').replace(/'/g, `'\"'\"'`)}'`;
}

/** runtime 번들 재적용 — sibling에서 실제 install-runtime 실행 후 result 파일로 최종 보고 */
export async function runtimeReinstallDeferred({ commandId = null } = {}) {
  const hostDir = await resolveHostRuntimeDir();
  const ccUrl = (process.env.WHICK_CC_API_URL || '').replace(/"/g, '\\"');
  const cmdId = String(commandId || '').replace(/"/g, '');
  const resultFile = '/var/lib/whick/reinstall-result.json';
  const progressFile = '/var/lib/whick/reinstall-progress.json';
  // agent state volume 경로(볼륨명 또는 bind) — 호스트 /var/lib/whick 하드코딩 금지
  // (볼륨만 쓰는 장비에서 중첩 docker:27-cli 가 빈 디렉터리에 result 를 쓰면 CC 미보고)
  const { stdout: stateOut } = await exec(
    'docker',
    [
      'inspect',
      'whick-agent',
      '--format',
      '{{range .Mounts}}{{if eq .Destination "/var/lib/whick"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}',
    ],
    { timeout: 15000 },
  );
  const stateSource = String(stateOut || '').trim();
  if (!stateSource) throw new Error('whick state volume not found');
  const reinstallTimeoutSec = Math.max(
    300,
    Number(process.env.WHICK_RUNTIME_REINSTALL_TIMEOUT_SEC || 1200) || 1200,
  );
  const inner = [
    'set -eu',
    `CMD_ID=${shQuote(cmdId)}`,
    `RESULT_FILE=${shQuote(resultFile)}`,
    `PROGRESS_FILE=${shQuote(progressFile)}`,
    'LOG_FILE=/var/lib/whick/reinstall-last.log',
    'export CMD_ID RESULT_FILE PROGRESS_FILE LOG_FILE',
    'write_progress() { pct="$1"; msg="${2:-}"; printf \'{"command_id":"%s","command_type":"runtime_reinstall","percent":%s,"message":"%s"}\\n\' "$CMD_ID" "$pct" "$msg" >"$PROGRESS_FILE"; }',
    // message/log_tail 은 임의 문자 → node로 JSON 기록 (따옴표·개행 안전)
    'write_result() {',
    '  ok="$1"; msg="$2"; code="${3:-}"; include_log="${4:-0}"',
    '  OK="$ok" MSG="$msg" CODE="$code" INCLUDE_LOG="$include_log" node <<\'NODE\'',
    'const fs = require("fs");',
    'const ok = process.env.OK === "true";',
    'const msg = String(process.env.MSG || "");',
    'const code = String(process.env.CODE || "");',
    'const includeLog = process.env.INCLUDE_LOG === "1";',
    'const logPath = process.env.LOG_FILE || "/var/lib/whick/reinstall-last.log";',
    // DB result_text/json 은 text — 한도는 HTTP·UI 여유(재설치 로그 보통 수~수십 KB)',
    'const LOG_CHARS = 48000;',
    'const LOG_LINES = 400;',
    'let logTail = "";',
    'if (includeLog) {',
    '  try {',
    '    const raw = fs.readFileSync(logPath, "utf8");',
    '    const lines = raw.trimEnd().split(/\\n/);',
    '    logTail = lines.slice(-LOG_LINES).join("\\n");',
    '    if (logTail.length > LOG_CHARS) logTail = logTail.slice(-LOG_CHARS);',
    '  } catch (_) {}',
    '}',
    'const message = logTail',
    '  ? `${msg}\\n--- install-runtime log (tail) ---\\n${logTail}`',
    '  : msg;',
    'const messageOut = message.length > LOG_CHARS ? message.slice(-LOG_CHARS) : message;',
    'const out = {',
    '  command_id: process.env.CMD_ID || "",',
    '  command_type: "runtime_reinstall",',
    '  success: ok,',
    '  message: messageOut,',
    '  error_code: code,',
    '  final: true,',
    '  detail: {',
    '    log_path: logPath,',
    '    log_tail: logTail || undefined,',
    '    log_bytes: (() => { try { return fs.statSync(logPath).size; } catch { return 0; } })(),',
    '  },',
    '};',
    'fs.writeFileSync(process.env.RESULT_FILE, JSON.stringify(out));',
    'NODE',
    '}',
    'on_fail() { rc=$?; write_progress 0 "runtime reinstall failed"; write_result false "runtime reinstall failed (exit $rc)" "APPLY_FAILED" 1; exit "$rc"; }',
    'trap on_fail EXIT',
    'rm -f "$RESULT_FILE"',
    ': > "$LOG_FILE"',
    'write_progress 5 "runtime reinstall start"',
    'echo "== runtime_reinstall start $(date -Iseconds) ==" | tee -a "$LOG_FILE"',
    'if ! docker image inspect docker:27-cli >/dev/null 2>&1; then',
    '  write_progress 8 "pulling docker:27-cli"',
    '  echo "== pulling docker:27-cli ==" | tee -a "$LOG_FILE"',
    '  timeout 300 docker pull docker:27-cli >>"$LOG_FILE" 2>&1',
    'fi',
    'write_progress 12 "install-runtime in docker:27-cli"',
    'echo "== install-runtime begin $(date -Iseconds) ==" | tee -a "$LOG_FILE"',
    // 출력은 state volume 로그에 보존 — CC 실패 보고·collect_diag 용
    `timeout ${reinstallTimeoutSec} docker run --rm --privileged \\`,
    `  -v "${hostDir}:${hostDir}" -v /var/run/docker.sock:/var/run/docker.sock \\`,
    `  -v "${stateSource}:/var/lib/whick" \\`,
    `  -e WHICK_RUNTIME_ROOT="${hostDir}" -e WHICK_CC_API_URL="${ccUrl}" -e WHICK_DISABLE_POWER_SAVING=0 \\`,
    `  -e WHICK_SKIP_HOST_PROBES=1 \\`,
    `  -w "${hostDir}" docker:27-cli \\`,
    `  sh -c 'apk add --no-cache bash python3 curl zstd >/dev/null 2>&1 || true; bash scripts/install-runtime.sh' >>"$LOG_FILE" 2>&1`,
    'echo "== install-runtime end $(date -Iseconds) ==" | tee -a "$LOG_FILE"',
    'write_progress 100 "runtime reinstall OK"',
    'echo "== runtime_reinstall OK $(date -Iseconds) ==" | tee -a "$LOG_FILE"',
    'write_result true "Docker 재설치 완료" "" 0',
    'trap - EXIT',
  ].join('\n');
  const cname = await spawnSiblingOp('runtime-reinstall', inner, {
    hostDir,
    rw: true,
    mountState: true,
  });
  return {
    message: `Docker 재설치 진행 중 (${cname})`,
    deferred: true,
    final: false,
    sibling: cname,
    command_id: cmdId || null,
    timeout_sec: reinstallTimeoutSec,
  };
}

/** CC가 지정한 immutable runtime bundle을 검증·적용하고 결과를 state volume에 남긴다. */
export async function applyRuntimeUpdateDeferred({
  updateId,
  targetVersion,
  packageUrl,
  sha256,
  sizeBytes = 0,
  commandId = null,
}) {
  if (!updateId || !targetVersion || !packageUrl || !/^[0-9a-f]{64}$/i.test(String(sha256 || ''))) {
    throw new Error('invalid update package parameters');
  }
  const hostDir = await resolveHostRuntimeDir();
  const safeVersion = String(targetVersion).replace(/[^a-zA-Z0-9._-]/g, '_');
  const tarName = `whick-runtime-${safeVersion}.tar.zst`;
  const tarPath = `${HOST_TMP}/${tarName}`;
  const stageDir = `${hostDir}/.update-stage`;
  const resultFile = '/var/lib/whick/update-result.json';
  const progressFile = '/var/lib/whick/update-progress.json';
  const expected = Math.max(0, Number(sizeBytes) || 0);
  const cmdId = String(commandId || '').replace(/[^a-zA-Z0-9_-]/g, '');
  const inner = [
    'set -eu',
    `UPDATE_ID=${shQuote(updateId)}`,
    `TARGET_VERSION=${shQuote(targetVersion)}`,
    `PACKAGE_URL=${shQuote(packageUrl)}`,
    `PACKAGE_SHA=${shQuote(sha256)}`,
    `EXPECTED_BYTES=${shQuote(String(expected))}`,
    `COMMAND_ID=${shQuote(cmdId)}`,
    `TAR_NAME=${shQuote(tarName)}`,
    `TAR_PATH=${shQuote(tarPath)}`,
    `HOST_DIR=${shQuote(hostDir)}`,
    `STAGE_DIR=${shQuote(stageDir)}`,
    `RESULT_FILE=${shQuote(resultFile)}`,
    `PROGRESS_FILE=${shQuote(progressFile)}`,
    'write_progress() { pct="$1"; phase="$2"; msg="${3:-}"; printf \'{"update_id":%s,"percent":%s,"phase":"%s","message":"%s","target_version":"%s"}\\n\' "$UPDATE_ID" "$pct" "$phase" "$msg" "$TARGET_VERSION" >"$PROGRESS_FILE"; }',
    'STOPPED_FOR_OTA=0',
    // 중지 이후 실패하면 미니PC가 무음·무에이전트로 남는 것을 막음 (Bugbot High)
    'restore_runtime_best_effort() {',
    '  echo "== OTA failure restore: bring runtime back =="',
    '  set +e',
    '  set -- -p whick-runtime -f "$HOST_DIR/compose.yaml"',
    '  [ -f "$HOST_DIR/compose.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.override.yaml"',
    '  [ -f "$HOST_DIR/compose.tunnel.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.tunnel.override.yaml"',
    '  [ -f "$HOST_DIR/compose.music-data.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.music-data.override.yaml"',
    '  [ -f "$HOST_DIR/compose.gpu.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.gpu.override.yaml"',
    '  [ -f "$HOST_DIR/.env" ] && set -- "$@" --env-file "$HOST_DIR/.env"',
    '  LOCAL_AI_FLAG=1',
    '  [ -f "$HOST_DIR/.env" ] && LOCAL_AI_FLAG=$(grep -oP \'^WHICK_LOCAL_AI=\\K.+\' "$HOST_DIR/.env" 2>/dev/null | head -1 || echo 1)',
    '  PROFILE_ARGS=""',
    '  [ "${LOCAL_AI_FLAG:-1}" != "0" ] && PROFILE_ARGS="--profile local-ai"',
    '  SVCS=$(docker compose "$@" $PROFILE_ARGS config --services 2>/dev/null | grep -vx player-db | tr "\\n" " " || true)',
    '  [ -z "$(echo "$SVCS" | tr -d "[:space:]")" ] && SVCS="docker-socket-proxy audio agent monitor player tunnel"',
    '  docker compose "$@" up -d --no-build --pull never --no-recreate player-db 2>/dev/null || true',
    '  # shellcheck disable=SC2086',
    '  docker compose "$@" $PROFILE_ARGS up -d --no-build --pull never --remove-orphans --no-deps $SVCS 2>/dev/null || docker start whick-agent whick-player whick-monitor whick-audio whick-docker-proxy whick-tunnel 2>/dev/null || true',
    '  set -e',
    '}',
    'write_failure() { rc=$?; if [ "$rc" -ne 0 ]; then write_progress 0 failed "update failed"; printf \'{"update_id":%s,"command_id":"%s","success":false,"target_version":"%s","error_code":"APPLY_FAILED","message":"runtime update failed (exit %s)"}\\n\' "$UPDATE_ID" "$COMMAND_ID" "$TARGET_VERSION" "$rc" >"$RESULT_FILE"; [ "${STOPPED_FOR_OTA:-0}" = "1" ] && restore_runtime_best_effort; fi; }',
    'trap write_failure EXIT',
    'rm -f "$RESULT_FILE" "$TAR_PATH"',
    'rm -rf "$STAGE_DIR" && mkdir -p "$STAGE_DIR"',
    // 업데이트 전 이미지 ID 기록 → 성공 후 삭제 (옛·새 이중 점유 방지).
    // player-db 는 데이터 컨테이너라 중지·삭제 대상에서 제외.
    'PREV_IMAGE_IDS=""',
    `for cid in $(docker ps -aq --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" 2>/dev/null || true); do`,
    '  [ -z "$cid" ] && continue',
    '  docker inspect "$cid" >/dev/null 2>&1 || continue',
    '  cname=$(docker inspect --format "{{.Name}}" "$cid" 2>/dev/null | sed "s#^/##")',
    '  case "$cname" in *player-db*|whick-selfop-*) continue ;; esac',
    '  iid=$(docker inspect --format "{{.Image}}" "$cid" 2>/dev/null) || continue',
    '  [ -z "$iid" ] && continue',
    '  docker image inspect "$iid" >/dev/null 2>&1 || continue',
    '  PREV_IMAGE_IDS="$PREV_IMAGE_IDS $iid"',
    'done',
    'write_progress 1 starting "업데이트 준비 중"',
    'docker run --rm -v /tmp:/out curlimages/curl:8.5.0 curl -fSL4 --retry 3 --max-time 1800 "$PACKAGE_URL" -o "/out/$TAR_NAME" &',
    'CURL_PID=$!',
    'while kill -0 "$CURL_PID" 2>/dev/null; do',
    '  SZ=$(stat -c%s "$TAR_PATH" 2>/dev/null || echo 0)',
    '  if [ "$EXPECTED_BYTES" -gt 0 ] 2>/dev/null; then',
    '    PCT=$(( SZ * 70 / EXPECTED_BYTES + 5 ))',
    '    [ "$PCT" -gt 74 ] && PCT=74',
    '    [ "$PCT" -lt 5 ] && PCT=5',
    '  else',
    '    PCT=20',
    '  fi',
    '  write_progress "$PCT" download "패키지 다운로드 중"',
    '  sleep 1',
    'done',
    'wait "$CURL_PID"',
    'write_progress 75 verify "무결성 확인 중"',
    'echo "$PACKAGE_SHA  $TAR_PATH" | sha256sum -c -',
    // 파파님 SSOT: 기존 내리고 → 새 올리는 순서. extract/load 전에 중지해 이중 점유·과열 차단.
    'write_progress 76 stop "기존 서비스 중지 중 (player-db 유지)"',
    'echo "== OTA: stop old runtime before extract/load =="',
    `for cid in $(docker ps -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" 2>/dev/null || true); do`,
    '  [ -z "$cid" ] && continue',
    '  cname=$(docker inspect --format "{{.Name}}" "$cid" 2>/dev/null | sed "s#^/##")',
    '  case "$cname" in *player-db*|whick-selfop-*) continue ;; esac',
    '  docker stop "$cid" 2>/dev/null || true',
    'done',
    'docker stop whick-ollama whick-runtime-ollama whick-player whick-audio whick-monitor whick-agent whick-tunnel whick-docker-proxy 2>/dev/null || true',
    'STOPPED_FOR_OTA=1',
    'write_progress 78 extract "압축 해제 중 (저우선순위)"',
    'if command -v apk >/dev/null 2>&1; then apk add --no-cache zstd tar >/dev/null; elif command -v apt-get >/dev/null 2>&1; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd tar >/dev/null; fi',
    // zstd+tar 가 CPU·디스크를 동시에 밀어 온도가 급상승함 → nice/ionice 로 완화
    'run_low() { if command -v ionice >/dev/null 2>&1; then nice -n 19 ionice -c3 "$@"; else nice -n 19 "$@"; fi; }',
    'run_low sh -c \'zstd -dc "$1" | tar -xf - -C "$2"\' _ "$TAR_PATH" "$STAGE_DIR"',
    'test -f "$STAGE_DIR/compose.yaml" && test -f "$STAGE_DIR/scripts/install-runtime.sh"',
    'write_progress 85 install "런타임 적용 중"',
    'for f in .env compose.tunnel.override.yaml compose.music-data.override.yaml; do [ -f "$HOST_DIR/$f" ] && cp "$HOST_DIR/$f" "/tmp/whick-update-$f"; done',
    'cp -a "$STAGE_DIR/." "$HOST_DIR/"',
    'for f in .env compose.tunnel.override.yaml compose.music-data.override.yaml; do [ -f "/tmp/whick-update-$f" ] && mv "/tmp/whick-update-$f" "$HOST_DIR/$f"; done',
    'rm -rf "$STAGE_DIR" "$TAR_PATH"',
    'write_progress 90 load "새 이미지 로드 중 (저우선순위·분할)"',
    // ollama 이미지(~수 GB)는 마지막·LOCAL_AI 일 때만. 이미지 사이 sleep 으로 열 방출 여유.
    'LOCAL_AI_FLAG=1',
    '[ -f "$HOST_DIR/.env" ] && LOCAL_AI_FLAG=$(grep -oP \'^WHICK_LOCAL_AI=\\K.+\' "$HOST_DIR/.env" 2>/dev/null | head -1 || echo 1)',
    'load_image_tar() {',
    '  img="$1"; [ -f "$img" ] || return 0',
    '  echo "docker load: $(basename "$img")"',
    '  run_low docker load -i "$img" >/dev/null',
    '  sleep 3',
    '}',
    'for image_tar in "$HOST_DIR"/offline/images/*.tar; do',
    '  [ -f "$image_tar" ] || continue',
    '  case "$(basename "$image_tar")" in ollama_*) continue ;; esac',
    '  load_image_tar "$image_tar"',
    'done',
    'if [ "${LOCAL_AI_FLAG:-1}" != "0" ]; then',
    '  for image_tar in "$HOST_DIR"/offline/images/ollama_*.tar; do load_image_tar "$image_tar"; done',
    'fi',
    'write_progress 95 restart "서비스 재시작 중"',
    'set -- -p whick-runtime -f "$HOST_DIR/compose.yaml"',
    '[ -f "$HOST_DIR/compose.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.override.yaml"',
    '[ -f "$HOST_DIR/compose.tunnel.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.tunnel.override.yaml"',
    '[ -f "$HOST_DIR/compose.music-data.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.music-data.override.yaml"',
    '[ -f "$HOST_DIR/compose.gpu.override.yaml" ] && set -- "$@" -f "$HOST_DIR/compose.gpu.override.yaml"',
    '[ -f "$HOST_DIR/.env" ] && set -- "$@" --env-file "$HOST_DIR/.env"',
    // local-ai(ollama)는 compose profile로 게이트돼 있어 --profile 없이 up 하면
    // 이미지가 새로 load 돼도 기존 컨테이너가 재생성되지 않고 방치된다.
    // OTA는 install-runtime을 다시 안 돌리므로, 여기서 램 기반 모델을 .env에 반영한다.
    'LOCAL_AI_FLAG=1',
    '[ -f "$HOST_DIR/.env" ] && LOCAL_AI_FLAG=$(grep -oP \'^WHICK_LOCAL_AI=\\K.+\' "$HOST_DIR/.env" 2>/dev/null | head -1 || echo 1)',
    'if [ "${LOCAL_AI_FLAG:-1}" != "0" ] && [ -f "$HOST_DIR/.env" ]; then',
    '  PINNED=$(grep -oP \'^WHICK_OLLAMA_MODEL=\\K.+\' "$HOST_DIR/.env" 2>/dev/null | head -1 || true)',
    '  MEM_KB=$(awk \'/MemTotal:/ {print $2}\' /proc/meminfo 2>/dev/null || echo 0)',
    '  if [ -n "$PINNED" ]; then OMODEL="$PINNED"',
    '  elif [ "${MEM_KB:-0}" -ge 25165824 ]; then OMODEL=gemma4:e4b',
    '  else OMODEL=gemma4:e2b; fi',
    '  if grep -q \'^OLLAMA_MODEL=\' "$HOST_DIR/.env"; then sed -i "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$OMODEL|" "$HOST_DIR/.env"',
    '  else echo "OLLAMA_MODEL=$OMODEL" >>"$HOST_DIR/.env"; fi',
    'fi',
    // install-runtime compose_up_except_player_db 와 동일 가드:
    // player-db keep + --no-build --pull never + force-recreate --no-deps + 1회 재시도
    'PROFILE_ARGS=""',
    'if [ "${LOCAL_AI_FLAG:-1}" != "0" ]; then PROFILE_ARGS="--profile local-ai"; fi',
    // ollama 는 핵심 서비스 기동·쿨다운 후에만 올린다 (OTA 직후 과열 방지). pull 은 OTA 에서 생략.
    'SVCS=$(docker compose "$@" $PROFILE_ARGS config --services 2>/dev/null | grep -vx player-db | grep -vx ollama | tr "\\n" " " || true)',
    'if [ -z "$(echo "$SVCS" | tr -d "[:space:]")" ]; then',
    '  SVCS="docker-socket-proxy audio agent monitor player"',
    '  [ -f "$HOST_DIR/compose.tunnel.override.yaml" ] && SVCS="$SVCS tunnel"',
    'fi',
    'compose_up_except_player_db() {',
    '  echo "keep player-db; force-recreate --no-deps: $SVCS"',
    '  docker compose "$@" up -d --no-build --pull never --no-recreate player-db',
    '  # shellcheck disable=SC2086',
    '  docker compose "$@" $PROFILE_ARGS up -d --no-build --pull never --remove-orphans --force-recreate --no-deps $SVCS',
    '}',
    'if ! compose_up_except_player_db "$@"; then',
    '  echo "WARN compose up failed — ensure player-db then retry once"',
    '  docker compose "$@" up -d --no-build --pull never --no-recreate player-db || true',
    '  sleep 3',
    '  compose_up_except_player_db "$@"',
    'fi',
    'if [ "${LOCAL_AI_FLAG:-1}" != "0" ]; then',
    '  echo "== OTA cooldown before ollama start (thermal) =="',
    '  sleep 20',
    '  docker compose "$@" $PROFILE_ARGS up -d --no-build --pull never --no-deps ollama 2>/dev/null || true',
    '  echo "skip ollama pull during OTA (use on-demand later)"',
    'fi',
    // .env는 보존하므로 버전 stamp를 여기서 반영 — cleanup 실패해도 버전은 맞춘다.
    'if [ -f "$HOST_DIR/.env" ]; then',
    '  if grep -q "^WHICK_SOFTWARE_VERSION=" "$HOST_DIR/.env"; then sed -i "s|^WHICK_SOFTWARE_VERSION=.*|WHICK_SOFTWARE_VERSION=$TARGET_VERSION|" "$HOST_DIR/.env"',
    '  else echo "WHICK_SOFTWARE_VERSION=$TARGET_VERSION" >>"$HOST_DIR/.env"; fi',
    // OTA는 install-runtime.sh 를 안 타서 PORT80 미기입 → LAN http://IP/ 연결거부 재발 방지
    // install-runtime 과 동일: 0.0.0.0:아무포트 이면 PORT80 개방
    '  if grep -qE "^WHICK_PLAYER_PORT_BIND=0\\.0\\.0\\.0:" "$HOST_DIR/.env"; then',
    '    if grep -q "^WHICK_PLAYER_PORT80_BIND=" "$HOST_DIR/.env"; then sed -i "s|^WHICK_PLAYER_PORT80_BIND=.*|WHICK_PLAYER_PORT80_BIND=0.0.0.0:80|" "$HOST_DIR/.env"',
    '    else printf "\\nWHICK_PLAYER_PORT80_BIND=0.0.0.0:80\\n" >>"$HOST_DIR/.env"; fi',
    '  fi',
    'fi',
    // KMA 키가 비어 있으면 번들 .env.example 에서 채움 (보존된 .env 에 키 없으면 Open-Meteo만 쓰게 됨)
    'if [ -f "$HOST_DIR/.env" ] && [ -f "$HOST_DIR/.env.example" ]; then',
    '  ENVF="$HOST_DIR/.env"; EX="$HOST_DIR/.env.example"',
    '  cur=$(grep -E "^WHICK_KMA_SERVICE_KEY=" "$ENVF" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\\r" || true)',
    '  if [ -z "$cur" ]; then',
    '    don=$(grep -E "^WHICK_KMA_SERVICE_KEY=" "$EX" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\\r" || true)',
    '    if [ -n "$don" ]; then',
    '      if grep -q "^WHICK_KMA_SERVICE_KEY=" "$ENVF"; then sed -i "s|^WHICK_KMA_SERVICE_KEY=.*|WHICK_KMA_SERVICE_KEY=$don|" "$ENVF"',
    '      else echo "WHICK_KMA_SERVICE_KEY=$don" >>"$ENVF"; fi',
    '    fi',
    '  fi',
    '  if ! grep -q "^WHICK_KMA_BASE_URL=." "$ENVF" 2>/dev/null; then',
    '    base=$(grep -E "^WHICK_KMA_BASE_URL=" "$EX" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "\\r" || true)',
    '    base=${base:-https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0}',
    '    if grep -q "^WHICK_KMA_BASE_URL=" "$ENVF"; then sed -i "s|^WHICK_KMA_BASE_URL=.*|WHICK_KMA_BASE_URL=$base|" "$ENVF"',
    '    else echo "WHICK_KMA_BASE_URL=$base" >>"$ENVF"; fi',
    '  fi',
    '  if ! grep -q "^WHICK_WEATHER_PROVIDER=." "$ENVF" 2>/dev/null; then',
    '    if grep -q "^WHICK_WEATHER_PROVIDER=" "$ENVF"; then sed -i "s|^WHICK_WEATHER_PROVIDER=.*|WHICK_WEATHER_PROVIDER=kma|" "$ENVF"',
    '    else echo "WHICK_WEATHER_PROVIDER=kma" >>"$ENVF"; fi',
    '  fi',
    'fi',
    // 번들 내부 lock 버전이 과거 릴리스 잔존이어도 적용 target 으로 보정 (재업데이트 루프 방지).
    // sibling(agent Alpine) 에 python 이 없을 수 있어 sed 만 사용.
    'if [ -f "$HOST_DIR/components.lock.json" ]; then',
    '  sed -i "s/\\"version\\": *\\"[^\\"]*\\"/\\"version\\": \\"$TARGET_VERSION\\"/" "$HOST_DIR/components.lock.json" || true',
    '  sed -i "s/\\"file\\": *\\"music-01-runtime-[^\\"]*\\"/\\"file\\": \\"music-01-runtime-$TARGET_VERSION.tar.zst\\"/" "$HOST_DIR/components.lock.json" || true',
    'fi',
    'printf "%s\\n" "$TARGET_VERSION" >"$HOST_DIR/software-version.txt" 2>/dev/null || true',
    // 핵심 서비스 기동 확인 후에만 성공·옛 이미지 삭제 (Bugbot High)
    'write_progress 96 health "서비스 상태 확인 중"',
    'healthy=0',
    'for _i in 1 2 3 4 5 6 7 8 9 10 11 12; do',
    '  agent_up=$(docker inspect -f "{{.State.Running}}" whick-agent 2>/dev/null || echo false)',
    '  player_up=$(docker inspect -f "{{.State.Running}}" whick-player 2>/dev/null || echo false)',
    '  if [ "$agent_up" = "true" ] && [ "$player_up" = "true" ]; then healthy=1; break; fi',
    '  sleep 5',
    'done',
    'if [ "$healthy" != "1" ]; then',
    '  echo "ERROR: whick-agent/player not running after update — refuse success/cleanup"',
    '  exit 2',
    'fi',
    'write_progress 97 cleanup "이전 이미지 삭제 중"',
    'set +e',
    'for c in $(docker ps -aq --filter "name=whick-keepimg-" 2>/dev/null || true); do',
    '  [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1',
    'done',
    'NEW_IMAGE_IDS=""',
    `for cid in $(docker ps -aq --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" 2>/dev/null || true); do`,
    '  [ -z "$cid" ] && continue',
    '  iid=$(docker inspect --format "{{.Image}}" "$cid" 2>/dev/null) || continue',
    '  [ -n "$iid" ] && NEW_IMAGE_IDS="$NEW_IMAGE_IDS $iid"',
    'done',
    'for iid in $PREV_IMAGE_IDS; do',
    '  [ -z "$iid" ] && continue',
    '  keep=0',
    '  for nid in $NEW_IMAGE_IDS; do [ "$nid" = "$iid" ] && keep=1 && break; done',
    '  [ "$keep" = "1" ] && continue',
    '  echo "rmi old image $iid"',
    '  docker rmi -f "$iid" >/dev/null 2>&1 || true',
    'done',
    'docker image prune -af >/dev/null 2>&1',
    'rm -f "$HOST_DIR"/offline/images/*.tar 2>/dev/null || true',
    'set -e',
    'STOPPED_FOR_OTA=0',
    'write_progress 100 done "업데이트 완료"',
    'printf \'{"update_id":%s,"command_id":"%s","success":true,"target_version":"%s","message":"runtime update completed"}\\n\' "$UPDATE_ID" "$COMMAND_ID" "$TARGET_VERSION" >"$RESULT_FILE"',
    'trap - EXIT',
  ].join('\n');
  const cname = await spawnSiblingOp('apply-update', inner, {
    hostDir,
    rw: true,
    mountState: true,
  });
  return {
    message: `update ${targetVersion} scheduled in sibling ${cname}`,
    deferred: true,
    command_id: cmdId || null,
  };
}

/** @param {string[]} services empty = all services */
export async function dockerComposeRestart(services = []) {
  const extra = services.length ? ['restart', ...services] : ['restart'];
  const args = await composeArgs(extra);
  const { stdout, stderr } = await exec('docker', args, {
    cwd: COMPOSE_DIR,
    timeout: 180000,
    maxBuffer: 1024 * 512,
  });
  const msg = (stdout || stderr || 'restarted').trim();
  return { message: msg.slice(0, 800) || 'docker compose restart 완료' };
}

/**
 * 전체(agent 포함) restart — sibling 컨테이너에서 실행해 agent가 재기동돼도 끊기지 않는다.
 * agent가 restart 중 죽으므로 최종 결과는 state volume 파일 → agent heartbeat flush.
 * @param {string[]} services empty = all
 * @param {{ commandId?: string|null }} [opts]
 */
export async function dockerComposeRestartDeferred(services = [], { commandId = null } = {}) {
  const hostDir = await resolveHostRuntimeDir();
  const svcArg = services.length ? services.join(' ') : '';
  const cmdId = String(commandId || '').replace(/[^a-zA-Z0-9_-]/g, '');
  const resultFile = '/var/lib/whick/ops-deferred-result.json';
  const inner = [
    'set -e',
    'sleep 2',
    'echo "== restart start $(date -Iseconds) =="',
    `EF=""; [ -f "${hostDir}/.env" ] && EF="--env-file ${hostDir}/.env"`,
    `OF=""; [ -f "${hostDir}/compose.override.yaml" ] && OF="-f ${hostDir}/compose.override.yaml"`,
    `docker compose -p ${COMPOSE_PROJECT} -f "${hostDir}/compose.yaml" $OF $EF restart ${svcArg}`,
    'echo "== restart OK $(date -Iseconds) =="',
    cmdId
      ? `printf '%s\\n' '{"command_id":"${cmdId}","command_type":"full_docker_restart","success":true,"message":"컨테이너 재시작 완료","error_code":"","final":true}' > ${resultFile}`
      : 'true',
  ].join('\n');
  const cname = await spawnSiblingOp('restart', inner, { hostDir, mountState: true });
  const scope = services.length ? services.join(',') : 'all';
  return {
    message: `restart scheduled (${scope}) in sibling ${cname} — agent 재기동돼도 무중단 (docker logs ${cname})`,
    deferred: true,
    command_id: commandId || null,
  };
}

/** @param {string[]} [services] default agent+audio — monitor 등 통합관제 무관 */
export async function dockerComposeRebuild(services = CUSTOMER_RUNTIME_SERVICES) {
  const svcs = services?.length ? services : CUSTOMER_RUNTIME_SERVICES;
  const args = await composeArgs(['up', '-d', '--build', ...svcs]);
  const { stdout, stderr } = await exec('docker', args, {
    cwd: COMPOSE_DIR,
    timeout: 600000,
    maxBuffer: 1024 * 512,
  });
  const msg = (stdout || stderr || 'rebuild done').trim();
  return { message: msg.slice(0, 800) || 'docker compose up --build 완료' };
}

/** rebuild — sibling 컨테이너에서 build (실제 docker.sock → build 가능, agent 재기동 무관) */
export async function dockerComposeRebuildDeferred(services = CUSTOMER_RUNTIME_SERVICES) {
  const svcs = services?.length ? services : CUSTOMER_RUNTIME_SERVICES;
  const hostDir = await resolveHostRuntimeDir();
  const inner = [
    'set -e',
    'sleep 2',
    `echo "== rebuild start $(date -Iseconds) svcs=${svcs.join(',')} =="`,
    // 빌드 전(=지금 도는) 이미지를 기록 — cleanup 단계에서 anchor로 보존해 "직전 1개 버전"까지 남긴다.
    'PREV_IMAGE_IDS=""',
    `for cid in $(docker ps -aq --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" 2>/dev/null || true); do`,
    '  [ -z "$cid" ] && continue',
    '  docker inspect "$cid" >/dev/null 2>&1 || continue',
    '  iid=$(docker inspect --format "{{.Image}}" "$cid" 2>/dev/null) || continue',
    '  [ -z "$iid" ] && continue',
    '  docker image inspect "$iid" >/dev/null 2>&1 || continue',
    '  PREV_IMAGE_IDS="$PREV_IMAGE_IDS $iid"',
    'done',
    `EF=""; [ -f "${hostDir}/.env" ] && EF="--env-file ${hostDir}/.env"`,
    `OF=""; [ -f "${hostDir}/compose.override.yaml" ] && OF="-f ${hostDir}/compose.override.yaml"`,
    `docker compose -p ${COMPOSE_PROJECT} -f "${hostDir}/compose.yaml" $OF $EF up -d --build ${svcs.join(' ')}`,
    'set +e',
    'for c in $(docker ps -aq --filter "name=whick-keepimg-" 2>/dev/null || true); do',
    '  [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1',
    'done',
    'i=0',
    'for iid in $PREV_IMAGE_IDS; do',
    '  [ -z "$iid" ] && continue',
    '  docker image inspect "$iid" >/dev/null 2>&1 || continue',
    '  i=$((i+1))',
    '  docker rm -f "whick-keepimg-$i" >/dev/null 2>&1',
    '  docker create --name "whick-keepimg-$i" "$iid" >/dev/null 2>&1',
    'done',
    'docker image prune -af >/dev/null 2>&1',
    'docker builder prune -f >/dev/null 2>&1',
    'set -e',
    'echo "== rebuild OK $(date -Iseconds) =="',
  ].join('\n');
  const cname = await spawnSiblingOp('rebuild', inner, { hostDir, rw: true });
  return {
    message: `rebuild scheduled svcs=${svcs.join(',')} in sibling ${cname} (docker logs ${cname})`,
    deferred: true,
  };
}

function ccBaseUrl() {
  return (process.env.WHICK_CC_API_URL || '').replace(/\/api\/v1\/?$/, '');
}

function agentAuthHeaders() {
  const state = loadRuntimeState(process.env.WHICK_STATE_PATH || DEFAULT_STATE_PATH);
  const token = state?.token || process.env.WHICK_AGENT_TOKEN || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function avgInt(nums) {
  const v = nums.filter((n) => n != null && Number.isFinite(n));
  return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : null;
}

/** kbps → Mbps 정수 표시 (1000 기준, 화면 단위 m = Mbps) */
export function formatSpeedMbps(kbps) {
  if (kbps == null || !Number.isFinite(kbps)) return '—';
  const mbps = kbps / 1000;
  if (mbps <= 0) return '—';
  const n = Math.round(mbps);
  return `${n > 0 ? n : 1}m`;
}

/** 뮤직서버 입장: 본사로 업로드 / 본사에서 다운로드 / RTT
 *  TODO(상담 SSOT): docs/MUSIC-SERVER-NETWORK-TEST.md — 현재 256KB probe, speedtest와 동일 단위·정확도 아님 */
export function formatNetworkResult({ upload_kbps, download_kbps, latency_ms }) {
  const up = formatSpeedMbps(upload_kbps);
  const down = formatSpeedMbps(download_kbps);
  const lat = latency_ms != null ? `${latency_ms}ms` : '—';
  return `${up} : ${down} : ${lat}`;
}

/** 다운로드 1회 — body를 스트리밍으로 읽어 도착하는 만큼 즉시 카운트(느린 회선·중단도 정확) */
async function downloadTransfer(base, auth, addBytes) {
  const res = await fetch(`${base}/api/v1/agent/network-probe?size=${NET_DL_CHUNK}`, {
    headers: auth,
    cache: 'no-store',
    signal: AbortSignal.timeout(NET_TRANSFER_TIMEOUT_MS),
  });
  if (!res.ok || !res.body) {
    await res.arrayBuffer().catch(() => {});
    return;
  }
  const reader = res.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    addBytes(value?.byteLength || 0);
  }
}

/** 업로드 1회 — 전송 완료 시 chunk 크기를 카운트(정상상태에서 경계 오차는 상쇄) */
async function uploadTransfer(base, auth, addBytes) {
  const res = await fetch(`${base}/api/v1/agent/network-probe`, {
    method: 'POST',
    headers: { ...auth, 'Content-Type': 'application/octet-stream' },
    body: UPLOAD_BODY,
    cache: 'no-store',
    signal: AbortSignal.timeout(NET_TRANSFER_TIMEOUT_MS),
  });
  if (res.ok) addBytes(NET_UL_CHUNK);
  await res.text().catch(() => {});
}

/** CDN 다운로드 1회 — Cloudflare __down?bytes=N (인증 불필요, 스트리밍 카운트) */
async function cdnDownloadTransfer(addBytes) {
  const res = await fetch(`${SPEED_ENDPOINT}/__down?bytes=${SPEED_DL_CHUNK}`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(SPEED_TRANSFER_TIMEOUT_MS),
  });
  if (!res.ok || !res.body) {
    await res.arrayBuffer().catch(() => {});
    // 429 등에서 즉시 재시도 폭주 방지 — worker catch에서 대기
    const err = new Error(`cdn_down_http_${res.status}`);
    err.status = res.status;
    throw err;
  }
  const reader = res.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    addBytes(value?.byteLength || 0);
  }
}

/** CDN 업로드 1회 — Cloudflare __up.
 *  ReadableStream으로 송신 중 바이트를 집계(완료 후에만 카운트하면 측정창 레이스로 업=— 발생). */
async function cdnUploadTransfer(addBytes) {
  const src = speedUploadBody();
  const total = src.byteLength;
  const piece = 256 * 1024;
  let offset = 0;
  const stream = new ReadableStream({
    pull(controller) {
      if (offset >= total) {
        controller.close();
        return;
      }
      const end = Math.min(offset + piece, total);
      const slice = src.subarray(offset, end);
      offset = end;
      addBytes(slice.byteLength);
      controller.enqueue(slice);
    },
  });
  const res = await fetch(`${SPEED_ENDPOINT}/__up`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: stream,
    duplex: 'half',
    cache: 'no-store',
    signal: AbortSignal.timeout(SPEED_TRANSFER_TIMEOUT_MS),
  });
  await res.arrayBuffer().catch(() => {});
  if (!res.ok) {
    const err = new Error(`cdn_up_http_${res.status}`);
    err.status = res.status;
    throw err;
  }
}

/** 무부하 RTT — TLS 워밍업 1회 후 소수 샘플 중 최소값(≈ ping) */
async function measureCdnLatency() {
  try {
    await fetch(`${SPEED_ENDPOINT}/__down?bytes=0`, { cache: 'no-store', signal: AbortSignal.timeout(4000) });
  } catch {
    /* warmup */
  }
  const samples = [];
  for (let i = 0; i < SPEED_RTT_SAMPLES; i++) {
    const t0 = Date.now();
    try {
      const res = await fetch(`${SPEED_ENDPOINT}/__down?bytes=0`, {
        cache: 'no-store',
        signal: AbortSignal.timeout(4000),
      });
      await res.arrayBuffer().catch(() => {});
      if (res.ok) samples.push(Date.now() - t0);
    } catch {
      /* skip */
    }
  }
  return samples.length ? Math.min(...samples) : null;
}

/** 본사 관제서버 도달 여부만 가볍게 확인(헤드라인 지연과 별개) */
async function ccReachable(base) {
  let ok = 0;
  for (let i = 0; i < 2; i++) {
    try {
      const res = await fetch(`${base}/api/system/health`, { signal: AbortSignal.timeout(5000) });
      if (res.ok) ok++;
    } catch {
      /* skip */
    }
  }
  return ok > 0;
}

/**
 * 멀티스트림 sustained 처리량 측정 — warmup(slow-start) 구간을 버리고 정상상태만 집계.
 * @returns {Promise<{ kbps: number, bytes: number, ms: number }|null>}
 */
async function measureSustained({ doTransfer, parallel, warmupMs, measureMs, maxBytes, drainMs, pacingMs }) {
  const workerDrain = drainMs ?? NET_WORKER_DRAIN_MS;
  const pacing = pacingMs ?? NET_PACING_MS;
  let stop = false;
  let counting = false;
  let bytes = 0;
  let measureStart = 0;
  let lastProgress = 0;

  const addBytes = (n) => {
    // warmup 제외 · 측정창 + drain(진행 중 업로드 완료분)까지 집계
    if (!counting || !n || n <= 0) return;
    bytes += n;
    lastProgress = Date.now();
    if (bytes >= maxBytes) {
      counting = false;
      stop = true;
    }
  };

  async function worker() {
    while (!stop) {
      try {
        await doTransfer(addBytes);
      } catch (e) {
        if (stop) break;
        // Cloudflare 429 등 — 짧게 재폭주하지 않도록 대기
        const st = Number(e?.status) || 0;
        await sleep(st === 429 ? 800 : 120);
      }
      // HQ 보수 모드만 pacing. CDN 실측(pacingMs=0)은 2.5G 내장 랜에서 풀스피드 측정.
      if (!stop && pacing > 0) await sleep(pacing);
    }
  }

  const workers = Array.from({ length: parallel }, () => worker());
  await sleep(warmupMs);
  measureStart = Date.now();
  lastProgress = measureStart;
  counting = true;
  await sleep(measureMs);
  stop = true;
  await Promise.race([Promise.allSettled(workers), sleep(workerDrain)]);
  counting = false;

  const ms = Math.max(lastProgress - measureStart, 1);
  if (bytes <= 0) return null;
  return { kbps: Math.round((bytes * 8) / ms), bytes, ms };
}

/** 회선 속도·지연 측정. 기본 'cdn'(근거리 CDN 실측, NIA급 수치) / 'hq'(본사 처리량, 레거시) */
export async function runNetworkTest() {
  if (SPEED_MODE === 'cdn') return runCdnSpeedTest();
  return runHqThroughputTest();
}

/** CDN 실측 — 총 ≤10초 목표. 근거리 CDN 다중 스트림 → NIA급 회선속도 */
async function runCdnSpeedTest() {
  const t0 = Date.now();
  const base = ccBaseUrl();
  const speedOpts = {
    parallel: SPEED_PARALLEL,
    warmupMs: SPEED_WARMUP_MS,
    measureMs: SPEED_MEASURE_MS,
    maxBytes: SPEED_MAX_BYTES,
    drainMs: SPEED_DRAIN_MS,
    pacingMs: 0,
  };

  const latencyMs = await measureCdnLatency();

  const dl = await measureSustained({
    doTransfer: (add) => cdnDownloadTransfer(add),
    ...speedOpts,
  }).catch(() => null);
  await sleep(SPEED_GAP_MS);
  const ul = await measureSustained({
    doTransfer: (add) => cdnUploadTransfer(add),
    ...speedOpts,
  }).catch(() => null);

  const downloadKbps = dl?.kbps ?? null;
  const uploadKbps = ul?.kbps ?? null;
  const ccOk = base ? await ccReachable(base).catch(() => false) : false;

  const message =
    downloadKbps != null || uploadKbps != null
      ? formatNetworkResult({ upload_kbps: uploadKbps, download_kbps: downloadKbps, latency_ms: latencyMs })
      : '인터넷 측정 실패(CDN 도달 불가)';

  return {
    message,
    latency_ms: latencyMs,
    upload_kbps: uploadKbps,
    download_kbps: downloadKbps,
    method: 'cdn_speedtest',
    endpoint: SPEED_ENDPOINT.replace(/^https?:\/\//, ''),
    parallel: SPEED_PARALLEL,
    duration_ms: Date.now() - t0,
    download_bytes: dl?.bytes ?? 0,
    upload_bytes: ul?.bytes ?? 0,
    download_ms: dl?.ms ?? 0,
    upload_ms: ul?.ms ?? 0,
    cc_reachable: ccOk,
  };
}

/** 레거시 — 본사 관제서버로 측정(회선속도가 아닌 HQ 처리량). WHICK_SPEED_MODE=hq 일 때 사용 */
async function runHqThroughputTest() {
  const base = ccBaseUrl();
  if (!base) throw new Error('WHICK_CC_API_URL 없음');

  const rtts = [];
  for (let i = 0; i < NET_RTT_SAMPLES; i++) {
    const t0 = Date.now();
    try {
      const res = await fetch(`${base}/api/system/health`, { signal: AbortSignal.timeout(5000) });
      if (res.ok) rtts.push(Date.now() - t0);
    } catch {
      /* sample skip */
    }
  }

  const auth = agentAuthHeaders();
  let dl = null;
  let ul = null;

  if (auth.Authorization) {
    dl = await measureSustained({
      doTransfer: (add) => downloadTransfer(base, auth, add),
      parallel: NET_PARALLEL,
      warmupMs: NET_WARMUP_MS,
      measureMs: NET_MEASURE_MS,
      maxBytes: NET_MAX_BYTES,
    }).catch(() => null);
    await sleep(600);
    ul = await measureSustained({
      doTransfer: (add) => uploadTransfer(base, auth, add),
      parallel: NET_PARALLEL,
      warmupMs: NET_WARMUP_MS,
      measureMs: NET_MEASURE_MS,
      maxBytes: NET_MAX_BYTES,
    }).catch(() => null);
  }

  const latencyMs = avgInt(rtts);
  const downloadKbps = dl?.kbps ?? null;
  const uploadKbps = ul?.kbps ?? null;
  const ccOk = rtts.length >= 3;

  const message =
    ccOk || downloadKbps != null || uploadKbps != null
      ? formatNetworkResult({
          upload_kbps: uploadKbps,
          download_kbps: downloadKbps,
          latency_ms: latencyMs,
        })
      : '관제 서버 응답 없음';

  return {
    message,
    latency_ms: latencyMs,
    upload_kbps: uploadKbps,
    download_kbps: downloadKbps,
    method: 'sustained_v2',
    parallel: NET_PARALLEL,
    download_bytes: dl?.bytes ?? 0,
    upload_bytes: ul?.bytes ?? 0,
    download_ms: dl?.ms ?? 0,
    upload_ms: ul?.ms ?? 0,
    rtt_samples: rtts.length,
    cc_reachable: ccOk,
  };
}
