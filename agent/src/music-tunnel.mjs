import { spawnSiblingOp, waitSiblingOp, resolveHostRuntimeDir } from './docker-ops.mjs';
import { writeFile, mkdir } from 'node:fs/promises';

function shQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function b64(value) {
  return Buffer.from(String(value || ''), 'utf8').toString('base64');
}

function safeFileName(name) {
  const s = String(name || '').trim();
  if (!/^[0-9a-f-]{36}\.json$/i.test(s)) throw new Error(`invalid credential filename: ${name}`);
  return s;
}

function composeTunnelOverride() {
  return `# 리모컨 외부·LTE named tunnel — CC 자동 발급 번들
services:
  tunnel:
    image: cloudflare/cloudflared:2026.6.1
    container_name: whick-tunnel
    restart: unless-stopped
    command: ['tunnel', '--no-autoupdate', '--config', '/etc/cloudflared/config.yml', 'run']
    volumes:
      - ./tunnel:/etc/cloudflared:rw
    networks: [whick_net]
    depends_on:
      - player
`;
}

function writeBase64(path, contentB64) {
  return `printf %s ${shQuote(contentB64)} | base64 -d > ${shQuote(path)}`;
}

// main.mjs의 내부 재시도 타이머(tickMusicTunnel)와 CC music_tunnel_apply 명령이
// 동시에 들어오면 둘 다 spawnSiblingOp('music-tunnel', ...)를 호출한다.
// spawnSiblingOp는 시작 시 동일 이름 컨테이너를 `docker rm -f`로 먼저 지우므로,
// 겹치면 먼저 뜬 쪽이 SIGKILL(exit 137)로 죽는다. 호출 경로가 둘이어도 실제 적용은
// 하나만 돌게 in-flight promise를 공유해 레이스를 막는다.
let _inflightApply = null;

export function ensureMusicTunnel(cc) {
  if (_inflightApply) return _inflightApply;
  _inflightApply = ensureMusicTunnelOnce(cc).finally(() => {
    _inflightApply = null;
  });
  return _inflightApply;
}

/**
 * 터널 번들 적용 — sibling 완료까지 기다린 뒤 final 보고.
 * (구버전: deferred만 보고하고 sibling 종료를 안 기다려 verify가 35%에 영구 정지했음)
 */
