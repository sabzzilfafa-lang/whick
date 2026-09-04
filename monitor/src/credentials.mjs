import fs from 'node:fs';
import { DEFAULT_STATE_PATH, loadRuntimeState } from '../protocol/runtime-state.mjs';

const WAIT_MS = Number(process.env.WHICK_MONITOR_TOKEN_WAIT_MS || 120000);
const INTERVAL_MS = 2000;

/**
 * @param {string} [statePath]
 * @param {{ rejectToken?: string|null, waitForChangeMs?: number }} [opts]
 */
export async function waitForRuntimeToken(
  statePath = process.env.WHICK_STATE_PATH || DEFAULT_STATE_PATH,
  opts = {},
) {
  const rejectToken = opts.rejectToken || null;

  function readStateToken() {
    if (!fs.existsSync(statePath)) return null;
    const state = loadRuntimeState(statePath);
    if (!state?.token) return null;
    if (rejectToken && state.token === rejectToken) return null;
    return {
      token: state.token,
      device_serial: state.device_serial || process.env.WHICK_DEVICE_SERIAL || null,
    };
  }

  const immediate = readStateToken();
  if (immediate) return immediate;

  if (process.env.WHICK_AGENT_TOKEN && process.env.WHICK_AGENT_TOKEN !== rejectToken) {
    return {
      token: process.env.WHICK_AGENT_TOKEN,
      device_serial: process.env.WHICK_DEVICE_SERIAL || null,
    };
  }

  const pollDeadline = Date.now() + WAIT_MS;
  while (Date.now() < pollDeadline) {
    const creds = readStateToken();
    if (creds) return creds;
    await new Promise((r) => setTimeout(r, INTERVAL_MS));
  }
  throw new Error(`agent token not found in ${statePath} after ${WAIT_MS}ms`);
}
