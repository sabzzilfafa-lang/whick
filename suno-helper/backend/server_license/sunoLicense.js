/**
 * Suno Helper 라이선스 API — /api/suno/*
 *
 * 공개 엔드포인트 (whick.org 로그인 세션 필요 여부):
 *   POST /api/suno/activate  — 로그인 필요. install_token 검증 → RS256 라이선스 JWT 발급 (계정당 1대)
 *   POST /api/suno/renew     — 라이선스 자체로 갱신 (오프라인 갱신, 로그인 불필요)
 *   GET  /api/suno/version   — 공개. 업데이트 메타데이터 (Phase C 채널)
 *
 * 설계:
 *  - 라이선스 JWT는 RS256 (개인키 서버 / 공개키 앱 내장) — 서버 DB 유출로도 위조 불가
 *  - machine_id 바인딩, 계정당 활성 1대 (cc_suno_licenses 활성 행 1개 강제)
 *  - 유효기간 30일, 앱이 만료 7일 전부터 자동 renew
 */

import { Router } from 'express';
import jwt from 'jsonwebtoken';
import crypto from 'crypto';
import fs from 'fs';
import { ok, fail } from '../../../lib/response.js';
import { siteAuthRequired } from '../lib/site/siteAuth.js';
import { queryOne, mutate } from '../../../db.js';

const router = Router();

// ---------------------------------------------------------------------------
// 설정
// ---------------------------------------------------------------------------
const LICENSE_TTL_DAYS = 30;
const GRACE_DAYS = 30;
const PRODUCT = 'suno-helper';

const KEY_PRIV_PATH = process.env.SUNO_LICENSE_PRIVKEY_PATH || '/app/keys/suno_license_private.pem';
const KEY_KID = process.env.SUNO_LICENSE_KEY_ID || 'suno-2026-01';

function loadPrivateKey() {
  try {
    return fs.readFileSync(KEY_PRIV_PATH, 'utf8');
  } catch {
    return null;
  }
}

// install_token: 사이트가 고객에게 발급하는 1회성 활성화 토큰
// 형식: sh_<random32hex> — cc_suno_install_tokens 테이블에서 검증
function newInstallToken() {
  return 'sh_' + crypto.randomBytes(24).toString('hex');
}

function signLicense(payload) {
  const priv = loadPrivateKey();
  if (!priv) throw new Error('license key not configured');
  return jwt.sign(
    {
      product: PRODUCT,
      user_id: payload.user_id,
      email: payload.email,
      machine_id: payload.machine_id,
      plan: payload.plan || 'standard',
      kid: KEY_KID,
    },
    priv,
    {
      algorithm: 'RS256',
      issuer: 'whick.org',
      audience: 'suno-helper',
      expiresIn: `${LICENSE_TTL_DAYS}d`,
    },
  );
}

function machineHash(machineId) {
  // 원본 machine_id는 앱이 보관, 서버에는 해시만 저장 (개인정보 최소화)
  return crypto.createHash('sha256').update(String(machineId)).digest('hex').slice(0, 32);
}

async function ensureTables() {
  await mutate(`CREATE TABLE IF NOT EXISTS cc_suno_licenses (
    id SERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL,
    machine_hash VARCHAR(64) NOT NULL,
    plan VARCHAR(32) DEFAULT 'standard',
    status VARCHAR(16) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    renewed_at TIMESTAMPTZ DEFAULT now(),
    revoked_at TIMESTAMPTZ
  )`);
  await mutate(`CREATE UNIQUE INDEX IF NOT EXISTS idx_suno_lic_active
    ON cc_suno_licenses (member_id) WHERE status = 'active'`);
  await mutate(`CREATE TABLE IF NOT EXISTS cc_suno_install_tokens (
    id SERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL,
    token VARCHAR(80) NOT NULL UNIQUE,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
  )`);
}

// ---------------------------------------------------------------------------
// 라우트
// ---------------------------------------------------------------------------

