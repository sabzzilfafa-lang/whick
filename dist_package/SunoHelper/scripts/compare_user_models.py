import json
from pathlib import Path

data = json.loads(Path(__file__).resolve().parent.parent.joinpath("data", "openrouter_models.json").read_text(encoding="utf-8"))

CANDIDATES = [
    # user picks
    "~deepseek/deepseek-v4-flash-latest",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "google/gemini-3.7-flash",
    "z-ai/glm-5.3-flash",
    "minimax/minimax-m3",
    # alternatives
    "google/gemini-2.5-flash-lite",
    "google/gemini-3.5-flash",
    "deepseek/deepseek-v3.2",
    "xiaomi/mimo-v2.5",
    "qwen/qwen3.7-flash",
    "upstage/solar-pro4",
    "meta-llama/llama-3.3-70b-instruct",
    "openai/gpt-4o-mini",
    "z-ai/glm-4.7-flash",
]

by_id = {m["id"]: m for m in data["data"]}

print("id | in | out | score")
for cid in CANDIDATES:
    m = by_id.get(cid)
    if not m:
        print(f"{cid} | NOT FOUND")
        continue
    pr = m["pricing"]
    inp = float(pr["prompt"]) * 1e6
    out = float(pr["completion"]) * 1e6
    score = inp + out * 0.4
    print(f"{cid} | {inp:.2f} | {out:.2f} | {score:.2f}")
