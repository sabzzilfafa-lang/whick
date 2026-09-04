import { createCcClient } from './cc-client.mjs';

/**
 * UAB / install CLI용 CC bootstrap 클라이언트
 * @param {object} opts
 * @param {string} opts.baseUrl
 * @param {string} [opts.bootstrapToken]
 */
export function createBootstrapClient({ baseUrl, bootstrapToken }) {
  let token = bootstrapToken || null;

  const client = createCcClient({
    baseUrl,
    token: token || 'bst_pending',
    source: 'bootstrap',
  });

  return {
    async createSession(payload = {}) {
      const data = await client.post('/install/sessions', {
        type: 'install_session_create',
        payload: {
          install_path: payload.install_path || 'diy',
          software_version: payload.software_version || 'v0.1.0',
          hostname_hint: payload.hostname_hint || null,
        },
      });
      token = data.bootstrap_token;
      return data;
    },

    async hwReport(payload) {
      if (!token) throw new Error('bootstrap token required — createSession first');
      const cc = createCcClient({
        baseUrl,
        token,
        source: 'bootstrap',
      });
      return cc.post('/install/hw-report', {
        type: 'hw_report',
        payload,
      });
    },

    async registerProduct(payload) {
      if (!token) throw new Error('bootstrap token required');
      const cc = createCcClient({
        baseUrl,
        token,
        source: 'bootstrap',
      });
      return cc.post('/install/register-product', {
        type: 'register_product',
        payload,
      });
    },

    get bootstrapToken() {
      return token;
    },
  };
}
