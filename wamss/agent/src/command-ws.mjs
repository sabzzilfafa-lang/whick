/**
 * Agent Command WebSocket client — 장비별 /ws/agent 소켓 (CC push)
 * poll fallback: WS 끊기면 main.mjs pollCommands()가 처리
 */

/** @param {string} ccApiUrl e.g. https://admin.whick.org/api/v1 */
export function agentCommandWsUrl(ccApiUrl, token) {
  const base = String(ccApiUrl).replace(/\/api\/v1\/?$/, '').replace(/\/$/, '');
  const u = new URL(base);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = '/ws/agent';
  u.search = `token=${encodeURIComponent(token)}`;
  u.hash = '';
  return u.toString();
}

export function isAgentCmdWsEnabled() {
  const v = process.env.WHICK_AGENT_CMD_WS;
  if (v === '0' || v === 'false') return false;
  return true;
}

/**
 * @param {object} opts
 * @param {string} opts.ccUrl
 * @param {string} opts.token
 * @param {(cmd: object) => Promise<void>} opts.onCommand
 * @param {(connected: boolean, ws: WebSocket|null) => void} [opts.onConnectionChange]
 */
export function startAgentCommandWebSocket({ ccUrl, token, onCommand, onConnectionChange }) {
  if (!isAgentCmdWsEnabled()) {
    onConnectionChange?.(false, null);
    return () => {};
  }

  let ws = null;
  let stopped = false;
  let reconnectTimer = null;
  let pingTimer = null;
  let backoffMs = 2000;

  const notify = (connected) => {
    try {
      onConnectionChange?.(connected, connected ? ws : null);
    } catch {
      /* ignore */
    }
  };

  const clearPing = () => {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    clearPing();
    notify(false);
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, backoffMs);
    backoffMs = Math.min(Math.round(backoffMs * 1.5), 60000);
  };

  const connect = () => {
    if (stopped) return;
    const url = agentCommandWsUrl(ccUrl, token);
    try {
      ws = new WebSocket(url);
    } catch (e) {
      console.warn('[agent-ws] connect error', e.message);
      scheduleReconnect();
      return;
    }

    ws.addEventListener('open', () => {
      backoffMs = 2000;
      notify(true);
      console.log('[agent-ws] connected (per-device command socket)');
      pingTimer = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          clearPing();
          return;
        }
        try {
          ws.send(JSON.stringify({ type: 'ping' }));
        } catch {
          clearPing();
        }
      }, 25000);
    });

    ws.addEventListener('message', (ev) => {
      let msg;
      try {
        msg = JSON.parse(String(ev.data || ''));
      } catch {
        return;
      }
      if (msg.type === 'pong' || msg.type === 'hello' || msg.type === 'command_result_ack') return;
      if (msg.type !== 'command' || !msg.command) return;
      onCommand(msg.command).catch((e) => {
        console.warn('[agent-ws] command handler', e.message);
      });
    });

    ws.addEventListener('close', () => {
      ws = null;
      scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      /* close handles reconnect */
    });
  };

  connect();

  return () => {
    stopped = true;
    clearTimeout(reconnectTimer);
    clearPing();
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
      ws = null;
    }
    notify(false);
  };
}

/** 결과 보고 — HTTP 단일 경로 (CC가 멱등 처리하지만 이중 전송 자체를 막는다) */
export async function postCommandResult(cc, payload) {
  await cc.post('/agent/commands/result', {
    type: 'command_result',
    payload,
  });
}
