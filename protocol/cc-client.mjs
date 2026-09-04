import { envelope, unwrapResponse } from './envelope.mjs';

// 고객 미니PC 표준 CC 주소 — .env가 본사 루프백(127.0.0.1:8090)으로 남아도 자동 교정한다.
export const CANONICAL_CC_URL =
  process.env.WHICK_CANONICAL_CC_API_URL || 'https://admin.whick.org/api/v1';

function isLoopbackCcUrl(url) {
  try {
    const host = new URL(url).hostname;
    return host === 'localhost' || host === '::1' || /^127\./.test(host);
  } catch {
    return false;
  }
}

async function ccReachable(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 3000);
  try {
    const res = await fetch(`${url.replace(/\/$/, '')}/system/health/live`, {
      signal: ctrl.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * .env가 옛 USB/재설치로 127.0.0.1:8090(본사 루프백)에 고정되면 고객 장비는 CC에 영영 못 붙는다.
 * 루프백 주소가 실제로 CC를 서빙하지 않으면 표준 주소로 폴백 — 본사 lab(진짜 루프백)은 그대로 둔다.
 * @param {string} configured WHICK_CC_API_URL
 * @param {string} [tag] 로그 prefix (agent·monitor)
 */
export async function resolveCcUrl(configured, tag = 'agent') {
  const url = String(configured || '').trim();
  if (!url) {
    console.warn(`[${tag}] WHICK_CC_API_URL 미설정 — 표준 주소 사용`, CANONICAL_CC_URL);
    return CANONICAL_CC_URL;
  }
  if (!isLoopbackCcUrl(url)) return url;
  if (await ccReachable(url)) return url;
  console.warn(`[${tag}] CC ${url} 응답 없음(루프백) — ${CANONICAL_CC_URL} 로 폴백`);
  return CANONICAL_CC_URL;
}

/**
 * @param {object} opts
 * @param {string} opts.baseUrl — e.g. https://control.whick.org/api/v1
 * @param {string} opts.token — agt_ or bst_
 * @param {string|null} [opts.deviceSerial]
 * @param {'bootstrap'|'agent'|'monitor'} opts.source
 */
export function createCcClient({ baseUrl, token, deviceSerial = null, source }) {
  const root = baseUrl.replace(/\/$/, '');
  const installSecret = String(
    process.env.WHICK_INSTALL_BOOTSTRAP_SECRET || process.env.CC_INSTALL_BOOTSTRAP_SECRET || '',
  ).trim();

  async function request(method, path, { type, payload, messageId } = {}) {
    const body =
      type != null
        ? envelope({ messageId, deviceSerial, source, type, payload: payload ?? {} })
        : payload ?? {};

    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };
    if (installSecret) headers['X-Whick-Install-Secret'] = installSecret;

    const res = await fetch(`${root}${path}`, {
      method,
      headers,
      body: method === 'GET' ? undefined : JSON.stringify(body),
    });

    const json = await res.json().catch(() => ({}));
    if (!res.ok && json?.ok !== true) {
      const msg = json?.error?.message || res.statusText;
      const err = new Error(msg);
      err.code = json?.error?.code || `HTTP_${res.status}`;
      err.status = res.status;
      throw err;
    }
    return unwrapResponse(json);
  }

  return {
    get: (path) => request('GET', path),
    post: (path, opts) => request('POST', path, opts),
  };
}
