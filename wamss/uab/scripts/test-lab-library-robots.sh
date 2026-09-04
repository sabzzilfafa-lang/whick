#!/usr/bin/env bash
# Phase 9 — incoming → scan(robot-auditor 검수만) + classify(robot-classifier)
# 검수 로봇: 파일 변경 없음 · import/delete는 user_approved 후에만
set -euo pipefail

LAB_RUNTIME="${1:?usage: test-lab-library-robots.sh <LAB_RUNTIME>}"
CC="${WHICK_CC_API_URL:-http://127.0.0.1:8090/api/v1}"
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"
LAB_HW_HASH="${LAB_HW_HASH:?LAB_HW_HASH required}"
LAB_DEVICE_ID="${LAB_DEVICE_ID:?LAB_DEVICE_ID required}"
GRANT_SQL="/data/whick-ai/2_control_center/db/72-library-monitor-core-grant.sql"
COMPOSE=(docker compose -f "$LAB_RUNTIME/compose.yaml" -f "$LAB_RUNTIME/compose.override.yaml")
COMPOSE_OK=0
if [[ -f "$LAB_RUNTIME/compose.yaml" && -f "$LAB_RUNTIME/compose.override.yaml" ]]; then
  COMPOSE_OK=1
fi

die() { echo "ERROR: $*" >&2; exit 1; }

player_exec() {
  if [[ "$COMPOSE_OK" -eq 1 ]]; then
    "${COMPOSE[@]}" exec -T player sh -ce "$1"
  else
    docker exec whick-player sh -ce "$1"
  fi
}

agent_state() {
  if [[ "$COMPOSE_OK" -eq 1 ]]; then
    "${COMPOSE[@]}" exec -T agent cat /var/lib/whick/runtime-state.json 2>/dev/null \
      || docker exec whick-agent cat /var/lib/whick/runtime-state.json 2>/dev/null || true
  else
    docker exec whick-agent cat /var/lib/whick/runtime-state.json 2>/dev/null || true
  fi
}

robot_complete() {
  local job_id="$1" robot_id="$2" result_json="$3"
  docker exec whick-cc-api-core node --input-type=module -e "
import { claimLibraryJob, completeLibraryJob } from './src/lib/deviceProtocol.js';
import { pool } from './src/db.js';
const jobId = process.argv[1];
const robotId = process.argv[2];
const result = JSON.parse(process.argv[3]);
if (!await claimLibraryJob(jobId, robotId)) process.exit(2);
await completeLibraryJob(jobId, { success: true, result });
await pool.end();
" "$job_id" "$robot_id" "$result_json"
}

echo "==> phase 9 library robots (auditor + classifier)"
echo "    device_id=$LAB_DEVICE_ID hw=${LAB_HW_HASH:0:12}…"

if [[ -f "$GRANT_SQL" ]]; then
  docker exec -i -e PGPASSWORD=whick_cc_dev_pass whick-cc-db \
    psql -U cc_app -d whick_control -v ON_ERROR_STOP=1 <"$GRANT_SQL" 2>/dev/null \
    || die "failed to apply $GRANT_SQL"
  echo "  DB grants OK (cc_library_jobs · cc_monitor_snapshots)"
fi

AGENT_TOKEN=""
for _ in $(seq 1 90); do
  AGENT_JSON="$(agent_state)"
  AGENT_TOKEN="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('token') or '')" "$AGENT_JSON" 2>/dev/null || true)"
  [[ -n "$AGENT_TOKEN" ]] && break
  sleep 2
done
[[ -n "$AGENT_TOKEN" ]] || die "agent token not ready (whick-agent register?)"

docker ps --format '{{.Names}}' | grep -qx whick-monitor || die "whick-monitor not running"

