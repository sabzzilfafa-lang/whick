import { createCcClient } from '../protocol/cc-client.mjs';
import { saveRuntimeState, loadRuntimeState, DEFAULT_STATE_PATH } from '../protocol/runtime-state.mjs';
import { kstIso } from '../protocol/kst.mjs';
import { resolveDeviceSerial, isHwIdHash } from './device-id.mjs';
import { resolveOwnerMbId } from './owner-id.mjs';

/**
 * @param {object} opts
 * @param {string} opts.ccUrl
 * @param {string} [opts.statePath]
 * @param {string} [opts.deviceSerial]
 * @param {string} [opts.mbId]
 */
export async function ensureRegistered({
  ccUrl,
  statePath = DEFAULT_STATE_PATH,
  deviceSerial,
  mbId,
}) {
  const serial = (deviceSerial || resolveDeviceSerial()).toLowerCase();
  const ownerMbId = mbId || resolveOwnerMbId(process.env, { statePath });

  if (!isHwIdHash(serial)) {
    throw Object.assign(
      new Error(
        'WHICK_DEVICE_SERIAL(64hex hw_id_hash) 필요 — UAB install/register-product 후 install-credentials.json 또는 .env에 설정',
      ),
      { code: 'DEVICE_SERIAL_INVALID' },
    );
  }
  if (!ownerMbId) {
    throw Object.assign(
      new Error(
        'WHICK_OWNER_MB_ID(소유자 whick.org mb_id) 필요 — install/register-product 후 install-credentials.json 또는 .env에 설정',
      ),
      { code: 'OWNER_MB_ID_REQUIRED' },
    );
  }

  const envToken = process.env.WHICK_AGENT_TOKEN;
  if (envToken) {
    const probe = createCcClient({
      baseUrl: ccUrl,
      token: envToken,
      deviceSerial: serial,
      source: 'agent',
    });
    try {
      await probe.get('/agent/health');
      saveRuntimeState(
        {
          device_serial: serial,
          mb_id: ownerMbId,
          token: envToken,
          cc_api_url: ccUrl,
        },
        statePath,
      );
      return { device_serial: serial, mb_id: ownerMbId, token: envToken, from: 'env' };
    } catch (e) {
      if (e.code !== 'AGENT_AUTH_INVALID') throw e;
      console.warn('[agent] env token invalid — re-registering');
    }
  }

  const saved = loadRuntimeState(statePath);
  if (saved?.token && saved?.device_serial) {
    const probe = createCcClient({
      baseUrl: ccUrl,
      token: saved.token,
      deviceSerial: saved.device_serial,
      source: 'agent',
    });
    try {
      await probe.get('/agent/health');
      return { ...saved, from: 'state' };
    } catch (e) {
      if (e.code !== 'AGENT_AUTH_INVALID') throw e;
      console.warn('[agent] saved token invalid — re-registering');
      saveRuntimeState({ token: null, device_id: null }, statePath);
    }
  }

  const cc = createCcClient({
    baseUrl: ccUrl,
    token: 'register',
    source: 'agent',
    deviceSerial: serial,
  });

  const data = await cc.post('/agent/register', {
    type: 'register',
    payload: {
      device_serial: serial,
      reported_hash: serial,
      hw_id_hash: serial,
      mb_id: ownerMbId,
      hostname: `whick-${serial.slice(0, 12)}`,
      solution_code: process.env.WHICK_SOLUTION_CODE || 'S2',
      software_version: process.env.WHICK_SOFTWARE_VERSION || 'v0.1.0-dev',
    },
  });

  const token = data.token;
  if (!token) {
    throw new Error('register response missing token');
  }

  const state = saveRuntimeState(
    {
      device_serial: serial,
      mb_id: ownerMbId,
      device_id: data.device_id,
      token,
      cc_api_url: ccUrl,
      poll_interval_sec: data.poll_interval_sec || 60,
      registered_at: kstIso(),
    },
    statePath,
  );

  console.log(
    '[agent] registered device_id',
    data.device_id,
    'owner',
    ownerMbId,
    'serial',
    serial.slice(0, 12) + '…',
  );
  return { ...state, from: 'register' };
}
