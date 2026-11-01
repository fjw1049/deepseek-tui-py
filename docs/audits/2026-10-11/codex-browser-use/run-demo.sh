#!/bin/sh
set -eu
cd "$(dirname "$0")/replica"
bundled_node=/Users/fjw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node
if [ -x "$bundled_node" ]; then
  demo_node="$bundled_node"
else
  demo_node=node
fi
installed_playwright=/Users/fjw/.local/share/rea/node_modules/playwright-core
if [ ! -d node_modules/playwright-core ] && [ -d "$installed_playwright" ]; then
  export PLAYWRIGHT_MODULE_PATH="$installed_playwright"
fi
exec "$demo_node" browser-use.mjs --demo
