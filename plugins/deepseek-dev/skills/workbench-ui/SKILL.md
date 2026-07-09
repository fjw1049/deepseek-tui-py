---
name: workbench-ui
description: >
  Workbench (Electron + React) UI development for DeepSeek GUI. Use when
  editing packages/workbench, Extensions pages (Plugins/Skills/Connectors),
  Sidebar, FloatingComposer, chat store, locales, or GUI ↔ runtime API wiring.
---

# workbench-ui

## Layout

| Concern | Path |
|---|---|
| Shell / routes | `packages/workbench/src/renderer/src/components/Workbench.tsx` |
| Sidebar nav | `packages/workbench/src/renderer/src/components/chat/Sidebar.tsx` |
| Composer + skill focus chip | `packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx` |
| `/skills` panel | `packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx` |
| Plugins page | `packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx` |
| Skills page | `packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx` |
| Connectors page | `packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx` |
| Chat store / routes | `packages/workbench/src/renderer/src/store/` |
| i18n | `packages/workbench/src/renderer/src/locales/{zh,en}/common.json` |
| Feature flags | `packages/workbench/src/shared/workbench-features.ts` |

## Conventions

- Extensions live under route `plugins` | `skills` | `connectors`; sidebar label is「应用拓展」.
- Skill focus: picking a skill sets a chip; on send the composer prepends `/skill-name ` so the runtime enters focus mode.
- Runtime calls go through `window.dsGui.runtimeRequest(path, method, body?)` to the Python FastAPI server (`/v1/...`).
- Plugin mutations must surface the hint that **changes apply to new sessions**.
- When adding UI copy, update **both** `zh/common.json` and `en/common.json`.
- Prefer existing Tailwind/`ds-*` tokens and patterns in neighboring components; do not invent a new design system.
- Keep components surgical: no drive-by refactors of Workbench.tsx unless required.

## API surfaces you will touch most

| UI need | API |
|---|---|
| List/install/trust plugins | `/v1/plugins`, `/v1/plugins/install`, `/v1/plugins/{name}/action` |
| List skills for composer | `/v1/skills` |
| MCP connectors | `/v1/mcp` (and related) |

## Verify

- Type-safe edits; match existing React patterns (lazy routes, zustand store).
- Manually: open Extensions → Plugins, confirm list; in chat open skills panel and confirm new skill names appear after a **new** session.
