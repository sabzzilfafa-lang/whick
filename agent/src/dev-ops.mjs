import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { access } from 'node:fs/promises';
import dns from 'node:dns';
import path from 'node:path';
import os from 'node:os';
import { spawnSiblingOp } from './docker-ops.mjs';

const exec = promisify(execFile);
dns.setDefaultResultOrder('ipv4first');

/** agent 컨테이너 /tmp ≠ 호스트 /tmp — docker 로 쓰는 경로는 항상 호스트 기준 */
const HOST_TMP = process.env.WHICK_HOST_TMP || '/tmp';

const HTTPS_TAR =
  process.env.WHICK_HTTPS_TAR ||
  'https://whick.org/whick-content/customer/whick-3product-20260612-pullfix.tar.gz';
const EXEC_TIMEOUT_MS = Number(process.env.WHICK_DEV_EXEC_TIMEOUT_MS) || 600000;

const BLOCKED = [
  /\brm\s+-rf\s+\/\s/,
  /\bmkfs\b/,
  /\bdd\s+if=.*of=\/dev\//,
  /\bshutdown\b/,
  /\breboot\b/,
  /\bpoweroff\b/,
  // 통합관제·본사 인프라 — 고객 runtime 조작만 (docs/CUSTOMER-UPDATE-ISOLATION.md)
  /\bwhick-cc-/,
  /\b2_control_center\b/,
  /\/data\/whick-ai\b/,
  /\bdocker\s+(stop|rm|kill|compose\s+down)\b.*\b(whick-cc|cc-api|cc-web|cc-db)\b/,
  /\b(whick-cc-api|whick-cc-web|whick-cc-db)\b/,
  /\/data\/whick-ai\/2_control_center/,
];

async function resolveHostRuntimeDir() {
  const fromEnv = process.env.WHICK_HOST_RUNTIME_DIR?.trim();
  if (fromEnv) return fromEnv;
  for (const candidate of ['/opt/whick/runtime', path.join(os.homedir(), 'whick-3product')]) {
    try {
      await access(path.join(candidate, 'compose.yaml'));
      return candidate;
    } catch {
      /* try next */
    }
  }
  const { stdout } = await exec(
    'docker',
    [
      'inspect',
      'whick-agent',
      '--format',
      '{{range .Mounts}}{{if eq .Destination "/opt/whick/runtime"}}{{.Source}}{{end}}{{end}}',
    ],
    { timeout: 15000 },
  ).catch(() => ({ stdout: '' }));
  const dir = stdout.trim();
  if (dir && dir !== '.') return dir;
  return '/opt/whick/runtime';
}

/** HTTPS tar → 호스트 3_product → agent 재빌드 (SSH 불필요)
 *  agent가 자기 자신을 stop하면 스크립트도 죽으므로 분리된 sibling 컨테이너에서 실행한다.
 *  sibling은 실제 docker.sock으로 build·compose가 가능하고 agent 재기동과 독립적이다. (8GB RAM build 10~20분) */
