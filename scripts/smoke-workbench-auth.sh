#!/usr/bin/env bash
# Authenticated chat smoke — exercises the same /v1/* path as Workbench
# Electron, including the Bearer token from ~/.deepseek/runtime.token (or
# DEEPSEEK_RUNTIME_TOKEN env). Counterpart of smoke-workbench-chat.sh which
# bypasses auth via --insecure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${DEEPSEEK_RUNTIME_PORT:-7878}"
BASE="http://127.0.0.1:${PORT}"
PYTHON="${DEEPSEEK_PYTHON:-python}"
TOKEN_FILE="${DEEPSEEK_HOME:-$HOME/.deepseek}/runtime.token"

TOKEN="${DEEPSEEK_RUNTIME_TOKEN:-}"
if [[ -z "$TOKEN" && -f "$TOKEN_FILE" ]]; then
  TOKEN="$(tr -d '[:space:]' <"$TOKEN_FILE" || true)"
fi

if [[ -z "$TOKEN" ]]; then
  echo "[smoke] no runtime token found in DEEPSEEK_RUNTIME_TOKEN or ${TOKEN_FILE}." >&2
  echo "[smoke] start runtime first to generate one:" >&2
  echo "  PYTHONPATH=${ROOT}/src ${PYTHON} -m deepseek_tui serve --http --port ${PORT} --config ${ROOT}/.deepseek/config.toml" >&2
  exit 1
fi

if ! curl -sf "${BASE}/health" >/dev/null; then
  echo "[smoke] runtime not reachable at ${BASE}; start it first." >&2
  exit 1
fi

# Sanity: /v1/* must reject unauthenticated calls.
unauth_status="$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/v1/threads?limit=1")"
if [[ "$unauth_status" != "401" ]]; then
  echo "[smoke] expected 401 without bearer, got ${unauth_status}" >&2
  exit 1
fi

export SMOKE_BASE="$BASE"
export SMOKE_TOKEN="$TOKEN"
PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" <<'PY'
import asyncio
import json
import os
import sys

import httpx

BASE = os.environ["SMOKE_BASE"]
TOKEN = os.environ["SMOKE_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


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
        headers=HEADERS,
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
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=120.0) as client:
        create = await client.post("/v1/threads", json={"auto_approve": True})
        create.raise_for_status()
        thread_id = create.json()["id"]
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
        print(
            f"[smoke] sse events ({len(names)}):",
            ", ".join(names[:12]),
            ("..." if len(names) > 12 else ""),
        )
        if "turn.completed" not in names:
            print("[smoke] timeout waiting for turn.completed", file=sys.stderr)
            return 1
        print("[smoke] ok (authenticated)")
        return 0


raise SystemExit(asyncio.run(main()))
PY
