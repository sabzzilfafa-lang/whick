import {
  DEFAULT_INSTALL_CREDENTIALS_PATH,
  loadInstallCredentials,
} from '../protocol/install-credentials.mjs';
import { loadRuntimeState, DEFAULT_STATE_PATH } from '../protocol/runtime-state.mjs';

/**
 * CC /agent/register 소유자 확인용 mb_id (site member id)
 * @param {NodeJS.ProcessEnv} [env]
 * @param {{ statePath?: string, credPath?: string }} [opts]
 */
export function resolveOwnerMbId(env = process.env, opts = {}) {
  const statePath = opts.statePath || env.WHICK_STATE_PATH || DEFAULT_STATE_PATH;
  const credPath = opts.credPath || env.WHICK_INSTALL_CREDENTIALS_PATH || DEFAULT_INSTALL_CREDENTIALS_PATH;

  const fromEnv = String(env.WHICK_OWNER_MB_ID || env.WHICK_MB_ID || '').trim();
  if (fromEnv) return fromEnv;

  const saved = loadRuntimeState(statePath);
  const fromState = String(saved?.mb_id || '').trim();
  if (fromState) return fromState;

  const creds = loadInstallCredentials(credPath);
  const fromCreds = String(creds?.mb_id || creds?.site_member_id || '').trim();
  if (fromCreds) return fromCreds;

  return '';
}
