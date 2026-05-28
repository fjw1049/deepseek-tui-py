#!/usr/bin/env bash
# One-shot: today's Baidu hot search → email via POST /v1/triggers.
#
# Prerequisites:
#   export DEEPSEEK_API_KEY='...'          # do NOT commit this
#   export DEEPSEEK_EMAIL_PASSWORD='...'   # SMTP app password
#   ~/.deepseek/automation/email.toml       # smtp_host, username, from_addr
#   deepseek serve --http with tasks+automations enabled in config
#
# Usage:
#   export MAIL_TO='you@example.com'
#   bash scripts/run-baidu-hotsearch-once.sh
#   bash scripts/run-baidu-hotsearch-once.sh http://127.0.0.1:8787

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY=python3
fi

BASE="${1:-http://127.0.0.1:8787}"

# Recipient: MAIL_TO env, else [automation].mail_to from config.toml
if [[ -z "${MAIL_TO:-}" ]]; then
  MAIL_TO=$(
    cd "${ROOT}" && "${PY}" -c "
from deepseek_tui.automation.inbox import default_mail_to_from_config
print(default_mail_to_from_config() or '')
" 2>/dev/null || true
  )
fi
if [[ -z "${MAIL_TO:-}" ]]; then
  echo "Set MAIL_TO or [automation].mail_to in config.toml" >&2
  exit 1
fi
export MAIL_TO

export PROMPT='你是简报助手。用 fetch_url 打开 https://top.baidu.com/board?tab=realtime ，解析今日百度热搜 Top 15（标题 + 热度若可见）。用中文编号列表输出，控制在 2000 字内。不要编造未在页面出现的内容。'
export MAIL_TO

BODY=$("${PY}" -c "
import json, os
print(json.dumps({
    'prompt': os.environ['PROMPT'],
    'triage_policy': 'skip',
    'delivery': {
        'mode': 'email',
        'to': os.environ['MAIL_TO'],
        'best_effort': True,
    },
}))
")

echo "[run-baidu-hotsearch] POST ${BASE}/v1/triggers → ${MAIL_TO}"
curl -sS -X POST "${BASE}/v1/triggers" \
  -H 'Content-Type: application/json' \
  -d "${BODY}" | "${PY}" -m json.tool

echo ""
echo "Task enqueued. Email sends in background when the agent task completes (check server logs)."