export async function devPullUpdate() {
  const hostDir = await resolveHostRuntimeDir();
  const parent = path.dirname(hostDir);
  const tarPath = path.join(HOST_TMP, `whick-3product-${Date.now()}.tar.gz`);
  const url = `${HTTPS_TAR}${HTTPS_TAR.includes('?') ? '&' : '?'}v=${Date.now()}`;

  // sibling 컨테이너: parent(rw) + docker.sock 마운트. 다운로드→stop→교체→build.
  // curl은 nested 컨테이너(curlimages/curl)로 — agent 이미지에 curl이 없을 수 있다.
  const inner = [
    'set -e',
    'sleep 3',
    'echo "== dev_pull start $(date -Iseconds) =="',
    // 빌드/교체 전(=지금 도는) 이미지를 기록 — cleanup 단계에서 anchor로 보존해 "직전 1개 버전"까지 남긴다.
    'PREV_IMAGE_IDS=""',
    'for cid in $(docker ps -aq --filter "label=com.docker.compose.project=whick-runtime" 2>/dev/null || true); do',
    '  [ -z "$cid" ] && continue',
    '  docker inspect "$cid" >/dev/null 2>&1 || continue',
    '  iid=$(docker inspect --format "{{.Image}}" "$cid" 2>/dev/null) || continue',
    '  [ -z "$iid" ] && continue',
    '  docker image inspect "$iid" >/dev/null 2>&1 || continue',
    '  PREV_IMAGE_IDS="$PREV_IMAGE_IDS $iid"',
    'done',
    `docker run --rm -v ${HOST_TMP}:${HOST_TMP} curlimages/curl:8.5.0 curl -fSL4 --max-time 180 '${url}' -o '${tarPath}'`,
    `[ -f '${hostDir}/.env' ] && cp '${hostDir}/.env' '${HOST_TMP}/whick-env.bak' || true`,
    // 워치독 대기용 센티넬 — agent가 빌드 중 내려가도 워치독이 재시작/재부팅하지 않도록.
    `VOL=$(docker inspect whick-agent --format '{{range .Mounts}}{{if eq .Destination "/var/lib/whick"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)`,
    '[ -n "$VOL" ] && docker run --rm -v "$VOL:/var/lib/whick" ubuntu:26.04 sh -c "touch /var/lib/whick/.update-in-progress" 2>/dev/null || true',
    'docker stop whick-agent whick-audio whick-monitor whick-player whick-player-db 2>/dev/null || true',
    `rm -rf '${hostDir}' '${parent}/whick-3product'`,
    `mkdir -p '${parent}'`,
    `tar xzf '${tarPath}' -C '${parent}'`,
    `[ -d '${hostDir}' ] || mv '${parent}/whick-3product' '${hostDir}'`,
    `test -d '${hostDir}'`,
    `[ -f '${HOST_TMP}/whick-env.bak' ] && cp '${HOST_TMP}/whick-env.bak' '${hostDir}/.env' && rm -f '${HOST_TMP}/whick-env.bak' || true`,
    `[ ! -f '${hostDir}/.env' ] && [ -f '${hostDir}/.env.example' ] && cp '${hostDir}/.env.example' '${hostDir}/.env' || true`,
    `rm -f '${tarPath}'`,
    '[ -n "$VOL" ] && docker run --rm -v "$VOL:/var/lib/whick" ubuntu:26.04 rm -f /var/lib/whick/runtime-state.json 2>/dev/null || true',
    `OF=""; [ -f '${hostDir}/compose.override.yaml' ] && OF="-f '${hostDir}/compose.override.yaml'"`,
    `docker compose -p whick-runtime -f '${hostDir}/compose.yaml' $OF --env-file '${hostDir}/.env' up -d --build agent audio monitor player player-db`,
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
    // 빌드 완료 → 센티넬 해제 (실패 시엔 30분 후 자동 만료되어 워치독 재개)
    '[ -n "$VOL" ] && docker run --rm -v "$VOL:/var/lib/whick" ubuntu:26.04 rm -f /var/lib/whick/.update-in-progress 2>/dev/null || true',
    'echo "== dev_pull OK $(date -Iseconds) =="',
  ].join('\n');

  const cname = await spawnSiblingOp('devpull', inner, { hostDir: parent, rw: true });
  return {
    message: `dev_pull scheduled target=${hostDir} in sibling ${cname} (docker logs ${cname}, agent 재기동 10~20분)`,
    deferred: true,
  };
}

export async function hostReboot(delaySec = 30) {
  const delay = Math.max(10, Math.min(120, Number(delaySec) || 30));
  const dockerHost = process.env.DOCKER_HOST || 'tcp://127.0.0.1:2375';
  const cname = 'whick-selfop-host-reboot';
  await exec('docker', ['rm', '-f', cname], { timeout: 15000 }).catch(() => {});

  // --rm + nohup 백그라운드는 컨테이너 종료 시 작업이 죽을 수 있음 → detached sibling
  // /sbin/reboot(→systemctl)는 nsenter 환경에서 PID1에 SIGTERM만 보내고 실제 재부팅이 안 됨
  // (journal: "Received SIGTERM from PID … (reboot)" 후 uptime 유지). logind busctl 사용.
  const inner = [
    'set -e',
    'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux >/dev/null 2>&1 || true',
    `echo "== host reboot scheduled delay=${delay}s $(date -Iseconds) =="`,
    `sleep ${delay}`,
    // 구형 whick-host-reboot 는 /sbin/reboot→PID1 SIGTERM 만 보내서 재부팅이 안 됨. logind/sysrq 우선.
    'echo "== invoke logind Reboot =="',
    'if nsenter -t 1 -m -u -i -n -p busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager Reboot b false; then',
    '  echo "== logind Reboot accepted =="',
    '  sleep 90',
    'fi',
    'echo "== fallback systemctl start reboot.target =="',
    'nsenter -t 1 -m -u -i -n -p systemctl --no-block start reboot.target || true',
    'sleep 20',
    'echo "== fallback sysrq b =="',
    'nsenter -t 1 -m -u -i -n -p sh -c "echo 1 > /proc/sys/kernel/sysrq; echo b > /proc/sysrq-trigger"',
  ].join('\n');

  await exec(
    'docker',
    [
      'run',
      '-d',
      '--name',
      cname,
      '--privileged',
      '--pid=host',
      '-v',
      '/usr/local/sbin:/usr/local/sbin:ro',
      'ubuntu:26.04',
      'sh',
      '-c',
      inner,
    ],
    {
      timeout: 30000,
      env: {
        ...process.env,
        DOCKER_HOST: dockerHost,
        PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
      },
    },
  );

  return {
    message: `미니PC 재부팅 ${delay}초 후 예약됨 (${cname}) — 잠시 후 장비가 꺼졌다 켜집니다`,
    delay_sec: delay,
  };
}

