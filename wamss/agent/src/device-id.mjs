import crypto from 'node:crypto';
import os from 'node:os';
import {
  DEFAULT_INSTALL_CREDENTIALS_PATH,
  loadInstallCredentials,
} from '../protocol/install-credentials.mjs';

const HW_HASH_RE = /^[a-f0-9]{64}$/i;

export function isHwIdHash(value) {
  return HW_HASH_RE.test(String(value || '').trim());
}

export function deriveDeviceSerial() {
  const parts = [os.hostname(), os.platform(), os.arch()];
  try {
    const ifaces = os.networkInterfaces();
    for (const list of Object.values(ifaces)) {
      if (!list) continue;
      for (const info of list) {
        if (info && !info.internal && info.mac && info.mac !== '00:00:00:00:00:00') {
          parts.push(info.mac);
          break;
        }
      }
    }
  } catch {
    /* ignore */
  }
  return crypto.createHash('sha256').update(parts.join('|')).digest('hex');
}

export function resolveDeviceSerial(env = process.env) {
  const explicit = String(env.WHICK_DEVICE_SERIAL || '').trim();
  if (explicit) return explicit.toLowerCase();

  const credPath =
    env.WHICK_INSTALL_CREDENTIALS_PATH || DEFAULT_INSTALL_CREDENTIALS_PATH;
  const creds = loadInstallCredentials(credPath);
  const fromCreds = String(
    creds?.device_serial || creds?.hw_id_hash || creds?.serial_no || '',
  ).trim();
  if (isHwIdHash(fromCreds)) return fromCreds.toLowerCase();

  throw Object.assign(
    new Error(
      'WHICK_DEVICE_SERIAL(64hex hw_id_hash) 또는 install-credentials.json 필요 — UAB register-product 후 설정',
    ),
    { code: 'DEVICE_SERIAL_REQUIRED' },
  );
}
