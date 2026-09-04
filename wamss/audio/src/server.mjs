import http from 'node:http';
import fs from 'node:fs';
import { kstIso } from '../protocol/kst.mjs';

const PORT = Number(process.env.WHICK_AUDIO_PORT || 8787);
const CAMILLA_PROFILE = process.env.WHICK_CAMILLA_PROFILE || '/var/lib/whick/camilla/profile.yml';

/** @type {{ playing: boolean, volume: number, track: string|null, updated_at: string, dsp_reloaded_at: string|null, dsp_swap_channels: boolean, camilla_path: string|null }} */
const state = {
  playing: false,
  volume: Number(process.env.WHICK_AUDIO_DEFAULT_VOLUME || 70),
  track: null,
  updated_at: kstIso(),
  dsp_reloaded_at: null,
  dsp_swap_channels: false,
  camilla_path: null,
};

function readCamillaSwap() {
  try {
    const yaml = fs.readFileSync(CAMILLA_PROFILE, 'utf8');
    state.camilla_path = CAMILLA_PROFILE;
    state.dsp_swap_channels = yaml.includes('whick_swap_lr');
    return yaml;
  } catch {
    state.camilla_path = null;
    state.dsp_swap_channels = false;
    return null;
  }
}

function json(res, code, body) {
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return {};
  }
}

function touch() {
  state.updated_at = kstIso();
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://127.0.0.1:${PORT}`);
  const path = url.pathname;

  if (req.method === 'GET' && path === '/health') {
    return json(res, 200, { ok: true, service: 'whick-audio', state });
  }

  if (req.method === 'GET' && path === '/status') {
    return json(res, 200, { ok: true, ...state });
  }

  const body = req.method === 'POST' ? await readBody(req) : {};

  if (req.method === 'POST' && path === '/play') {
    state.playing = true;
    state.track = body.track || body.path || body.title || state.track || 'unknown';
    touch();
    console.log('[audio] play', state.track);
    return json(res, 200, { ok: true, message: 'playing', state });
  }

  if (req.method === 'POST' && path === '/pause') {
    state.playing = false;
    touch();
    console.log('[audio] pause');
    return json(res, 200, { ok: true, message: 'paused', state });
  }

  if (req.method === 'POST' && path === '/stop') {
    state.playing = false;
    state.track = null;
    touch();
    console.log('[audio] stop');
    return json(res, 200, { ok: true, message: 'stopped', state });
  }

  if (req.method === 'POST' && path === '/volume') {
    const vol = body.volume ?? body.level ?? body.value;
    if (vol != null) {
      state.volume = Math.max(0, Math.min(100, Number(vol)));
    }
    touch();
    console.log('[audio] volume', state.volume);
    return json(res, 200, { ok: true, message: 'volume', state });
  }

  if (req.method === 'GET' && path === '/dsp/status') {
    readCamillaSwap();
    return json(res, 200, {
      ok: true,
      camillaPath: state.camilla_path || CAMILLA_PROFILE,
      swapChannels: state.dsp_swap_channels,
      reloadedAt: state.dsp_reloaded_at || null,
    });
  }

  if (req.method === 'POST' && path === '/dsp/reload') {
    readCamillaSwap();
    state.dsp_reloaded_at = kstIso();
    touch();
    console.log('[audio] dsp reload', state.dsp_reloaded_at, 'swap=', state.dsp_swap_channels);
    return json(res, 200, {
      ok: true,
      message: 'dsp reloaded',
      reloadedAt: state.dsp_reloaded_at,
      swapChannels: state.dsp_swap_channels,
    });
  }

  if (req.method === 'POST' && path === '/sweep/play') {
    touch();
    console.log('[audio] sweep play requested');
    return json(res, 200, { ok: true, message: 'sweep', state });
  }

  if (req.method === 'POST' && path === '/test-tone/play') {
    const ch = body.channel === 'right' ? 'right' : 'left';
    readCamillaSwap();
    touch();
    console.log('[audio] test tone fallback', ch, 'swap=', state.dsp_swap_channels);
    return json(res, 200, { ok: true, channel: ch, swapChannels: state.dsp_swap_channels, message: 'test-tone', state });
  }

  return json(res, 404, { ok: false, error: 'not found' });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('[audio] stub listening', PORT, '(CamillaDSP TBD)');
});
