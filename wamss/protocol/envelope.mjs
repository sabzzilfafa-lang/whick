import crypto from 'node:crypto';
import { kstIso } from './kst.mjs';

export const PROTOCOL_VERSION = '1.0.0';

/**
 * @param {object} opts
 * @param {string} [opts.messageId]
 * @param {string|null} [opts.deviceSerial]
 * @param {'bootstrap'|'agent'|'monitor'} opts.source
 * @param {string} opts.type
 * @param {Record<string, unknown>} opts.payload
 */
export function envelope({ messageId, deviceSerial = null, source, type, payload }) {
  return {
    protocol_version: PROTOCOL_VERSION,
    message_id: messageId ?? crypto.randomUUID(),
    sent_at: kstIso(),
    device_serial: deviceSerial,
    source,
    type,
    payload,
  };
}

/** CC 응답 unwrap — { ok, data, error } */
export function unwrapResponse(json) {
  if (json && typeof json === 'object' && 'ok' in json) {
    if (!json.ok) {
      const msg = json.error?.message || 'CC request failed';
      const code = json.error?.code || 'CC_ERROR';
      const err = new Error(msg);
      err.code = code;
      throw err;
    }
    return json.data;
  }
  return json;
}
