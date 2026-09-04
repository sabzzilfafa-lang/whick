import os from 'node:os';

/** 첫 번째 비-루프백 IPv4 — 관제 UI 네트워크 표시용 */
export function pickLanIp() {
  try {
    const ifaces = os.networkInterfaces();
    for (const list of Object.values(ifaces)) {
      if (!list) continue;
      for (const info of list) {
        if (
          info &&
          info.family === 'IPv4' &&
          !info.internal &&
          info.address &&
          !info.address.startsWith('169.254.')
        ) {
          return info.address;
        }
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function networkPayload() {
  const device_class = process.env.WHICK_DEVICE_CLASS || null;
  return {
    hostname: os.hostname(),
    lan_ip: pickLanIp(),
    ...(device_class ? { device_class: device_class.toLowerCase() } : {}),
  };
}
