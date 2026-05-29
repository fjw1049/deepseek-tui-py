# Workbench 宠物 Mascot — 设计（v2，合并 Codex review）

> 目标：输入框上方固定区域显示 Petdex 格式 spritesheet 宠物，随 Agent 生命周期切换动画。  
> **原则：装饰性增强——失败时静默降级，绝不阻塞 Composer。**

---

## 0. 与 v1 方案的主要差异

| 点 | v1（Cursor 初稿） | v2（采纳 Codex review 后） |
|----|-------------------|---------------------------|
| Phase 0 | CSP + 在线 manifest | **本地/内置 pet，零网络、零 CSP** |
| chat-store | 完全不动，纯推导 | 核心语义不动；**可选极小 `petEvents` 通道** |
| failed 态 | 历史 failed tool block | **仅当前 turn / 刚发生 error** |
| burst 优先级 | burst 最高 | **waiting/failed 高于 decorative burst** |
| 状态切换 | 即时 | **最短停留 ~300ms，防闪烁** |
| 在线资源 | Phase 0 阻塞项 | **Phase 2**；main IPC + allowlist + 缓存 |
| 失败降级 | 未强调 | **显式：隐藏或回退内置 pet** |

---

## 1. 架构总览

```
ComposerStage                    ← 薄 wrapper，只包 FloatingComposer 上方
├── PetMascotDock               ← ~112px，overflow:hidden，pointer-events 克制
│   └── PetSprite               ← CSS steps()，src 来自本地 asset 或 blob
└── FloatingComposer            ← 现有组件，行为不变

usePetController()
├── 订阅 chat-store（busy, blocks, liveReasoning, error, currentTurnId）
├── 订阅 petEvents（边沿：user_message / turn_complete / turn_error）
├── 状态机：sustained + decorative burst + minDwellMs
└── 输出 { stateId, visible, status: 'ready'|'fallback'|'hidden' }

petEvents（Phase 1，极小扩展）
└── chat-store 在 ThreadEventSink 三处 emit，不改编排语义
```

**明确不做（Phase 0–1）：** Python engine、sidecar、改 MessageTimeline 布局、在线 manifest。

---

## 2. 分阶段交付

### Phase 0A — 本地静态宠物（~0.5–1 天）

**目的：** 验证位置、尺寸、不挡输入、双布局（空会话 / 正常聊天）。

| 项 | 内容 |
|----|------|
| 资产 | `packages/workbench/asset/pet/demo-spritesheet.webp`（或从 Petdex 复制一只到 repo） |
| 导入 | `import demoSheet from '../../../asset/pet/demo-spritesheet.webp'` → Vite 打包，`img-src 'self'` 够用 |
| 组件 | `PetSprite`、`PetMascotDock`、`ComposerStage` |
| 状态 | 硬编码 `idle`，不接 store |
| 改动 | `Workbench.tsx` 两处 composer → `ComposerStage`；`index.css` 动画规则 |
| **不改** | `index.html` CSP、chat-store、main IPC |

**验收：**

- [ ] 输入框上方 idle 循环
- [ ] 空会话 + 正常聊天布局均有宠物
- [ ] textarea 可聚焦、可点击，宠物不抢事件
- [ ] 保留 `ds-chat-stage` / `ds-no-drag` 现有规则

---

### Phase 1 — 状态机 + petEvents（~1–1.5 天）

**目的：** 随 Agent 生命周期切换动作，边沿可靠、不闪烁。

#### 2.1 petEvents 通道（推荐，比纯推导稳）

在 `buildThreadEventSink` 内 **只追加** 三行 emit，不改 blocks/busy 逻辑：

```ts
// chat-store-types.ts
export type PetEventKind = 'user_message' | 'turn_complete' | 'turn_error'

// chat-store.ts — 独立模块或 store 切片
let petEventListeners = new Set<(e: PetEventKind) => void>()
export function subscribePetEvents(fn: (e: PetEventKind) => void): () => void { ... }
function emitPetEvent(kind: PetEventKind): void { ... }

// ThreadEventSink 内：
onUserMessage: (...) => { ...; emitPetEvent('user_message') }
onTurnComplete: () => { ...; emitPetEvent('turn_complete') }
onError: (err) => { ...; emitPetEvent('turn_error') }
```

