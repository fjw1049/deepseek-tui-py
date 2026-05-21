#!/bin/sh
# Lifecycle hook: read a policy document before each tool call.
#
# Usage in config.toml:
#   command = "sh /path/to/pre_tool_check_doc.sh /path/to/TOOL_POLICY.md /path/to/audit.log"
#
# Expects DEEPSEEK_TOOL_NAME (and optionally DEEPSEEK_TOOL_ARGS) from HookExecutor.

set -eu

POLICY_DOC="${1:-}"
AUDIT_LOG="${2:-}"

if [ -z "$POLICY_DOC" ] || [ -z "$AUDIT_LOG" ]; then
  echo "usage: pre_tool_check_doc.sh <policy.md> <audit.log>" >&2
  exit 2
fi

if [ ! -f "$POLICY_DOC" ]; then
  echo "policy document missing: $POLICY_DOC" >&2
  exit 2
fi

TITLE=$(head -n 1 "$POLICY_DOC" | tr -d '\r')
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TOOL="${DEEPSEEK_TOOL_NAME:-unknown}"
echo "${TS} tool=${TOOL} policy=${TITLE}" >> "$AUDIT_LOG"
exit 0
