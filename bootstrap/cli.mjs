#!/usr/bin/env node
/**
 * Install flow smoke — CC /install/* (dev)
 * Usage: node bootstrap/cli.mjs [--cc URL] [--hw HASH]
 */
import crypto from 'node:crypto';
import os from 'node:os';
import { createBootstrapClient } from '../protocol/bootstrap-client.mjs';
import {
  DEFAULT_INSTALL_CREDENTIALS_PATH,
  saveInstallCredentials,
} from '../protocol/install-credentials.mjs';
import { kstIso } from '../protocol/kst.mjs';

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : fallback;
}

const CC_URL = arg('--cc', process.env.WHICK_CC_API_URL || 'http://127.0.0.1:8090/api/v1');
const HW_HASH =
  arg('--hw', null) ||
  crypto.createHash('sha256').update(`${os.hostname()}|bootstrap-smoke`).digest('hex');
const MB_ID = arg('--mb', process.env.WHICK_OWNER_MB_ID || process.env.WHICK_MB_ID || 'bootstrap-smoke');
const CRED_PATH = arg('--cred', process.env.WHICK_INSTALL_CREDENTIALS_PATH || DEFAULT_INSTALL_CREDENTIALS_PATH);

async function main() {
  const boot = createBootstrapClient({ baseUrl: CC_URL });

  console.log('[bootstrap] POST /install/sessions');
  const session = await boot.createSession({
    hostname_hint: os.hostname(),
  });
  console.log('  session_id', session.session_id);
  console.log('  device_code', session.device_code);

  console.log('[bootstrap] POST /install/hw-report');
  await boot.hwReport({
    session_id: session.session_id,
    hw_id_hash: HW_HASH,
    fingerprint: {
      hostname: os.hostname(),
      primary_mac: 'smoke',
    },
  });
  console.log('  hw_id_hash', HW_HASH.slice(0, 16) + '…');

  console.log('[bootstrap] POST /install/register-product');
  const reg = await boot.registerProduct({
    session_id: session.session_id,
    mb_id: MB_ID,
    email: 'smoke@whick.local',
    server_name: 'Bootstrap Smoke',
    mode: 'diy',
  });
  console.log('  device_id', reg.device_id);
  console.log('  serial_no', reg.serial_no || HW_HASH);
  console.log('  license_status', reg.license_status);

  const deviceSerial = reg.serial_no || reg.agent_register_hint?.device_serial || HW_HASH;
  saveInstallCredentials(
    {
      mb_id: MB_ID,
      device_serial: deviceSerial,
      hw_id_hash: deviceSerial,
      device_id: reg.device_id,
      customer_id: reg.customer_id,
      license_status: reg.license_status,
      registered_at: kstIso(),
      source: 'bootstrap-cli',
    },
    CRED_PATH,
  );
  console.log('  → saved', CRED_PATH);

  if (reg.agent_register_hint) {
    console.log('  → runtime: WHICK_DEVICE_SERIAL=', deviceSerial);
    console.log('  → runtime: WHICK_OWNER_MB_ID=', MB_ID);
  }
}

main().catch((e) => {
  console.error('[bootstrap] FAIL', e.code || '', e.message);
  process.exit(1);
});
