/** 단계적 복구용 진단·안전 청소 · 결과는 2000자 요약 고정 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const exec = promisify(execFile);
const OUT_LIMIT = 1900;

/** agent 컨테이너 내부 (Alpine · docker CLI) */
async function sh(cmd, timeoutMs = 45000) {
  try {
    const { stdout, stderr } = await exec('sh', ['-lc', cmd], {
      timeout: timeoutMs,
      maxBuffer: 1024 * 256,
      env: { ...process.env, PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' },
    });
    return [stdout, stderr].filter(Boolean).join('\n').trim();
  } catch (e) {
    const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim();
    return out || String(e);
  }
}

/**
 * 호스트 PID1 네임스페이스에서 실행 (apt/df/journalctl 등 — agent는 Alpine)
 */
async function hostSh(cmd, timeoutMs = 60000) {
  const dockerHost = process.env.DOCKER_HOST || 'tcp://127.0.0.1:2375';
  const quoted = JSON.stringify(String(cmd || ''));
  const inner = [
    'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux >/dev/null 2>&1 || true',
    `nsenter -t 1 -m -u -i -n -p sh -lc ${quoted}`,
  ].join('; ');
  try {
    const { stdout, stderr } = await exec(
      'docker',
      ['run', '--rm', '--privileged', '--pid=host', 'ubuntu:26.04', 'sh', '-c', inner],
      {
        timeout: Math.max(30000, timeoutMs + 20000),
        maxBuffer: 1024 * 256,
        env: {
          ...process.env,
          DOCKER_HOST: dockerHost,
          PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        },
      },
    );
    return [stdout, stderr].filter(Boolean).join('\n').trim();
  } catch (e) {
    const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim();
    return out || String(e);
  }
}

function summarize(title, body) {
  const text = `== ${title} ==\n${String(body || '').trim()}`.slice(0, OUT_LIMIT);
  return { message: text || `${title}: (no output)`, ok: true };
}

/** df 요약 — 시스템(/) · /mnt/music · inode (호스트) */
export async function diagnoseDisk() {
  const df = await hostSh(
    "df -hT / /mnt/music /var/lib/docker 2>/dev/null | awk 'NR==1 || /\\/mnt\\/music|^\\/dev|overlay|tmpfs/' ; echo '---'; df -i / /mnt/music 2>/dev/null | head -6",
    20000,
  );
  const du = await hostSh(
    'du -sh /var/log /var/cache/apt /var/lib/docker 2>/dev/null | head -20',
    30000,
  );
  return summarize('diagnose_disk', `${df}\n---\n${du}`);
}

/** apt 상태 요약 — 호스트 apt (agent Alpine에 apt 없음). update·시뮬레이션만 */
export async function diagnoseApt() {
  const parts = [];
  parts.push(
    await hostSh(
      'command -v apt-get >/dev/null && apt-get --version | head -1 || echo apt:missing-on-host',
      15000,
    ),
  );
  parts.push(
    await hostSh(
      'timeout 90 apt-get update -qq 2>&1 | tail -20; echo EXIT:$?',
      100000,
    ),
  );
  parts.push(
    await hostSh(
      "apt-get -s upgrade 2>/dev/null | awk '/^Inst |^Remv |upgraded|newly installed|to remove|not upgraded/{print}' | head -40",
      60000,
    ),
  );
  parts.push(
    await hostSh(
      'dpkg -l docker-ce docker-ce-cli containerd.io 2>/dev/null | tail -10 || true',
      15000,
    ),
  );
  return summarize('diagnose_apt', parts.join('\n---\n'));
}

/** Docker 서비스·컨테이너 요약
 *  docker info 는 socket-proxy(403)로 막히는 경우가 많아 version+ps 집계 사용
 */
export async function diagnoseDocker() {
  const parts = [];
  // proxy 허용 API만 — info 금지
  parts.push(
    await sh(
      [
        'echo -n "Client: "; docker version --format "{{.Client.Version}}" 2>/dev/null || echo n/a',
        'echo -n "Server: "; docker version --format "{{.Server.Version}}" 2>/dev/null || echo n/a',
        'UP=$(docker ps -q 2>/dev/null | wc -l | tr -d " ")',
        'ALL=$(docker ps -aq 2>/dev/null | wc -l | tr -d " ")',
        'echo "Containers: up=$UP all=$ALL"',
      ].join('; '),
      25000,
    ),
  );
  parts.push(
    await hostSh(
      'echo -n "docker.service: "; (/bin/systemctl is-active docker || /usr/bin/systemctl is-active docker || echo unknown) 2>&1; echo -n "containerd.service: "; (/bin/systemctl is-active containerd || /usr/bin/systemctl is-active containerd || echo unknown) 2>&1',
      20000,
    ),
  );
  parts.push(
    await sh(
      'timeout 20 docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>&1 | head -40',
      25000,
    ),
  );
  return summarize('diagnose_docker', parts.join('\n---\n'));
}

/**
 * 시스템 디스크 안전 청소 — 음악 라이브러리(/mnt/music) 삭제 금지
 * 로그·apt 캐시·미사용 docker 이미지/컨테이너만
 * (builder prune 제외 — 고객기 로컬 빌드 없음 · agent proxy에서 403)
 */
export async function diskCleanupSafe() {
  const steps = [];
  steps.push([
    'journal',
    await hostSh('journalctl --vacuum-size=200M 2>&1 | tail -5 || echo skip', 60000),
  ]);
  steps.push([
    'apt-cache',
    await hostSh(
      'apt-get clean 2>&1 | tail -3; du -sh /var/cache/apt 2>/dev/null || true',
      60000,
    ),
  ]);
  steps.push([
    'docker-prune',
    await sh(
      'docker image prune -f 2>&1 | tail -8; docker container prune -f 2>&1 | tail -5',
      120000,
    ),
  ]);
  steps.push(['df-after', await hostSh('df -h / /var/lib/docker 2>/dev/null | head -6', 15000)]);
  const body = steps.map(([k, v]) => `[${k}]\n${v}`).join('\n---\n');
  return summarize('disk_cleanup', body);
}

/** 진단 로그 묶음 — AI 수동조치용 (+ Docker 재설치 실패 로그 보강) */
export async function collectDiagLogs() {
  const parts = [];
  parts.push(await hostSh('date -Iseconds; uptime; free -h | head -3', 10000));
  parts.push(await hostSh('df -h / /mnt/music 2>/dev/null | head -8', 10000));
  parts.push(
    await sh(
      'docker ps -a --format "{{.Names}} {{.Status}}" 2>&1 | head -20',
      20000,
    ),
  );
  parts.push(
    await sh(
      'docker logs --tail 40 whick-agent 2>&1 | tail -40; echo ---; docker logs --tail 30 whick-player 2>&1 | tail -30',
      30000,
    ),
  );
  // runtime_reinstall 실패 시 state volume에 남는 로그/진행률 (원인 파악 보강)
  parts.push(
    await sh(
      [
        'echo "== reinstall-progress =="',
        'if [ -f /var/lib/whick/reinstall-progress.json ]; then cat /var/lib/whick/reinstall-progress.json; else echo "(none)"; fi',
        'echo "== reinstall-result =="',
        'if [ -f /var/lib/whick/reinstall-result.json ]; then cat /var/lib/whick/reinstall-result.json; else echo "(none)"; fi',
        'echo "== reinstall-last.log (tail 400) =="',
        'if [ -f /var/lib/whick/reinstall-last.log ]; then',
        '  wc -c /var/lib/whick/reinstall-last.log; tail -n 400 /var/lib/whick/reinstall-last.log',
        'else echo "(none)"; fi',
      ].join('; '),
      20000,
    ),
  );
  return summarize('collect_diag_logs', parts.join('\n---\n'));
}

/**
 * Docker daemon(systemctl) 재시작 — agent도 죽으므로 privileged sibling deferred.
 * daemon 재시작 시 sibling이 SIGTERM(143)으로 죽어서 OK 로그/결과 보고가 불가 →
 * 재시작 직전에 state volume에 최종 결과 파일을 남겨 agent 기동 후 flush.
 */
export async function dockerServiceRestartDeferred({ commandId = null } = {}) {
  const cmdId = String(commandId || '').replace(/[^a-zA-Z0-9_-]/g, '');
  const cname = 'whick-selfop-docker-svc-restart';
  await exec('docker', ['rm', '-f', cname], { timeout: 20000 }).catch(() => {});
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
  const resultFile = '/var/lib/whick/ops-deferred-result.json';
  const inner = [
    'set -e',
    'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux >/dev/null 2>&1 || true',
    'sleep 3',
    'echo "== docker_service_restart start $(date -Iseconds) =="',
    // docker 재시작으로 이 컨테이너가 죽기 전에 결과 파일 기록 (agent 기동 후 flush)
    `printf '%s\\n' '{"command_id":"${cmdId}","command_type":"docker_service_restart","success":true,"message":"Docker 서비스 재시작 완료","error_code":"","final":true}' > ${resultFile}`,
    'nsenter -t 1 -m -u -i -n -p systemctl restart docker',
    'echo "== docker_service_restart OK $(date -Iseconds) =="',
  ].join('\n');
  const args = [
    'run',
    '-d',
    '--name',
    cname,
    '--privileged',
    '--pid=host',
    '-v',
    `${stateSource}:/var/lib/whick`,
    'ubuntu:26.04',
    'sh',
    '-c',
    inner,
  ];
  await exec('docker', args, {
    timeout: 30000,
    env: {
      ...process.env,
      DOCKER_HOST: process.env.DOCKER_HOST || 'tcp://127.0.0.1:2375',
      PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
    },
  });
  return {
    message: `docker service restart scheduled in sibling ${cname}${cmdId ? ` cmd=${cmdId}` : ''}`,
    deferred: true,
    command_id: commandId || null,
  };
}
