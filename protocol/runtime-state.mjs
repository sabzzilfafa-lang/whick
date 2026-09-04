import fs from 'node:fs';
import path from 'node:path';
import { kstIso } from './kst.mjs';

export const DEFAULT_STATE_PATH = '/var/lib/whick/runtime-state.json';

/**
 * @param {string} [statePath]
 */
export function loadRuntimeState(statePath = DEFAULT_STATE_PATH) {
  try {
    const raw = fs.readFileSync(statePath, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * @param {Record<string, unknown>} patch
 * @param {string} [statePath]
 */
export function saveRuntimeState(patch, statePath = DEFAULT_STATE_PATH) {
  const dir = path.dirname(statePath);
  fs.mkdirSync(dir, { recursive: true });
  const prev = loadRuntimeState(statePath) || {};
  const next = { ...prev, ...patch, updated_at: kstIso() };
  const tmp = `${statePath}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2));
  fs.renameSync(tmp, statePath);
  try {
    fs.chmodSync(statePath, 0o600);
  } catch {
    /* dev bind mount */
  }
  return next;
}

/**
 * Heartbeat liveness — utimes only; never read-modify-write (avoids clobbering token).
 * @param {string} [statePath]
 */
export function touchRuntimeStateHeartbeat(statePath = DEFAULT_STATE_PATH) {
  try {
    if (!fs.existsSync(statePath)) return null;
    const now = new Date();
    fs.utimesSync(statePath, now, now);
    return true;
  } catch {
    return null;
  }
}
