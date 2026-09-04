import os from 'node:os';
import crypto from 'node:crypto';
import { createCcClient, resolveCcUrl } from '../protocol/cc-client.mjs';
import { collectMetrics } from './metrics.mjs';
import { evaluateHealth } from './health_policy.mjs';
import { scanIncoming } from './library_watch.mjs';
import { waitForRuntimeToken } from './credentials.mjs';
import {
  libraryJobMessageId,
  loadKnownJobs,
  saveKnownJobs,
  forgetKnownJob,
  completedIncomingPaths,
} from './known_jobs.mjs';

const CC_URL = await resolveCcUrl(process.env.WHICK_CC_API_URL, 'monitor');
const INTERVAL_SEC = Number(process.env.WHICK_MONITOR_INTERVAL_SEC || 30);
const INCOMING = process.env.WHICK_LIBRARY_INCOMING || '/var/lib/whick/library/incoming';

let creds = await waitForRuntimeToken();
console.log('[monitor] credentials from', process.env.WHICK_AGENT_TOKEN ? 'env' : 'runtime-state');

function buildCcClient() {
  const serial = process.env.WHICK_DEVICE_SERIAL || creds.device_serial || '';
  return createCcClient({
    baseUrl: CC_URL,
    token: creds.token,
    deviceSerial: serial || null,
    source: 'monitor',
  });
}

let cc = buildCcClient();

const knownJobs = loadKnownJobs();

const JOB_IN_FLIGHT = new Set(['queued', 'processing']);
const JOB_DONE = new Set(['completed']);
const JOB_RETRY = new Set(['failed']);

async function fetchLibraryJobStatus(jobId) {
  try {
    return await cc.get(`/agent/library-jobs/${jobId}`);
  } catch {
    return null;
  }
}

async function shouldSkipLibraryJob(messageId, batchPaths = []) {
  const entry = knownJobs.get(messageId);
  if (!entry?.job_id) {
    if (entry) forgetKnownJob(knownJobs, messageId);
    return false;
  }

  const job = await fetchLibraryJobStatus(entry.job_id);
  if (!job?.status) return false;

  const status = String(job.status);
  if (JOB_IN_FLIGHT.has(status)) {
    entry.status = status;
    saveKnownJobs(knownJobs);
    return true;
  }

  if (JOB_DONE.has(status)) {
    entry.status = status;
    if (batchPaths.length) entry.file_paths = batchPaths;
    saveKnownJobs(knownJobs);
    return true;
  }

  if (JOB_RETRY.has(status)) {
    if (entry.retried) {
      entry.status = status;
      saveKnownJobs(knownJobs);
      return true;
    }
    return false;
  }

  return false;
}

async function queueLibraryJob(library, messageId, opts = {}) {
  const trackMessageId = opts.trackMessageId || messageId;
  const batchPaths = opts.batchPaths || library.files.map((f) => f.rel_path);

  const data = await cc.post('/agent/library-jobs', {
    type: 'library_job_create',
    messageId,
    payload: {
      job_type: 'scan',
      source_path: library.incoming_path,
      files: library.files,
    },
  });

  if (data.duplicate && data.job_id) {
    const status = String(data.status || '');
    if (JOB_IN_FLIGHT.has(status) || JOB_DONE.has(status)) {
      knownJobs.set(trackMessageId, { job_id: data.job_id, status, file_paths: batchPaths });
      saveKnownJobs(knownJobs);
      console.log('[monitor] library job already queued', data.job_id, status);
      return data;
    }
    if (JOB_RETRY.has(status)) {
      const existing = knownJobs.get(trackMessageId);
      if (existing?.retried) {
        knownJobs.set(trackMessageId, { job_id: data.job_id, status: 'failed', retried: true });
        saveKnownJobs(knownJobs);
        console.warn('[monitor] library job failed (already retried)', data.job_id);
        return data;
      }
      const retryId = crypto.createHash('sha256').update(`${messageId}:${Date.now()}`).digest('hex').slice(0, 36);
      console.log('[monitor] library job retry after', status, data.job_id);
      const retryData = await queueLibraryJob(library, retryId, { trackMessageId, batchPaths });
      if (retryData?.job_id) {
        knownJobs.set(trackMessageId, {
          job_id: retryData.job_id,
          status: retryData.status || 'queued',
          retried: true,
          file_paths: batchPaths,
        });
        saveKnownJobs(knownJobs);
      }
      return retryData;
    }
  }

  if (data.job_id && trackMessageId === messageId) {
    knownJobs.set(trackMessageId, {
      job_id: data.job_id,
      status: data.status || 'queued',
      file_paths: batchPaths,
    });
    saveKnownJobs(knownJobs);
  }
  if (data.duplicate) {
    console.log('[monitor] library job duplicate', data.job_id);
    return data;
  }
  console.log('[monitor] library job queued', data.job_id, 'files', library.files.length);
  return data;
}