INCOMING_N="$(player_exec '
  set -e
  inc=/var/lib/whick/library/incoming/robot-e2e
  mkdir -p "$inc"
  rm -f "$inc"/*
  n=0
  for f in /var/lib/whick/library/samples/flac/*.flac /var/lib/whick/library/samples/*.flac; do
    [ -f "$f" ] || continue
    cp "$f" "$inc/"
    n=$((n + 1))
    [ "$n" -ge 2 ] && break
  done
  echo "$n"
' 2>/dev/null | tr -d '[:space:]')"
if [[ "${INCOMING_N:-0}" -lt 2 ]]; then
  SAMPLE_SRC="${WHICK_SAMPLE_AUDIO_PATH:-/data/whick-ai_music_server/5_site/content/sample-audio}/flac"
  player_exec 'mkdir -p /var/lib/whick/library/incoming/robot-e2e' >/dev/null
  n=0
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    docker cp "$f" "whick-player:/var/lib/whick/library/incoming/robot-e2e/"
    n=$((n + 1))
    [[ "$n" -ge 2 ]] && break
  done < <(find "$SAMPLE_SRC" -maxdepth 1 -name '*.flac' 2>/dev/null | head -2)
  INCOMING_N="$n"
fi
[[ "${INCOMING_N:-0}" -ge 2 ]] || die "failed to stage 2 incoming FLAC files (got ${INCOMING_N:-0})"
echo "  staged 2 FLAC → incoming/robot-e2e"

export CC AGENT_TOKEN LAB_HW_HASH PLAYER_URL
export -f robot_complete
python3 <<'PY'
import json
import os
import shlex
import subprocess
import urllib.request
import uuid

CC = os.environ["CC"].rstrip("/")
AGENT = os.environ["AGENT_TOKEN"]
HW = os.environ["LAB_HW_HASH"].lower()
PLAYER = os.environ["PLAYER_URL"].rstrip("/")


def agent_req(path, method="GET", data=None, msg_type=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {AGENT}",
    }
    body = None
    if msg_type:
        body = json.dumps(
            {
                "message_id": str(uuid.uuid4()),
                "device_serial": HW,
                "source": "monitor",
                "type": msg_type,
                "payload": data or {},
            }
        ).encode()
    r = urllib.request.Request(f"{CC}{path}", data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=45) as resp:
        raw = json.loads(resp.read())
    if raw.get("ok") is False:
        raise RuntimeError(raw.get("error") or raw)
    return raw.get("data") if raw.get("data") is not None else raw


def robot_done(job_id, robot_id, result):
    rj = json.dumps(result)
    subprocess.run(
        [
            "bash",
            "-lc",
            f"robot_complete {shlex.quote(job_id)} {shlex.quote(robot_id)} {shlex.quote(rj)}",
        ],
        check=True,
        env=os.environ,
    )


def create_scan_job():
    payload_files = []
    for name in subprocess.check_output(
        ["docker", "exec", "whick-player", "ls", "/var/lib/whick/library/incoming/robot-e2e"],
        text=True,
    ).splitlines():
        name = name.strip()
        if not name.endswith(".flac"):
            continue
        payload_files.append({"rel_path": f"robot-e2e/{name}", "size_bytes": 1, "mtime": "lab-e2e"})
    scan = agent_req(
        "/agent/library-jobs",
        "POST",
        {
            "job_type": "scan",
            "source_path": "/var/lib/whick/library/incoming",
            "files": payload_files,
        },
        msg_type="library_job_create",
    )
    assert scan.get("robot_target") == "robot-auditor", scan
    return scan["job_id"], payload_files


scan_id, files = create_scan_job()
print(f"  scan job queued id={scan_id} files={len(files)}")

incoming_before = int(
    subprocess.check_output(
        [
            "docker",
            "exec",
            "whick-player",
            "sh",
            "-c",
            "find /var/lib/whick/library/incoming/robot-e2e -name '*.flac' | wc -l",
        ],
        text=True,
    ).strip()
)

approved = [f["rel_path"] for f in files]
robot_done(
    scan_id,
    "robot-auditor",
    {
        "mode": "audit_only",
        "files_modified": False,
        "approved": len(approved),
        "rejected": 0,
        "reviewed_files": approved,
        "rejected_files": [],
        "items": [{"rel_path": p, "verdict": "approved"} for p in approved],
        "robot": "robot-auditor",
    },
)
st = agent_req(f"/agent/library-jobs/{scan_id}")
assert st.get("status") == "completed", st
assert st.get("result", {}).get("mode") == "audit_only", st
print(f"  robot-auditor OK approved={len(approved)} (audit-only, no file changes)")

incoming_after = int(
    subprocess.check_output(
        [
            "docker",
            "exec",
            "whick-player",
            "sh",
            "-c",
            "find /var/lib/whick/library/incoming/robot-e2e -name '*.flac' | wc -l",
        ],
        text=True,
    ).strip()
)
assert incoming_after == incoming_before, f"auditor must not move/delete files: {incoming_before} -> {incoming_after}"

# import without user_approved → 403
try:
    urllib.request.urlopen(
        urllib.request.Request(
            f"{PLAYER}/api/library/import-incoming",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        ),
        timeout=30,
    )
    raise AssertionError("import without user_approved should fail")
except urllib.error.HTTPError as e:
    assert e.code == 403, e.code
print("  import blocked without user_approved OK")

classify = agent_req(
    "/agent/library-jobs",
    "POST",
    {
        "job_type": "classify",
        "source_path": "/var/lib/whick/library/incoming",
        "files": files,
    },
    msg_type="library_job_create",
)
classify_id = classify["job_id"]
assert classify.get("robot_target") == "robot-classifier", classify
print(f"  classify job queued id={classify_id}")

robot_done(
    classify_id,
    "robot-classifier",
    {
        "classified": len(files),
        "category_summary": {"lossless|hires": len(files)},
        "genres": {"classical": len(files)},
        "robot": "robot-classifier",
    },
)
st2 = agent_req(f"/agent/library-jobs/{classify_id}")
assert st2.get("status") == "completed", st2
print(f"  robot-classifier OK classified={len(files)}")

# 사용자 승인 후 approved_paths만 import
imp_body = json.dumps({"user_approved": True, "approved_paths": approved}).encode()
req = urllib.request.Request(
    f"{PLAYER}/api/library/import-incoming",
    data=imp_body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=120) as resp:
    imp = json.loads(resp.read())
assert imp.get("ok") is True, imp
assert imp.get("imported", {}).get("moved", 0) >= 1, imp
print(f"  import-incoming ok (user_approved) moved={imp.get('imported', {}).get('moved')}")
print("  PASS  library robots (auditor audit-only + classifier + user-approved import)")
PY

echo "OK  test-lab-library-robots.sh"
