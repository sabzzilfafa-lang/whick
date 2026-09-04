/**
 * Whick Remote Portal — API base (same-origin via nginx proxy)
 */
window.WHICK_REMOTE_PORTAL = {
  apiBase: '/api/v1/remote',
  remoteUiBase: '/v4',
  version: 'v0.9.33',
  tokenKey: 'whick_remote_token',
  userKey: 'whick_remote_user',
  deviceKey: 'whick_remote_device_id',
  devicesCacheKey: 'whick_remote_devices_cache',
  deviceEndpointsPrefix: 'whick_device_ep_',
};