async function ensureMusicTunnelOnce(cc) {
  const bundle = await cc.get('/agent/music-tunnel/bundle');
  if (!bundle?.available) {
    throw new Error(bundle?.reason || 'music tunnel not ready');
  }
  if (!bundle.config_yml_b64 || !Array.isArray(bundle.credentials) || !bundle.credentials.length) {
    throw new Error('music tunnel bundle incomplete');
  }

  const hostDir = await resolveHostRuntimeDir();
  const tunnelDir = `${hostDir}/tunnel`;
  const lines = [
    'set -e',
    `HOST_DIR=${shQuote(hostDir)}`,
    `TUNNEL_DIR=${shQuote(tunnelDir)}`,
    'mkdir -p "$TUNNEL_DIR"',
    writeBase64(`${tunnelDir}/config.yml`, bundle.config_yml_b64),
  ];

  for (const cred of bundle.credentials) {
    lines.push(writeBase64(`${tunnelDir}/${safeFileName(cred.name)}`, cred.content_b64));
  }

  if (bundle.device_token) {
    lines.push(`printf '%s\n' ${shQuote(bundle.device_token)} > "$TUNNEL_DIR/device-token"`);
    lines.push('touch "$HOST_DIR/.env"');
    lines.push(`if grep -q '^WHICK_PLAYER_DEVICE_TOKEN=' "$HOST_DIR/.env"; then sed -i 's|^WHICK_PLAYER_DEVICE_TOKEN=.*|WHICK_PLAYER_DEVICE_TOKEN=${bundle.device_token}|' "$HOST_DIR/.env"; else printf '%s\n' ${shQuote(`WHICK_PLAYER_DEVICE_TOKEN=${bundle.device_token}`)} >> "$HOST_DIR/.env"; fi`);
    lines.push(`if grep -q '^WHICK_PLAYER_AUTH_REQUIRED=' "$HOST_DIR/.env"; then sed -i 's|^WHICK_PLAYER_AUTH_REQUIRED=.*|WHICK_PLAYER_AUTH_REQUIRED=1|' "$HOST_DIR/.env"; else printf '%s\n' 'WHICK_PLAYER_AUTH_REQUIRED=1' >> "$HOST_DIR/.env"; fi`);

    // Write token to shared volume (whick-data:/var/lib/whick) so the running player
    // container picks it up immediately without needing a restart.
    // load_device_token() in music_api.py checks env var first, then /var/lib/whick/remote-device-token.
    try {
      await mkdir('/var/lib/whick', { recursive: true });
      await writeFile('/var/lib/whick/remote-device-token', bundle.device_token + '\n', 'utf8');
    } catch {
      /* non-fatal — sibling op will also write via .env + --force-recreate */
    }
  }

  lines.push(writeBase64(`${hostDir}/compose.tunnel.override.yaml`, b64(composeTunnelOverride())));
  // cloudflared 이미지는 nonroot(65532)로 실행 — credential/config은 컨테이너에서 읽혀야 한다.
  // device 전용 runtime 디렉터리 내부 파일이므로 0644 노출은 허용 범위. (600이면 permission denied 크래시 루프)
  lines.push('chmod 644 "$TUNNEL_DIR"/*.json "$TUNNEL_DIR/config.yml" 2>/dev/null || true');
  lines.push('chmod 644 "$TUNNEL_DIR/device-token" 2>/dev/null || true');
  lines.push('EF=""; [ -f "$HOST_DIR/.env" ] && EF="--env-file $HOST_DIR/.env"');
  lines.push('OF=""');
  lines.push('[ -f "$HOST_DIR/compose.override.yaml" ] && OF="$OF -f $HOST_DIR/compose.override.yaml"');
  lines.push('[ -f "$HOST_DIR/compose.music-data.override.yaml" ] && OF="$OF -f $HOST_DIR/compose.music-data.override.yaml"');
  lines.push('[ -f "$HOST_DIR/compose.tunnel.override.yaml" ] && OF="$OF -f $HOST_DIR/compose.tunnel.override.yaml"');
  // Token은 /var/lib/whick/remote-device-token + .env 로 이미 반영됨.
  // player까지 --force-recreate 하면 설치 검증 직후 MPD/ALSA 레이스(:6600 EADDRINUSE)의 주원인이 된다.
  // tunnel만 recreate하고, player는 기동만 보장한 뒤 /health mpd=true 를 기다린다.
  lines.push('echo "[music-tunnel] applying tunnel bundle — recreate tunnel only (keep player)"');
  lines.push('docker compose -p whick-runtime -f "$HOST_DIR/compose.yaml" $OF $EF up -d --force-recreate tunnel');
  lines.push('docker compose -p whick-runtime -f "$HOST_DIR/compose.yaml" $OF $EF up -d player');
  lines.push('echo "[music-tunnel] waiting for player MPD ready…"');
  // player /health 는 mpc+DAC probe로 약 3초 걸림 — wget --timeout=2 면
  // 본문이 비어 나와 90회 재시도해도 항상 exit 1 이었다.
  // --tries=1: busybox wget 기본 재시도(백오프)로 sibling 이 수분 더 늘어나는 것 방지.
  lines.push('ok=0; for i in $(seq 1 60); do');
  lines.push('  h=$(wget -qO- --timeout=8 --tries=1 http://127.0.0.1:8080/health 2>/dev/null || true)');
  lines.push('  if printf %s "$h" | grep -q \'"mpd":true\'; then ok=1; break; fi');
  lines.push('  sleep 2');
  lines.push('done');
  lines.push('if [ "$ok" != 1 ]; then echo "[music-tunnel] player mpd not ready: $h" >&2; exit 1; fi');
  lines.push('echo "[music-tunnel] player health: $h"');
  if (bundle.tunnel_host) {
    lines.push(`echo "music tunnel active: ${bundle.tunnel_host}"`);
  }

  // sibling이 기본 bridge 네트워크면 host에 published된 127.0.0.1:8080(player /health)에
  // 닿지 않아 mpd-ready 대기가 항상 90초 타임아웃(exit 1)으로 끝난다 — host network 필요.
  const cname = await spawnSiblingOp('music-tunnel', lines.join('\n'), {
    hostDir,
    rw: true,
    network: 'host',
  });
  const exitCode = await waitSiblingOp(cname, { timeoutMs: 300_000 });
  if (exitCode !== 0) {
    throw new Error(`music tunnel apply failed in sibling ${cname} (exit ${exitCode})`);
  }

  if (bundle.tunnel_host) {
    // Extract tunnel_id from credential filename: {uuid}.json
    const tunnelId = bundle.credentials?.[0]?.name?.replace(/\.json$/i, '') || '';
    await cc.post('/agent/music-tunnel', {
      type: 'music_tunnel',
      payload: {
        host: bundle.tunnel_host,
        tunnel_id: tunnelId,
        tunnel_type: 'cloudflared-named',
        source: 'agent_bundle_pull',
      },
    });
  }
  return {
    available: true,
    deferred: false,
    final: true,
    tunnel_host: bundle.tunnel_host || null,
    message: bundle.tunnel_host
      ? `music tunnel active: ${bundle.tunnel_host}`
      : 'music tunnel applied',
  };
}
