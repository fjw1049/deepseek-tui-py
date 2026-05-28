#!/usr/bin/env bash
# Start Feishu/Lark long-connection bridge (chat control from phone).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE="${FEISHU_BRIDGE_DIR:-$ROOT/docs/CodeWhale-main/integrations/feishu-bridge}"

if [[ ! -f "$BRIDGE/package.json" ]]; then
  echo "feishu-bridge not found at: $BRIDGE" >&2
  echo "Set FEISHU_BRIDGE_DIR or clone CodeWhale integrations." >&2
  exit 1
fi

cd "$BRIDGE"
if [[ ! -d node_modules ]]; then
  echo "Installing feishu-bridge dependencies..."
  npm install --omit=dev
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit FEISHU_APP_ID, DEEPSEEK_RUNTIME_TOKEN, etc."
  else
    echo "Missing .env in $BRIDGE" >&2
    exit 1
  fi
fi

echo "Starting Feishu bridge from $BRIDGE"
exec node src/index.mjs