/**
 * CC apply_power_policy — 기존 고객 장비에 24/7 전원 정책 적용.
 * 고정된 정책만 실행하며 임의 shell 입력은 받지 않는다.
 */
export async function applyHostPowerPolicy() {
  const dockerHost = process.env.DOCKER_HOST || 'tcp://127.0.0.1:2375';
  const script = String.raw`
set -eu
mkdir -p /etc/systemd/logind.conf.d /etc/systemd/sleep.conf.d /etc/systemd/system
cat >/etc/systemd/logind.conf.d/99-whick-no-suspend.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
IdleActionSec=0
EOF
cat >/etc/systemd/sleep.conf.d/99-whick-disable-sleep.conf <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowHybridSleep=no
AllowSuspendThenHibernate=no
EOF
for target in sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target; do
  ln -sfn /dev/null "/etc/systemd/system/$target"
done
mkdir -p /etc/modprobe.d /etc/udev/rules.d
cat >/etc/modprobe.d/whick-usb-no-autosuspend.conf <<'EOF'
options usbcore autosuspend=-1
EOF
cat >/etc/udev/rules.d/99-whick-usb-no-autosuspend.rules <<'EOF'
ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"
EOF
echo -1 >/sys/module/usbcore/parameters/autosuspend 2>/dev/null || true
systemctl daemon-reload >/dev/null 2>&1 || true
busctl call org.freedesktop.login1 /org/freedesktop/login1 \
  org.freedesktop.login1.Manager ReloadConfiguration >/dev/null 2>&1 || true
udevadm control --reload-rules >/dev/null 2>&1 || true
printf 'power_policy=applied\n'
systemd-analyze cat-config systemd/logind.conf 2>/dev/null \
  | awk '/^(HandlePowerKey|HandleSuspendKey|HandleHibernateKey|HandleLidSwitch|IdleAction)=/{print}' \
  | sort -u || true
`;
  const { stdout, stderr } = await exec(
    'docker',
    [
      'run',
      '--rm',
      '--privileged',
      '--pid=host',
      '-v',
      '/:/host',
      'ubuntu:26.04',
      'chroot',
      '/host',
      'sh',
      '-lc',
      script,
    ],
    {
      timeout: 60000,
      env: {
        ...process.env,
        DOCKER_HOST: dockerHost,
        PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
      },
      maxBuffer: 1024 * 1024,
    },
  );
  return {
    message: `host power policy applied: ${String(stdout || '').trim()}`,
    stderr: String(stderr || '').trim(),
  };
}

