import fs from 'node:fs';
import path from 'node:path';
import { kstIso } from './kst.mjs';

export const DEFAULT_INSTALL_CREDENTIALS_PATH = '/var/lib/whick/install-credentials.json';

/**
 * UAB register-product 직후 저장 — agent register 시 mb_id · hw_id_hash SSOT
 * @param {string} [credPath]
 */
export function loadInstallCredentials(credPath = DEFAULT_INSTALL_CREDENTIALS_PATH) {
  try {
    const raw = fs.readFileSync(credPath, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * @param {Record<string, unknown>} patch
 * @param {string} [credPath]
 */
export function saveInstallCredentials(patch, credPath = DEFAULT_INSTALL_CREDENTIALS_PATH) {
  const dir = path.dirname(credPath);
  fs.mkdirSync(dir, { recursive: true });
  const prev = loadInstallCredentials(credPath) || {};
  const next = { ...prev, ...patch, updated_at: kstIso() };
  const tmp = `${credPath}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2));
  fs.renameSync(tmp, credPath);
  try {
    fs.chmodSync(credPath, 0o600);
  } catch {
    /* dev bind mount */
  }
  return next;
}
