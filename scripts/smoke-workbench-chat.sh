#!/usr/bin/env bash
# Simulates the Workbench renderer chat path against a running runtime API.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${DEEPSEEK_RUNTIME_PORT:-7878}"
BASE="http://127.0.0.1:${PORT}"
PYTHON="${DEEPSEEK_PYTHON:-${ROOT}/.venv/bin/python}"

if ! curl -sf "${BASE}/health" >/dev/null; then
  echo "[smoke] runtime not reachable at ${BASE}; start with:"
  echo "  PYTHONPATH=${ROOT}/src ${PYTHON} -m deepseek_tui serve --http --insecure --port ${PORT} --config ${ROOT}/.deepseek/config.toml"
  exit 1
fi

export SMOKE_BASE="$BASE"
PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" <<'PY'
import asyncio
import json
import os
import sys

import httpx

BASE = os.environ["SMOKE_BASE"]


async def read_sse_until(
    client: httpx.AsyncClient,
    thread_id: str,
    *,
    since_seq: int,
    stop_events: set[str],
    timeout_s: float = 120.0,
) -> list[dict]:
    seen: list[dict] = []
    deadline = asyncio.get_running_loop().time() + timeout_s
    async with client.stream(
        "GET",
        f"/v1/threads/{thread_id}/events",
        params={"since_seq": since_seq},
        timeout=None,
    ) as resp:
        resp.raise_for_status()
        buffer = ""
        while asyncio.get_running_loop().time() < deadline:
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    event_name = ""
                    data_line = ""
                    for line in frame.splitlines():
                        if line.startswith("event:"):
                            event_name = line[6:].strip()
                        elif line.startswith("data:"):
                            data_line = line[5:].strip()
                    if not data_line:
                        continue
                    payload = json.loads(data_line)
                    seen.append({"event": event_name or payload.get("event"), "payload": payload})
                    if (event_name or payload.get("event")) in stop_events:
                        return seen
            await asyncio.sleep(0.05)
    return seen


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as client:
        detail_before = await client.post("/v1/threads", json={"auto_approve": True})
        detail_before.raise_for_status()
        thread_id = detail_before.json()["id"]
        detail = await client.get(f"/v1/threads/{thread_id}")
        detail.raise_for_status()
        since_seq = detail.json().get("latest_seq", 0)

        sse_task = asyncio.create_task(
            read_sse_until(
                client,
                thread_id,
                since_seq=since_seq,
                stop_events={"turn.completed", "turn.failed", "turn.interrupted"},
            )
        )

        turn = await client.post(
            f"/v1/threads/{thread_id}/turns",
            json={"prompt": "Reply with exactly: pong", "auto_approve": True},
        )
        if turn.status_code != 201:
            print("[smoke] turn failed:", turn.status_code, turn.text[:500], file=sys.stderr)
            sse_task.cancel()
            return 1
        turn_id = turn.json()["turn"]["id"]
        print(f"[smoke] turn_id={turn_id}")

        events = await sse_task
        names = [e["event"] for e in events]
        print(f"[smoke] sse events ({len(names)}):", ", ".join(names[:12]), ("..." if len(names) > 12 else ""))

        if "turn.completed" not in names and "turn.failed" not in names:
            detail = await client.get(f"/v1/threads/{thread_id}")
            turns = {t["id"]: t for t in detail.json().get("turns", [])}
            status = turns.get(turn_id, {}).get("status")
            print(f"[smoke] timeout waiting for turn.completed (status={status})", file=sys.stderr)
            return 1

        detail = await client.get(f"/v1/threads/{thread_id}")
        items = detail.json().get("items", [])
        texts = [
            (it.get("detail") or it.get("summary") or "")
            for it in items
            if it.get("turn_id") == turn_id and it.get("kind") == "agent_message"
        ]
        print(f"[smoke] agent_message={texts[-1] if texts else '(none)'}")
        print("[smoke] ok")
        return 0


raise SystemExit(asyncio.run(main()))
PY