async function maybeCreateLibraryJob(library) {
  if (!library.pending_files || !library.files?.length) return;

  const batchPaths = library.files.map((f) => f.rel_path);
  const key = batchPaths.slice().sort().join('|');
  const messageId = libraryJobMessageId(key);
  if (await shouldSkipLibraryJob(messageId, batchPaths)) return;

  await queueLibraryJob(library, messageId, { batchPaths });

  if (library.scan_truncated) {
    console.log(
      '[monitor] library incoming has more files after batch',
      library.files.length,
      'of',
      library.pending_files,
    );
  }
}

async function reloadCredentials() {
  const oldToken = creds.token;
  creds = await waitForRuntimeToken(undefined, { rejectToken: oldToken });
  cc = buildCcClient();
  console.log('[monitor] credentials reloaded');
}

async function postSnapshot() {
  const skipPaths = completedIncomingPaths(knownJobs);
  const metrics = await collectMetrics();
  const healthPolicy = evaluateHealth(metrics);
  const library = await scanIncoming(INCOMING, { skipPaths });
  const health = healthPolicy.alerts.length ? 'warning' : metrics.health;
  const payload = {
    health,
    uptime_sec: Math.floor(os.uptime()),
    runtime: {
      compose_project: process.env.WHICK_COMPOSE_PROJECT || 'whick-runtime',
      services: metrics.services,
    },
    metrics: {
      cpu_pct: metrics.cpu_pct,
      cpu_model: metrics.cpu_model,
      mem_pct: metrics.mem_pct,
      disk_pct: metrics.disk_pct,
      ssd1_pct: metrics.ssd1_pct,
      ssd2_pct: metrics.ssd2_pct,
      ssd1_total_kb: metrics.ssd1_total_kb,
      ssd1_used_kb: metrics.ssd1_used_kb,
      ssd2_total_kb: metrics.ssd2_total_kb,
      ssd2_used_kb: metrics.ssd2_used_kb,
      ssd2_mount: metrics.ssd2_mount,
      temp_c: metrics.temp_c,
      ssd_hours: metrics.ssd_hours,
      ssd_model: metrics.ssd_model,
      smart_status: metrics.smart_status,
    },
    health_alerts: healthPolicy.alerts,
    remediation: {
      suppress_nonessential_jobs: healthPolicy.suppress_nonessential_jobs,
    },
    library,
  };

  await cc.post('/agent/monitor-snapshot', {
    type: 'monitor_snapshot',
    payload,
  });
  console.log(
    '[monitor] snapshot',
    health,
    'alerts',
    healthPolicy.alerts.length,
    'incoming',
    library.pending_files,
  );
  return { library, healthPolicy };
}

async function tick() {
  try {
    const { library, healthPolicy } = await postSnapshot();
    if (healthPolicy.suppress_nonessential_jobs) {
      console.warn('[monitor] health remediation active: nonessential library scan job deferred');
    } else {
      await maybeCreateLibraryJob(library);
    }
  } catch (e) {
    if (e.code === 'AGENT_AUTH_INVALID') {
      try {
        await reloadCredentials();
      } catch (reloadErr) {
        console.warn('[monitor] credential reload failed', reloadErr.message);
      }
    }
    console.warn('[monitor]', e.code || '', e.message);
  }
}

console.log('[monitor] start interval', INTERVAL_SEC, 's', 'incoming', INCOMING);
await tick();
setInterval(tick, INTERVAL_SEC * 1000);