`usePetController` 订阅 `subscribePetEvents`，触发 **decorative burst** 或 **sustained failed**。

> 若坚持零 touch chat-store：可在 `ComposerStage` 包装 `onSend` 处理 `user_message`；但 `turn_complete` / `turn_error` 仍建议 petEvents，否则要靠 `busy` 下降沿猜测，易丢 wave。

#### 2.2 状态优先级（修正版）

**Tier A — 必须即时反映（覆盖一切 decorative burst）：**

| 条件 | 状态 |
|------|------|
| `turn_error` 边沿，或 **当前 turn** 内有 tool `status==='error'` | `failed` |
| approval / elevation / user_input **pending** | `waiting` |

**Tier B — sustained（busy 期间）：**

| 条件 | 状态 |
|------|------|
| 最新 **running** 工具且 read-like | `review` |
| `busy && liveReasoning` 且无 running tool | `review` |
| `busy` | `running` |
| 默认 | `idle` |

**Tier C — decorative burst（仅当 Tier A/B 为 idle 或 running 时生效）：**

| 触发 | 状态 | 时长 |
|------|------|------|
| `user_message` | `jumping` | 840ms |
| `turn_complete` | `waving` | 700ms |
| `/pet wave`（Phase 3） | `waving` | 700ms |

**规则：**

- `waiting` / `failed` **不可**被 Tier C burst 覆盖
- `failed` **只看** `currentTurnId` 窗口内 tool error + `turn_error` 边沿；**不**扫历史 blocks
- `turn_complete` 后：先 `waving`（Tier C），再回 Tier B/idle
- **minDwellMs = 300**：状态变更后至少展示 300ms 再切（防多工具并发闪烁）

#### 2.3 Phase 1 文件

| 新增/改 | 文件 |
|---------|------|
| + | `hooks/use-pet-controller.ts` + test |
| + | `lib/pet/pet-states.ts` |
| ~ | `store/chat-store.ts`（petEvents emit，~15 行） |
| ~ | `store/chat-store-types.ts`（PetEventKind） |
| ~ | `ComposerStage.tsx`（接 controller） |

**验收：** §7 清单（除 manifest 相关）。

---

### Phase 2 — 在线 manifest + 安全加载（~1.5–2 天）

**目的：** 从 Petdex 选宠物；离线/失败可降级。

| 项 | 做法 |
|----|------|
| 加载 | **main IPC** fetch manifest + spritesheet；renderer 只拿 `blob:` |
| Allowlist | main 侧校验 host：`petdex.crafter.run`、`*.r2.dev`（可配置） |
| 缓存 | `userData/pet-cache/{slug}.webp` |
| UI | Settings → General → Desktop pet 右侧选择区；dock 只显示动画，不提供选择入口 |
| CSP | 仍可不放宽；或仅加 `connect-src` 若 renderer 直 fetch（不推荐） |

**失败降级（必须）：**

```
manifest 失败 → 继续用内置 demo pet，status='fallback'
spritesheet 失败 → 同上；Dock 不显示 error 阻断层
用户 enabled=false → status='hidden'
任何情况 → FloatingComposer 100% 可用
```

**当前实现约定：**

- Settings 打开 General 后通过 main IPC 预缓存 manifest 前 15 个宠物到 `userData/pet-cache/`。
- Renderer 只持久化 `deepseekgui.pet.slug` / `deepseekgui.pet.enabled`。
- 输入框上方不放选择按钮，避免干扰 composer；切换入口统一放在 Settings。

---

### Phase 3 — 增强（按需）

- `/pet wave`、`/pet jump`、`/pet wake`、`/pet tuck`（Tier C，仍低于 waiting/failed）
- `/pet` 单独提交 → 切换显示/隐藏
- Settings → General → Desktop pet 开关（localStorage 同步）
- dock 内 idle 漫步 + `running-left` / `running-right`
- 离线仅缓存 pet
- 可选：Python SSE `pet_hint`（仅 TUI 也要宠物时）

---

## 3. CSP（仅 Phase 2 需要）

Phase 0A/1 **不需要改 CSP**（内置 asset）。

Phase 2 首选 **main IPC**，renderer CSP 保持：

```html
img-src 'self' data: blob:;
connect-src 'self';
```

备选快速路径（不推荐生产）：放宽 `connect-src` + R2 `img-src`（见 v1 §3.2）。

