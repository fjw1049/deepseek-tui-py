---
name: deepseek-tui-docs
description: Answer questions about DeepSeek TUI itself — its tools, modes, skills, MCP setup, automations, configuration keys, and how any feature works. Use whenever the user asks what this app can do or how to configure it.
---

# DeepSeek TUI self-reference guide

You are answering a question about DeepSeek TUI itself: its tools, modes (agent/plan/yolo/workflow), approval rules, skills, MCP servers, automations, configuration, or any other part of how this app works.

## Your knowledge of DeepSeek TUI is stale by default

DeepSeek TUI is not in your training data in any reliable form. Never answer questions about its features, commands, or configuration from memory — check a live surface first, in this order:

1. **The current session is ground truth for what exists right now.** Your system prompt's tool definitions, `## Skills` listing, and mode/approval sections are generated from the running build. If a tool or skill is not listed there, it does not exist in this session — no matter how plausible it sounds.
2. **Configuration lives in `.deepseek/config.toml`** (workspace-local) and `~/.deepseek/config.toml` (global). Read the actual file before telling the user what their settings are or where a key goes. Feature flags live under `[features]` (e.g. `automations`, `tasks`, `subagents`, `mcp`, `web_search`, `shell_tool`).
3. **MCP servers are configured in `.deepseek/mcp.json`.** Read it to answer "what MCP servers do I have".
4. **When the workspace is the deepseek-tui repository itself**, `README.md` and `docs/` are the authoritative feature documentation — read the relevant section instead of paraphrasing from memory.
5. **If none of these surfaces answer the question, say so plainly.** Tell the user the feature may not exist and where you looked. Do not invent flags, config keys, or commands.

## How to find the answer

| The user is asking about… | Check |
|---|---|
| What tools/capabilities exist | Tool definitions visible to you in this session |
| A mode (agent / plan / yolo / workflow) | Your system prompt's mode and approval sections |
| A skill | The `## Skills` listing in your system prompt |
| A config key or feature flag | `.deepseek/config.toml`, then `~/.deepseek/config.toml` |
| MCP server setup | `.deepseek/mcp.json` |
| Scheduled jobs / automations | `cron_list`, then the Workbench sidebar Automations page |
| Background tasks / sub-agents | `task_list` |
| Anything else | `README.md` / `docs/` when in the deepseek-tui repo; otherwise say what you could not verify |

## Answering style

- Be concrete: show the exact config key, TOML/JSON snippet, or tool name — not a paraphrase.
- Config snippets must be strictly valid TOML/JSON (no comments inside JSON), and say which file they go in.
- If the user's existing configuration conflicts with what they are trying to do, point it out.
- Answer in the conversation language per the `lang` field.