/** system_reinstall — rescue 파티션 확인 후 GRUB one-time-boot + 실제 재부팅 */
export async function rescueReboot({ commandId = null } = {}) {
  const helper = '/usr/local/sbin/whick-rescue-reboot';
  const dockerHost = process.env.DOCKER_HOST || 'tcp://127.0.0.1:2375';
  const cmdId = String(commandId || '');
  const resultFile = '/var/lib/whick/reinstall-result.json';

  // 1) preflight — rescue 파티션·헬퍼 존재 (실패 시 명확히 보고)
  try {
    const { stdout } = await exec(
      'docker',
      [
        'run',
        '--rm',
        '--privileged',
        '-v',
        '/dev:/dev',
        '-v',
        '/usr/local/sbin:/usr/local/sbin:ro',
        'ubuntu:26.04',
        'sh',
        '-c',
        [
          'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux >/dev/null 2>&1 || true',
          'test -x /usr/local/sbin/whick-rescue-reboot || { echo "missing helper"; exit 3; }',
          'DEV=$(blkid -L whick-rescue -o device 2>/dev/null || true)',
          'test -n "$DEV" || { echo "rescue partition not found"; exit 2; }',
          'echo "OK $DEV"',
        ].join('; '),
      ],
      {
        timeout: 45000,
        env: {
          ...process.env,
          DOCKER_HOST: dockerHost,
          PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        },
      },
    );
    if (!String(stdout || '').includes('OK')) {
      throw new Error(String(stdout || '').trim() || 'rescue preflight failed');
    }
  } catch (e) {
    // docker가 ubuntu:26.04을 로컬에 못 찾으면 pull 진행 로그가 stderr로 나가
    // 실제 스크립트 echo(진단 메시지)가 담긴 stdout을 가려버린다 — stdout을 우선 확인한다.
    const stdoutMsg = String(e?.stdout || '').trim();
    const msg = stdoutMsg || String(e?.stderr || e?.message || e);
    if (/exit code 2|rescue partition not found/i.test(msg)) {
      throw new Error(
        'rescue 파티션(whick-rescue)이 없어 시스템 전체 재설치를 할 수 없습니다. USB/공장 이미지로 설치한 장비만 지원합니다.',
      );
    }
    if (/exit code 3|missing helper/i.test(msg)) {
      throw new Error('호스트에 whick-rescue-reboot 헬퍼가 없습니다. 시스템 재설치를 지원하지 않는 이미지입니다.');
    }
    throw new Error(`시스템 재설치 preflight 실패: ${msg.slice(0, 300)}`);
  }

  // 2) 재부팅 예약 — sibling이 실제 헬퍼를 포그라운드로 실행 (nohup+--rm 백그라운드 버그 수정)
  //    agent는 결과 보고 후 곧 끊기므로 deferred로 두고, 재기동 후 result 파일/하트비트로 최종 확인
  const pending = {
    command_id: cmdId,
    command_type: 'system_reinstall',
    phase: 'rebooting',
    started_at: new Date().toISOString(),
  };
  try {
    const { writeFile, mkdir } = await import('node:fs/promises');
    await mkdir('/var/lib/whick', { recursive: true });
    await writeFile('/var/lib/whick/system-reinstall-pending.json', JSON.stringify(pending), 'utf8');
  } catch {
    /* best-effort */
  }

  await exec(
    'docker',
    [
      'run',
      '-d',
      '--name',
      'whick-selfop-system-reinstall',
      '--pid=host',
      '--privileged',
      '-v',
      '/usr/local/sbin:/usr/local/sbin:ro',
      '-v',
      '/dev:/dev',
      '-v',
      '/sys:/sys',
      '-v',
      '/boot:/boot',
      '-v',
      '/etc/default:/etc/default',
      '-v',
      '/var/lib/whick:/var/lib/whick',
      'ubuntu:26.04',
      'sh',
      '-c',
      [
        'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux bash >/dev/null 2>&1 || true',
        'sleep 8',
        'sh /usr/local/sbin/whick-rescue-reboot',
        `printf '%s\\n' '{"command_id":"${cmdId.replace(/"/g, '')}","command_type":"system_reinstall","success":false,"message":"rescue reboot helper returned without reboot","error_code":"REBOOT_NOT_TRIGGERED","final":true}' > ${resultFile}`,
      ].join('; '),
    ],
    {
      timeout: 30000,
      env: {
        ...process.env,
        DOCKER_HOST: dockerHost,
        PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
      },
    },
  ).catch(async () => {
    // name conflict — remove and retry once
    await exec('docker', ['rm', '-f', 'whick-selfop-system-reinstall'], { timeout: 15000 }).catch(() => {});
    await exec(
      'docker',
      [
        'run',
        '-d',
        '--name',
        'whick-selfop-system-reinstall',
        '--pid=host',
        '--privileged',
        '-v',
        '/usr/local/sbin:/usr/local/sbin:ro',
        '-v',
        '/dev:/dev',
        '-v',
        '/sys:/sys',
        '-v',
        '/boot:/boot',
        '-v',
        '/etc/default:/etc/default',
        '-v',
        '/var/lib/whick:/var/lib/whick',
        'ubuntu:26.04',
        'sh',
        '-c',
        [
          'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux bash >/dev/null 2>&1 || true',
          'sleep 8',
          'sh /usr/local/sbin/whick-rescue-reboot',
        ].join('; '),
      ],
      {
        timeout: 30000,
        env: {
          ...process.env,
          DOCKER_HOST: dockerHost,
          PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        },
      },
    );
  });

  return {
    message: '시스템 재설치 — rescue 파티션으로 재부팅을 시작합니다',
    deferred: true,
    final: false,
    command_id: cmdId || null,
  };
}

export async function devExec(command) {
  const cmd = String(command || '').trim();
  if (!cmd) throw new Error('command required');
  if (cmd.length > 4000) throw new Error('command too long');
  for (const re of BLOCKED) {
    if (re.test(cmd)) throw new Error('blocked command pattern');
  }

  const { stdout, stderr } = await exec('sh', ['-lc', cmd], {
    timeout: EXEC_TIMEOUT_MS,
    maxBuffer: 1024 * 512,
    cwd: process.env.WHICK_COMPOSE_DIR || '/opt/whick/runtime',
    env: { ...process.env, PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' },
  });
  const out = [stdout, stderr].filter(Boolean).join('\n').trim();
  return { message: out.slice(0, 2000) || 'ok (no output)' };
}
