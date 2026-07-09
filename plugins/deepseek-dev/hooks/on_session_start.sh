#!/bin/sh
# deepseek-dev session_start hook — write a small context snapshot the agent
# (or a human) can read. Also prints a one-line summary to stdout for logs.
set -eu

PLUGIN_ROOT="${PLUGIN_DIR:-$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)}"
OUT_DIR="${PLUGIN_ROOT}/.runtime"
OUT_FILE="${OUT_DIR}/session_context.md"
mkdir -p "$OUT_DIR"

WS="${DEEPSEEK_WORKSPACE:-${DEEPSEEK_CWD:-$PWD}}"
cd "$WS" 2>/dev/null || true

BRANCH="?"
SHORT_STAT="(not a git checkout)"
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  SHORT_STAT="$(git status -sb 2>/dev/null | head -n 12 || true)"
fi

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat >"$OUT_FILE" <<EOF
# deepseek-dev session context

* time_utc: ${TS}
* workspace: ${WS}
* branch: ${BRANCH}
* session_id: ${DEEPSEEK_SESSION_ID:-}
* model: ${DEEPSEEK_MODEL:-}
* event: ${DEEPSEEK_EVENT:-session_start}

## git status (short)

\`\`\`
${SHORT_STAT}
\`\`\`

## plugin skills to focus in composer

* \`/deepseek-dev\` — default umbrella
* \`/workbench-ui\` — GUI / Extensions / composer
* \`/plugin-system\` — plugins.py / trust / contributions
* \`/python-runtime\` — engine / MCP / server / pytest
EOF

echo "DEEPSEEK_DEV_OK branch=${BRANCH} context=${OUT_FILE}"
