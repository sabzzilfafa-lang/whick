import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const DEFAULT_PATH =
  process.env.WHICK_MONITOR_KNOWN_JOBS || '/var/lib/whick/run/monitor-known-jobs.json';

/** @typedef {{ job_id: string, status?: string, retried?: boolean, file_paths?: string[] }} KnownJobEntry */

/**
 * CC `message_id` is CHAR(36) — use a 36-char hex digest.
 * @param {string} fileKey
 * @returns {string}
 */
export function libraryJobMessageId(fileKey) {
  return crypto.createHash('sha256').update(fileKey).digest('hex').slice(0, 36);
}

/**
 * @param {string} [statePath]
 * @returns {Map<string, KnownJobEntry>}
 */
export function loadKnownJobs(statePath = DEFAULT_PATH) {
  try {
    const raw = fs.readFileSync(statePath, 'utf8');
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      const map = new Map();
      for (const id of parsed) {
        if (typeof id === 'string') map.set(id, { job_id: '' });
      }
      return map;
    }
    if (parsed && typeof parsed === 'object') {
      const map = new Map();
      for (const [messageId, entry] of Object.entries(parsed)) {
        if (typeof entry === 'string') {
          map.set(messageId, { job_id: entry });
        } else if (entry && typeof entry === 'object' && entry.job_id) {
          map.set(messageId, {
            job_id: String(entry.job_id),
            status: entry.status,
            retried: Boolean(entry.retried),
            file_paths: Array.isArray(entry.file_paths) ? entry.file_paths : undefined,
          });
        }
      }
      return map;
    }
  } catch {
    /* fresh start */
  }
  return new Map();
}

/**
 * @param {Map<string, KnownJobEntry>} map
 * @param {string} [statePath]
 */
export function saveKnownJobs(map, statePath = DEFAULT_PATH) {
  try {
    fs.mkdirSync(path.dirname(statePath), { recursive: true });
    const entries = [...map.entries()].slice(-500);
    const obj = Object.fromEntries(entries);
    fs.writeFileSync(statePath, JSON.stringify(obj));
  } catch (err) {
    console.warn('[monitor] known-jobs persist failed', err.message);
  }
}

/**
 * @param {Map<string, KnownJobEntry>} map
 * @param {string} messageId
 * @param {string} [statePath]
 */
export function forgetKnownJob(map, messageId, statePath = DEFAULT_PATH) {
  map.delete(messageId);
  saveKnownJobs(map, statePath);
}

/**
 * @param {Map<string, KnownJobEntry>} knownJobs
 * @returns {Set<string>}
 */
export function completedIncomingPaths(knownJobs) {
  const paths = new Set();
  for (const entry of knownJobs.values()) {
    if (entry.status === 'completed' && Array.isArray(entry.file_paths)) {
      for (const rel of entry.file_paths) paths.add(rel);
    }
  }
  return paths;
}
