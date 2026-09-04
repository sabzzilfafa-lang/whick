import fs from 'node:fs';
import path from 'node:path';
import { isAudioFile } from './metrics.mjs';
import { kstIso } from '../protocol/kst.mjs';

const DEFAULT_BATCH = Number(process.env.WHICK_LIBRARY_SCAN_BATCH || 50);

function walkAll(dir, base, out, skipPaths) {
  if (!fs.existsSync(dir)) return;
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      walkAll(full, base, out, skipPaths);
    } else if (ent.isFile() && isAudioFile(ent.name)) {
      const rel = path.relative(base, full);
      if (skipPaths?.has(rel)) continue;
      const st = fs.statSync(full);
      out.push({
        rel_path: rel,
        size_bytes: st.size,
        mtime: kstIso(st.mtime),
      });
    }
  }
}

/**
 * @param {string} incomingPath
 * @param {{ skipPaths?: Set<string> }} [opts]
 */
export async function scanIncoming(incomingPath, opts = {}) {
  const allFiles = [];
  walkAll(incomingPath, incomingPath, allFiles, opts.skipPaths);
  allFiles.sort((a, b) => a.rel_path.localeCompare(b.rel_path));

  const batchSize = DEFAULT_BATCH > 0 ? DEFAULT_BATCH : 50;
  const files = allFiles.slice(0, batchSize);

  return {
    incoming_path: incomingPath,
    pending_files: allFiles.length,
    scan_truncated: allFiles.length > files.length,
    last_scan_at: kstIso(),
    files,
  };
}