---

## 4. ComposerStage 实现约束

```tsx
// 只做两件事：上方 Dock + 下方原 Composer，props 原样透传
export function ComposerStage(props: ComponentProps<typeof FloatingComposer>) {
  const pet = usePetController()
  return (
    <div className={/* 与现 FloatingComposer 外层相同 */}>
      <PetMascotDock ... />
      <FloatingComposer {...props} />
    </div>
  )
}
```

**禁止：** 移动 approval 条、队列条、改 MessageTimeline、改 composer 宽度算法。

---

## 5. 状态机伪代码（v2）

```ts
const MIN_DWELL_MS = 300
const READ_LIKE = /\b(read|grep|glob|list_dir|search)\b/i

type Tier = 'critical' | 'sustained' | 'decorative'

function deriveCritical(input): PetStateId | null {
  if (input.turnErrorEdge) return 'failed'
  if (hasToolErrorInTurn(input.blocks, input.currentTurnId)) return 'failed'
  if (hasPendingInteractive(input.blocks)) return 'waiting'
  return null
}

function deriveSustained(input): PetStateId {
  if (!input.busy) return 'idle'
  const running = latestRunningTool(input.blocks)
  if (running && READ_LIKE.test(running.summary)) return 'review'
  if (input.liveReasoning.trim() && !running) return 'review'
  return 'running'
}

function resolveState(input, burst, lastChangeAt): PetStateId {
  const critical = deriveCritical(input)
  if (critical) return maybeDwell(critical, lastChangeAt)

  const sustained = deriveSustained(input)

  if (burst && burst.tier === 'decorative' && sustained === 'idle') {
    if (Date.now() < burst.expiresAt) return burst.stateId
  }

  return maybeDwell(sustained, lastChangeAt)
}

// petEvents →
//   user_message  → setBurst('jumping', 840, 'decorative')
//   turn_complete → setBurst('waving', 700, 'decorative')
//   turn_error    → turnErrorEdge=true until next user_message
```

---

## 6. PetMascotDock 降级 UX

| status | UI |
|--------|-----|
| `ready` | 正常动画 |
| `fallback` | 内置 demo pet + 可选小灰字「离线模式」 |
| `hidden` | 不占位或 height:0（settings 关闭） |
| 加载中 | 不占位；**不** spinner 挡 composer |

---

## 7. Phase 1 验收清单

- [ ] 空闲 idle
- [ ] 发送 → jumping → running/review
- [ ] 工具 running → running；读类 → review
- [ ] approval pending → waiting（高于 jumping）
- [ ] 当前 turn tool error → failed（历史 turn 不影响）
- [ ] turn 完成 → waving → idle
- [ ] 多工具快速切换无明显闪烁（minDwell）
- [ ] `prefers-reduced-motion` → 静态首帧
- [ ] 宠物加载失败 → fallback，composer 正常

---

## 8. 测试

| 文件 | 覆盖 |
|------|------|
| `use-pet-controller.test.ts` | waiting > jumping；failed 不读历史；minDwell |
| `pet-catalog-utils.test.ts` | Phase 2：manifest 列表过滤 |
| `pet-url-allowlist.test.ts` | Phase 2：manifest/R2 allowlist |

---

## 9. Codex review 逐条回应

| Codex 意见 | 采纳？ | 说明 |
|------------|--------|------|
| Phase 0 做重了 | ✅ | 拆 0A 本地 pet，manifest 挪 Phase 2 |
| 不动 chat-store 太绝对 | ✅ | petEvents 三处 emit，最小侵入 |
| failed/waiting/burst 细化 | ✅ | 三层 tier + minDwell + turn  scoped failed |
| CSP 应用 IPC | ✅ | Phase 2 main IPC；0A/1 不改 CSP |
| ComposerStage 要克制 | ✅ | 写进 §4 禁止项 |
| 失败降级 | ✅ | §6 显式 fallback/hidden |

---

## 10. 时间估算（修订）

| 阶段 | 时间 |
|------|------|
| Phase 0A | 0.5–1 天 |
| Phase 1 | 1–1.5 天 |
| Phase 2 | 1.5–2 天 |
| Phase 3 | 按需 |

---

*文档版本：v2 · 2026-05-29 · deepseek-tui-py / packages/workbench*