/** 계정 활성화 토큰 발급 (웹에서 "내 PC 등록" 버튼 → 표시/복사) */
router.post('/token/new', siteAuthRequired, async (req, res) => {
  await ensureTables();
  const memberId = req.siteMember.id;
  // 기존 미사용 토큰 무효화 (1개 유지)
  await mutate(
    `UPDATE cc_suno_install_tokens SET used_at = now()
     WHERE member_id = $1 AND used_at IS NULL`,
    [memberId],
  );
  const token = newInstallToken();
  await mutate(
    `INSERT INTO cc_suno_install_tokens (member_id, token) VALUES ($1, $2)`,
    [memberId, token],
  );
  return ok(res, { token, expires_hint: '사용 시까지 유효' });
});

/** 내 라이선스 상태 (웹 마이페이지) */
router.get('/status', siteAuthRequired, async (req, res) => {
  await ensureTables();
  const row = await queryOne(
    `SELECT machine_hash, plan, status, created_at, renewed_at
     FROM cc_suno_licenses WHERE member_id = $1 AND status = 'active' LIMIT 1`,
    [req.siteMember.id],
  );
  return ok(res, { license: row || null, max_devices: 1 });
});

/** 활성화 — 앱이 install_token + machine_id로 호출 (로그인 세션 불필요) */
router.post('/activate', async (req, res) => {
  try {
    await ensureTables();
    const token = String(req.body?.install_token || '').trim();
    const machineId = String(req.body?.machine_id || '').trim();
    if (!token || !machineId) {
      return fail(res, 400, 'install_token과 machine_id가 필요합니다', 'BAD_REQUEST');
    }
    const trow = await queryOne(
      `SELECT id, member_id FROM cc_suno_install_tokens
       WHERE token = $1 AND used_at IS NULL LIMIT 1`,
      [token],
    );
    if (!trow) {
      return fail(res, 403, '활성화 토큰이 유효하지 않습니다', 'TOKEN_INVALID');
    }
    const member = await queryOne(
      `SELECT id, email, display_name FROM cc_site_members WHERE id = $1 LIMIT 1`,
      [trow.member_id],
    );
    if (!member) return fail(res, 403, '회원을 찾을 수 없습니다', 'MEMBER_NOT_FOUND');

    const mh = machineHash(machineId);
    // 계정당 1대 — 활성 라이선스가 다른 기기면 차단
    const existing = await queryOne(
      `SELECT id, machine_hash FROM cc_suno_licenses
       WHERE member_id = $1 AND status = 'active' LIMIT 1`,
      [member.id],
    );
    if (existing && existing.machine_hash !== mh) {
      return fail(
        res,
        409,
        '이 계정은 이미 다른 PC에 등록되어 있습니다 (계정당 1대). 웹에서 기기를 해지한 뒤 다시 시도하세요.',
        'DEVICE_LIMIT',
      );
    }
    if (existing && existing.machine_hash === mh) {
      // 재설치 — 기존 행 갱신
      await mutate(`UPDATE cc_suno_licenses SET renewed_at = now() WHERE id = $1`, [existing.id]);
    } else {
      await mutate(
        `INSERT INTO cc_suno_licenses (member_id, machine_hash) VALUES ($1, $2)`,
        [member.id, mh],
      );
    }
    await mutate(`UPDATE cc_suno_install_tokens SET used_at = now() WHERE id = $1`, [trow.id]);

    const license = signLicense({
      user_id: member.id,
      email: member.email,
      machine_id: String(machineId),
    });
    return ok(res, {
      license,
      plan: 'standard',
      ttl_days: LICENSE_TTL_DAYS,
      grace_days: GRACE_DAYS,
    });
  } catch (e) {
    if (String(e.message).includes('license key')) {
      return fail(res, 503, '라이선스 키 미설정', 'KEY_NOT_CONFIGURED');
    }
    return fail(res, 500, '활성화 실패', 'ACTIVATE_FAILED');
  }
});

