"""Offline scaling probe; run the same payload before/after age-index optimization."""

import hashlib
import json
import statistics
import time

from deepseek_tui.engine.capacity import ToolPruneConfig, prune_old_tool_results
from deepseek_tui.protocol.messages import Message

results = {}
for turns in (200, 800):
    samples = []
    for _ in range(5):
        messages = []
        for i in range(turns):
            messages.extend([Message.user(f"request {i}"), Message.tool_result(str(i), "x" * 5000)])
        start = time.perf_counter()
        changed = prune_old_tool_results(
            messages, config=ToolPruneConfig(hard_clear_min_reclaim=16000)
        )
        samples.append(1000 * (time.perf_counter() - start))
        payload = json.dumps([m.model_dump(mode="json") for m in messages], sort_keys=True)
    results[str(turns)] = {
        "messages": turns * 2,
        "samples": len(samples),
        "median_ms": round(statistics.median(samples), 3),
        "changed": changed,
        "output_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }
print(json.dumps(results, indent=2))
