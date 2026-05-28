#!/usr/bin/env python3
"""E2E: create three 1-minute Feishu automations via runtime API."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:7878"
FEISHU_CHAT = "oc_5b08c88b758c17b6dffd3a53bf501a36"
WORKSPACE = "/Users/fjw/.deepseekgui/default_workspace"
MODEL = "deepseek-v4-pro"

REQUESTS = [
    "一分钟后把腾讯股票发到飞书",
    "一分钟后把阿里股票发到飞书",
    "一分钟后把小米股票发到飞书",
]


def build_prompt(user_text: str) -> str:
    tz = "Asia/Shanghai"
    hints = [
        "The user wants a scheduled or delayed automation. Follow this playbook:",
        "Do NOT call tool_search_tool_regex, tool_search_tool_bm25, or any other discovery tools — tool names are listed below.",
        "Only use these tools for this request: current_time, automation_create (and automation_list/read/update/pause/resume/delete/run if the user asks to manage existing jobs).",
        f'1. Call `current_time` with timezone "{tz}" and offset_minutes [1] when the user says "in 1 minute" (use [2] for 2 minutes, etc.; integer 2 also works).',
        "2. Recurring jobs: set `rrule` (FREQ=HOURLY;INTERVAL=N or FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30).",
        "3. One-shot or delayed runs: set `next_run_at` to the exact `in_Nmin_utc` value from current_time (ISO8601 UTC) and use a far-future placeholder rrule such as FREQ=HOURLY;INTERVAL=8760.",
        "4. Call `automation_create` with name, prompt (the task to run), rrule, optional next_run_at/cwds, and delivery when the user wants results sent.",
        f"5. Confirm the automation id, schedule, and delivery target in plain language. Quote the exact `in_Nmin_local` string from current_time for the run time in {tz} — never guess or use UTC-only.",
        f"User timezone: {tz}. Re-call current_time if more than 30 seconds pass before automation_create.",
        "Feishu delivery is required. Do NOT ask the user for open_chat_id — use this configured target.",
        "You MUST pass delivery exactly as:",
        f'{{"mode":"feishu","to":"{FEISHU_CHAT}","best_effort":true}}',
        f"Workspace cwd for the task: {WORKSPACE}",
    ]
    return (
        "[Scheduled automation request]\n\n"
        + "\n".join(hints)
        + "\n\n---\n[Current user request]\n"
        + user_text.strip()
    )


def api(method: str, path: str, body: dict | None = None, timeout: float = 300.0) -> dict:
    url = f"{BASE}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def wait_turn(thread_id: str, turn_id: str, timeout_s: float = 180.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        thread = api("GET", f"/v1/threads/{thread_id}")
        turns = thread.get("turns") or []
        turn = next((t for t in turns if t.get("id") == turn_id), None)
        if turn and turn.get("status") in ("completed", "failed", "interrupted"):
            return turn
        time.sleep(2)
    raise TimeoutError(f"turn {turn_id} not finished in {timeout_s}s")


def main() -> int:
    print("health:", api("GET", "/health"))
    automations_before = api("GET", "/v1/automations")
    print(f"automations before: {len(automations_before)}")

    results: list[dict] = []
    for i, user_text in enumerate(REQUESTS, 1):
        print(f"\n=== [{i}/3] {user_text} ===")
        thread = api(
            "POST",
            "/v1/threads",
            {
                "model": MODEL,
                "workspace": WORKSPACE,
                "mode": "agent",
                "auto_approve": True,
            },
        )
        tid = thread["id"]
        print("thread:", tid)
        started = api(
            "POST",
            f"/v1/threads/{tid}/turns",
            {"prompt": build_prompt(user_text), "model": MODEL, "auto_approve": True},
        )
        turn = started["turn"]
        turn_id = turn["id"]
        print("turn started:", turn_id, "status:", turn.get("status"))
        final = wait_turn(tid, turn_id)
        print("turn done:", final.get("status"), "error:", final.get("error"))
        results.append({"thread_id": tid, "turn_id": turn_id, "user_text": user_text, **final})

    automations_after = api("GET", "/v1/automations")
    print(f"\nautomations after: {len(automations_after)}")
    for a in automations_after:
        print(
            " -",
            a.get("id"),
            a.get("name"),
            "next_run_at=",
            a.get("next_run_at"),
            "status=",
            a.get("status"),
        )

    out = Path("/Users/fjw/Desktop/deepseek-tui-py-main/.deepseek/e2e_three_automations.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"turns": results, "automations": automations_after}, ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print("API error:", exc, file=sys.stderr)
        raise SystemExit(1)