/** 갱신 — 유효한 라이선스(만료 포함, grace 내)로 재발급. 로그인/토큰 불필요 */
router.post('/renew', async (req, res) => {
  try {
    const old = String(req.body?.license || '').trim();
    if (!old) return fail(res, 400, 'license 필요', 'BAD_REQUEST');
    const pub = loadPrivateKey(); // 검증용 공개키는 앱에 있으므로 서버에서는 개인키로 서명만
    if (!pub) return fail(res, 503, '라이선스 키 미설정', 'KEY_NOT_CONFIGURED');
    // 서버가 발급한 것인지 확인: 발급자 서명은 개인키 — verify에는 공개키가 필요하므로
    // 서버에는 개인키에서 파생한 공개키를 저장해 둔다
    const pubPemPath = process.env.SUNO_LICENSE_PUBKEY_PATH || '/app/keys/suno_license_public.pem';
    let pubPem;
    try {
      pubPem = fs.readFileSync(pubPemPath, 'utf8');
    } catch {
      return fail(res, 503, '라이선스 공개키 미설정', 'KEY_NOT_CONFIGURED');
    }
    let payload;
    try {
      payload = jwt.verify(old, pubPem, {
        algorithms: ['RS256'],
        issuer: 'whick.org',
        audience: 'suno-helper',
      });
    } catch {
      return fail(res, 403, '라이선스가 유효하지 않습니다', 'LICENSE_INVALID');
    }
    if (payload.product !== PRODUCT) {
      return fail(res, 403, '제품 불일치', 'LICENSE_INVALID');
    }
    await ensureTables();
    const mh = machineHash(payload.machine_id);
    const row = await queryOne(
      `SELECT id FROM cc_suno_licenses
       WHERE member_id = $1 AND machine_hash = $2 AND status = 'active' LIMIT 1`,
      [payload.user_id, mh],
    );
    if (!row) return fail(res, 403, '기기 등록 상태가 아닙니다', 'DEVICE_NOT_FOUND');

    await mutate(`UPDATE cc_suno_licenses SET renewed_at = now() WHERE id = $1`, [row.id]);
    const license = signLicense({
      user_id: payload.user_id,
      email: payload.email,
      machine_id: String(payload.machine_id),
      plan: payload.plan,
    });
    return ok(res, { license, ttl_days: LICENSE_TTL_DAYS, grace_days: GRACE_DAYS });
  } catch {
    return fail(res, 500, '갱신 실패', 'RENEW_FAILED');
  }
});

/** 기기 해지 (웹 마이페이지 — 다른 PC로 옮길 때) */
router.post('/deactivate', siteAuthRequired, async (req, res) => {
  await ensureTables();
  await mutate(
    `UPDATE cc_suno_licenses SET status = 'revoked', revoked_at = now()
     WHERE member_id = $1 AND status = 'active'`,
    [req.siteMember.id],
  );
  return ok(res, { deactivated: true });
});

/** 업데이트 채널 (공개) — CC 버전관리(cc_software_versions)에서 최신 stable 버전 조회 */
router.get('/version', async (_req, res) => {
  try {
    // CC 버전관리 SSOT: suno-helper 솔루션의 deploy 버전
    const row = await queryOne(
      `SELECT v.version, v.release_notes, v.released_at
       FROM cc_software_versions v
       JOIN cc_solutions s ON s.id = v.solution_id
       WHERE s.code = 'suno-helper' AND v.dev_status = 'deploy' AND v.channel = 'stable'
       ORDER BY v.released_at DESC, v.id DESC LIMIT 1`,
    );
    if (row) {
      return ok(res, {
        product: PRODUCT,
        version: String(row.version || '').replace(/^v/, ''),
        notes: row.release_notes || '',
        url: `https://whick.org/downloads/suno-helper`,
        released_at: row.released_at || null,
      });
    }
  } catch {
    /* DB/테이블 없으면 아래 fallback */
  }
  // fallback: env 기반 (CC 등록 전 임시)
  return ok(res, {
    product: PRODUCT,
    version: process.env.SUNO_LATEST_VERSION || '',
    notes: process.env.SUNO_LATEST_NOTES || '',
    url: process.env.SUNO_LATEST_URL || 'https://whick.org/downloads/suno-helper',
  });
});

export default router;
