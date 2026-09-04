/**
 * 런타임 컴포넌트 버전 수집 — Docker 이미지·컨테이너·패키지 버전을 heartbeat·update 보고용으로 취합
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { access } from 'node:fs/promises';
import path from 'node:path';

const exec = promisify(execFile);

const COMPOSE_DIR = process.env.WHICK_COMPOSE_DIR || '/opt/whick/runtime';
const COMPOSE_FILE = process.env.WHICK_COMPOSE_FILE || path.join(COMPOSE_DIR, 'compose.yaml');
const COMPOSE_PROJECT = process.env.WHICK_COMPOSE_PROJECT || 'whick-runtime';
const COMPONENTS_MANIFEST_PATH =
  process.env.WHICK_COMPONENTS_MANIFEST_PATH || path.join(COMPOSE_DIR, 'components.json');
const COMPONENTS_LOCK_PATH =
  process.env.WHICK_COMPONENTS_LOCK_PATH || path.join(COMPOSE_DIR, 'components.lock.json');

/** Docker 이미지 목록 — docker compose images */
export async function collectDockerImageVersions() {
  try {
    const { stdout } = await exec(
      'docker',
      ['compose', '-p', COMPOSE_PROJECT, '-f', COMPOSE_FILE, 'images', '--format', '{{.Repository}}\t{{.Tag}}\t{{.ID}}'],
      { timeout: 15000, cwd: COMPOSE_DIR },
    );
    const images = {};
    const lines = String(stdout).trim().split('\n');
    for (const line of lines) {
      const parts = line.split('\t');
      const repo = parts[0]?.trim();
      const tag = parts[1]?.trim();
      const id = parts[2]?.trim();
      if (!repo || !tag) continue;
      images[repo] = { tag, id: id || null };
    }
    return images;
  } catch (e) {
    console.warn('[components] docker images collect failed:', e.message);
    return {};
  }
}

/** 컨테이너별 digest — docker inspect */
export async function collectDockerDigests() {
  try {
    const { stdout } = await exec(
      'docker',
      ['compose', '-p', COMPOSE_PROJECT, '-f', COMPOSE_FILE, 'ps', '-q'],
      { timeout: 10000, cwd: COMPOSE_DIR },
    );
    const ids = String(stdout).trim().split('\n').map((l) => l.trim()).filter(Boolean);
    if (!ids.length) return {};

    const { stdout: inspectOut } = await exec(
      'docker',
      ['inspect', '--format', '{{.Name}}\t{{ index .Config.Labels "image.digest" }}', ...ids],
      { timeout: 10000 },
    );
    const digests = {};
    const lines = String(inspectOut).trim().split('\n');
    for (const line of lines) {
      const [name, digest] = line.split('\t');
      if (name && digest) {
        const shortName = name.startsWith('/') ? name.slice(1) : name;
        digests[shortName.replace(`${COMPOSE_PROJECT}-`, '')] = digest.trim();
      }
    }
    return digests;
  } catch (e) {
    console.warn('[components] docker digests collect failed:', e.message);
    return {};
  }
}

/** Docker 엔진·containerd·docker-compose 버전 */
export async function collectDockerEngineVersion() {
  try {
    const { stdout } = await exec('docker', ['version', '--format', '{{.Server.Version}}'], { timeout: 10000 });
    const server = String(stdout).trim();

    let compose = '';
    try {
      const { stdout: co } = await exec('docker', ['compose', 'version', '--short'], { timeout: 10000 });
      compose = String(co).trim();
    } catch {
      compose = '';
    }

    return { server, compose: compose || null };
  } catch (e) {
    console.warn('[components] docker engine version failed:', e.message);
    return { server: null, compose: null };
  }
}

function parseOsRelease(text) {
  const osInfo = {};
  for (const line of String(text || '').trim().split('\n')) {
    const m = line.match(/^(\w+)=["']?(.+?)["']?$/);
    if (m) osInfo[m[1].toLowerCase()] = m[2];
  }
  return osInfo;
}

/** 호스트 OS 문자열 — agent 컨테이너(Alpine) /etc/os-release 가 아닌 실제 호스트 우선 */
async function readHostOsReleaseText() {
  const tries = [
    ['cat', ['/host/etc/os-release']],
    ['cat', ['/proc/1/root/etc/os-release']],
    [
      'docker',
      ['run', '--rm', '-v', '/etc/os-release:/os-release:ro', 'ubuntu:26.04', 'cat', '/os-release'],
    ],
    ['cat', ['/etc/os-release']],
  ];
  for (const [cmd, args] of tries) {
    try {
      const { stdout } = await exec(cmd, args, { timeout: 8000 });
      const text = String(stdout || '').trim();
      if (!text) continue;
      // 컨테이너 Alpine 이면 다음 후보로 (마지막 /etc/os-release 만 허용)
      if (/ID=alpine/i.test(text) && args[0] !== '/etc/os-release') continue;
      return text;
    } catch {
      /* next */
    }
  }
  return '';
}

/** 호스트 OS/커널·아키텍처 */
export async function collectHostInfo() {
  try {
    const osRel = await readHostOsReleaseText();
    const osInfo = parseOsRelease(osRel);

    const { stdout: kernel } = await exec('uname', ['-r'], { timeout: 3000 }).catch(() => ({ stdout: '' }));
    const { stdout: arch } = await exec('uname', ['-m'], { timeout: 3000 }).catch(() => ({ stdout: '' }));

    return {
      os: osInfo.pretty_name || osInfo.name || 'Ubuntu',
      kernel: String(kernel).trim(),
      arch: String(arch).trim(),
    };
  } catch {
    return { os: null, kernel: null, arch: null };
  }
}

/** 설치된 Jenkins 패키지(Runtime·UAB) 버전 — components.json */
export async function collectRuntimeManifestVersion() {
  try {
    let manifestPath = COMPONENTS_MANIFEST_PATH;
    try {
      await access(manifestPath);
    } catch {
      manifestPath = COMPONENTS_LOCK_PATH;
      await access(manifestPath);
    }
    const { stdout } = await exec('cat', [manifestPath], { timeout: 5000 });
    const manifest = JSON.parse(String(stdout));
    return {
      version: manifest.version || null,
      build_ts: manifest.build_ts || null,
      components: manifest.components || {},
    };
  } catch {
    return { version: process.env.WHICK_SOFTWARE_VERSION || null, build_ts: null, components: {} };
  }
}

/**
 * 종합 — heartbeat·update 보고용
 * @returns {Promise<{ software_version: string, docker_engine: object, images: object, host: object, manifest: object, collected_at: string }>}
 */
export async function collectAllComponentVersions() {
  const [images, digests, dockerEngine, host, manifest] = await Promise.all([
    collectDockerImageVersions(),
    collectDockerDigests(),
    collectDockerEngineVersion(),
    collectHostInfo(),
    collectRuntimeManifestVersion(),
  ]);

  // OTA가 .env 에 찍은 TARGET 을 lock 보다 우선 — lock 이 옛 버전으로 남아도
  // heartbeat 이 업데이트 완료 버전을 되돌리지 않게 한다.
  const envVer = process.env.WHICK_SOFTWARE_VERSION || null;
  return {
    software_version: envVer || manifest.version || 'unknown',
    docker_engine: dockerEngine,
    images,
    host,
    manifest,
    collected_at: new Date().toISOString(),
  };
}
