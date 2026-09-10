import json
import urllib.request
from collections import defaultdict
from pathlib import Path

cache = Path(__file__).resolve().parent.parent / "data" / "openrouter_models.json"
if cache.exists():
    data = json.loads(cache.read_text(encoding="utf-8"))
else:
    data = json.loads(urllib.request.urlopen("https://openrouter.ai/api/v1/models").read())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")


def score(m):
    pr = m.get("pricing") or {}
    inp = float(pr.get("prompt", 0) or 0) * 1e6
    out = float(pr.get("completion", 0) or 0) * 1e6
    name = m["id"].lower()
    skip = any(
        x in name
        for x in [
            "batch",
            "image",
            "embedding",
            "tts",
            "audio",
            ":free",
            "opus",
            "o1",
            "o3",
            "luna-pro",
            "terra-pro",
            "sol-pro",
            "5.5-pro",
            "5.4-pro",
            "5.6",
        ]
    )
    if skip:
        return None
    if inp > 2.5 or out > 12:
        return None
    total = inp + out * 0.45
    return (total, m["id"], m.get("name", ""), inp, out)


rows = []
for m in data["data"]:
    s = score(m)
    if s:
        rows.append(s)
rows.sort(key=lambda x: x[0])

by = defaultdict(list)
for r in rows:
    prefix = r[1].split("/")[0] if "/" in r[1] else "other"
    by[prefix].append(r)

for prefix in sorted(by.keys()):
    print(f"=== {prefix} (cheap) ===")
    for r in by[prefix][:12]:
        print(f"  {r[1]:48} ${r[3]:.2f}/${r[4]:.2f} per M")
