# DeepSeek TUI × TencentDB Agent Memory — 统一集成设计

> 合并方案1/2/3 + 评审修订（2026-05-29 **v3**）  
> 本文档为实施规格，不含实现代码。v2 已可进入 P1；v3 为第二轮评审微调（非阻塞）。  
> **P1 逐文件 PR 清单**：[MEMORY_INTEGRATION_P1_CHECKLIST.md](./MEMORY_INTEGRATION_P1_CHECKLIST.md)  
> **延后 / 集中测试**：[MEMORY_INTEGRATION_BACKLOG.md](./MEMORY_INTEGRATION_BACKLOG.md)

### 修订记录

| 版本 | 变更 |
|------|------|
| v2 | P1 默认 Native；workspace；质量门控；recall 进 `build_system_prompt` |
| v3 | 门控阈值 20 + AND 语义写清；`inject_position` 预留；L1 时间衰减 + schema 时间字段 |

---

## 1. 目标与原则

### 1.1 要解决的问题

| 层次 | 现状 | 目标 |
|------|------|------|
| **跨会话** | `memory.md` 整文件注入 + `remember` 追加 | 结构化 L0→L1→…、混合检索、按需注入 |
| **单会话** | compaction + spillover + WorkingSet（已成熟） | **保持**，不替换 |
| **可审计** | 记忆来源不透明 | 事实可下钻到 L0 原话 / ref |

### 1.2 核心思想（泛化公式）

**记忆 ≠ 聊天记录摘要**，而是：

1. **原始证据可追溯**（L0 / refs / spillover 文件）
2. **高层知识可召回**（L1 原子、L2 场景、L3 Persona）
3. **当前上下文只注入最相关部分**（Recall 限条数 + 工具主动查）
4. **记住什么比怎么记更重要**（质量门控，避免 L1 成噪声堆）

会话内减压与跨会话记忆**分层并行**：

- **长期记忆层**：懂用户、懂项目、懂踩坑
- **会话减压层**：本轮别爆窗（compaction + spillover；**不上 OpenClaw Offload**）

### 1.3 设计原则

1. **宿主为主**：`Engine` 主循环不被记忆逻辑改写。
2. **接口优先**：`MemoryProvider` 可替换；**默认 Native（纯 Python）**，Sidecar 仅作可选后端。
3. **单一技术栈**：`pip install` 即可用，不强制 Node（泛化到 Python CLI / Workbench 用户）。
4. **单一 Prompt 组装点**：`build_system_prompt` 是唯一 system 拼装入口（含 recall 稳定层）。
5. **多项目信号**：`workspace` 贯穿 recall / capture / 检索加权。
6. **默认关闭**：`enabled=false` 或 `mode=manual` 时与现网一致。
7. **失败不阻塞**：Recall 超时跳过；Capture 失败只打日志。

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                     deepseek-tui（宿主）                          │
│  ThreadManager ──► Engine                                         │
│       │                │                                          │
│       │                ├── coordinator.recall(workspace=…)        │
│       │                ├── build_system_prompt(memory_recall=…)  │  ← 唯一拼装点
│       │                └── TurnComplete → capture (门控后)        │
│       └── thread 销毁 ──► flush_session                           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ MemoryCoordinator
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  MemoryProvider（默认）NativeMemoryProvider  P1: L0+L1+FTS recall │
│  MemoryProvider（可选）SidecarTdaiProvider   需 Node + Gateway    │
└──────────────────────────────────────────────────────────────────┘

并行保留：compaction · spillover · handoff.md · WorkingSet · project_context
```

---

## 3. MemoryProvider 协议（接口草案）

```python
@dataclass
class RecallResult:
    l1_context: str | None          # 动态：本轮 L1 命中正文
    append_system: str | None       # 稳定：L3 + L2 导航 + 工具指南（进 system 静态区）
    inject_position: Literal["user", "system_volatile"] = "user"
    # user：包进当前 user（默认，对齐 TencentDB prependContext）
    # system_volatile：进 system 的 volatile 区（handoff 后），供 cache 友好场景选配
    strategy: str = "skipped"
    timed_out: bool = False

@dataclass
class CaptureInput:
    thread_id: str
    user_text: str
    messages: list[dict]
    workspace: str | None          # 绝对路径，用于 L1 元数据与 recall 加权
    had_tool_calls: bool           # 门控信号
    success: bool

class MemoryProvider(Protocol):
    async def recall(
        self,
        thread_id: str,
        user_text: str,
        *,
        workspace: str | None = None,
        timeout_ms: int = 5000,
    ) -> RecallResult: ...

    async def capture(self, inp: CaptureInput) -> None: ...

    async def flush_session(self, thread_id: str) -> None: ...

    async def search_memories(
        self,
        query: str,
        *,
        workspace: str | None = None,
        limit: int = 5,
        type: str | None = None,
    ) -> str: ...

    async def search_conversations(
        self,
        query: str,
        *,
        workspace: str | None = None,
        thread_id: str | None = None,
        limit: int = 5,
    ) -> str: ...
```

### 3.1 P1 实现（默认）：NativeMemoryProvider

**范围（刻意收窄）**

| 包含 | 不包含（后续阶段） |
|------|-------------------|
| L0 JSONL 增量录制 | L2 场景 Agent |
| 后台 L1 提取（复用 `LLMClient`） | L3 Persona 自动生成 |
| SQLite + FTS5 关键词 recall | embedding / hybrid RRF |
| `append_system` 仅 persona 占位或读已有 `persona.md`（若空则跳过） | TCVDB 云端 |

**存储**：`~/.deepseek/memory_data/`（与 `memory-tdai` 命名二选一，实现时统一）

- `l0/{thread_id}.jsonl`
- `store/memory.db`（L1 + FTS5）
- L1 元数据字段：`workspace`、`confidence`、`type`（persona | episodic | instruction）
- **时间字段（P1 必做）**：`created_at`、`updated_at`、`last_recalled_at`（见 §3.4）

**工期**：L0 + L1 + FTS recall + Engine 挂接 ≈ **1–2 周**（不含 L2/L3）。

**实现参考**：逻辑可对齐 TencentDB 的 `sanitize.ts`、`l0-recorder.ts`、`l1-extractor` 行为，在 Python 中移植子集，避免行为漂移。

### 3.2 记忆质量门控（Coordinator + Provider 共识）

> 「记住什么」优先于「怎么记」。门控分两层：**进 L0 前**（Coordinator）、**进 L1 前**（Provider/提取器）。

#### A. Capture 前（MemoryCoordinator.should_capture_turn）

在调用 `Provider.capture` 之前判断，满足任一则 **跳过本 turn**：

| 规则 | 说明 |
|------|------|
| 用户文本过短 | **`len(user_text.strip()) < capture_min_user_chars` 且本轮无 tool calls**（默认 20，非 50） |
| 有 tool calls | **`had_tool_calls=True` 时无条件 capture**（与上条 AND，不矛盾） |
| Slash 命令 | 以 `/` 开头（`/compact`、`/clear` 等） |
| 纯确认语 | 匹配简单模式（如仅「好」「继续」「ok」）— 可配置 |
| turn 失败 / 取消 | `success=False` |

> **多语言说明**：P1 用字符数启发式；中文信息密度高于英文，50 字门槛会误杀「帮我把这个函数改成 async」类短指令。P2 可选改为按 token 估算（复用 engine 已有 token 工具）。

#### B. L0 写入（对齐 TencentDB `shouldCaptureL0`）

- 剥离 `<relevant-memories>`、过长 base64、空内容
- 单条消息长度下限（参考 TencentDB sanitize）

#### C. L1 提取（对齐 `shouldExtractL1`）

- 仅对通过 L0 质量的消息批次调用 LLM
- Prompt 限定：只输出 persona / episodic / instruction
- 每条记忆带 `confidence`（0–1），默认阈值 **0.6** 以下丢弃
- 去重：P1 用 FTS 相似 + 文本 hash；P2 再升级 embedding

#### D. Recall 注入（对齐 `scoreThreshold`）

- 检索结果 score < 配置阈值（默认 0.3）不进入 `l1_context`
- `workspace` 匹配时加分：同 workspace 的 L1 优先排序
- 命中并注入后更新该条 `last_recalled_at`

### 3.4 记忆时间衰减（P1 纳入 schema + recall 排序）

P1 无 L2/L3 时，L1 会长期堆积，需防止过时事实（如「在用 React 17」）靠 FTS 命中误导模型。

**Schema（`memories` 表，P1 创建）**

| 字段 | 用途 |
|------|------|
| `created_at` | 写入时间 |
| `updated_at` | merge/update 时间 |
| `last_recalled_at` | 上次被注入上下文的时间（可为 NULL） |

**Recall 排序（P1 在 SQLite 层完成）**

```text
final_score = fts_score
            × workspace_boost(workspace)    # 同 workspace ×1.2，无关 ×1.0
            × time_decay(created_at)        # 半衰期默认 180 天
```

半衰期公式（简单、可配置）：

```text
time_decay = 0.5 ^ (age_days / l1_decay_half_life_days)
```

- 配置：`l1_decay_half_life_days = 180`（0 = 关闭衰减）
- P3 可由 L2/L3 重写隐式「刷新」记忆；P1 用衰减兜底即可

---

## 4. 宿主集成点

### 4.1 Turn 前 — Recall + Prompt 组装（优化4）

**文件**：`engine.py` — `_handle_send_message_inner`

```text
user_text = processed.model_text
workspace = str(engine.tool_context.working_directory.resolve())

memory_recall = None
if coordinator.enabled_for_mode(...):
    memory_recall = await coordinator.recall(
        thread_id, user_text, workspace=workspace,
    )

system_prompt = build_system_prompt(
    ...,
    memory_enabled=...,           # hybrid 时仍可读 memory.md
    memory_recall=memory_recall,  # 新增：在函数内部拼装
    workspace=workspace,
)

# 动态 L1：仅注入「当前 turn」，绝不改写 session_messages 里的历史 user
if memory_recall and memory_recall.l1_context:
    if memory_recall.inject_position == "user":
        user_message = wrap_relevant_memories(user_message, memory_recall.l1_context)
    # else: 已在 build_system_prompt 内注入 volatile 区

system_prompt = build_system_prompt(..., memory_recall=memory_recall, ...)
```

**`build_system_prompt` 内部分层（与现有 Rust parity 一致）**

```text
1. mode + personality
2. project_context（workspace 静态）
3. ## Environment
4. ── 记忆稳定层（KV-friendly）──
   memory_recall.append_system        # L3 + L2 导航（若有；L3 未生成前留空）
5. Context Management + skills + compact template
6. ── volatile 边界 ──
7. handoff.md
8. memory_recall.l1_context          # 仅当 inject_position == "system_volatile"
9. memory.md（hybrid）
10. working_set_summary
```

**禁止**：在 `Engine` 里对 `system_prompt` 做 `+=` 拼接（单一职责）。

**KV cache 说明（回应评审 #2）**

- 默认 `inject_position=user`：只改变**本轮** user 内容，**不修改**历史 messages，因此不会导致「前几轮 user cache 全部失效」。
- 若产品侧更关注 system 前缀稳定性，可配 `inject_position=system_volatile`，把 L1 放在 handoff 之后（system 尾部每轮会变，与 TencentDB 把动态块放 user 的策略不同，需 A/B）。
- P1 实现 `user` 即可；`system_volatile` 为配置预留。

**持久化**：无论注入位置，写入 DB 前剥离 `<relevant-memories>`。

### 4.2 Turn 后 — Capture（含门控）

```text
if coordinator.should_capture_turn(user_text, had_tool_calls, success):
    await coordinator.capture(CaptureInput(
        thread_id=..., user_text=..., messages=...,
        workspace=workspace, had_tool_calls=..., success=True,
    ))
```

### 4.3 Thread 结束 — Flush

`thread_manager` 淘汰/归档/删除 thread 时：`flush_session(thread_id)`。禁止全局 destroy。

### 4.4 Config

```toml
[memory]
enabled = false
mode = "manual"              # manual | auto | hybrid（推荐默认 hybrid）
max_entries = 500

[memory.smart]               # 智能记忆（Native 本地，~/.deepseek/memory_data）
enabled = false
data_dir = ""                # 默认 ~/.deepseek/memory_data
hybrid_search = true         # FTS + LIKE + RRF（无 embedding 时）

recall_enabled = true
capture_enabled = true
recall_timeout_ms = 5000
recall_score_threshold = 0.3

# 仅当 len(user_text) < 此值 且 本轮无 tool calls 时跳过 capture（AND）
capture_min_user_chars = 20
capture_skip_slash_commands = true

l1_every_n = 5
l1_idle_timeout_seconds = 600
l1_confidence_min = 0.6
l1_max_per_session = 20   # per thread_id; long-lived threads may need 50+
l1_decay_half_life_days = 180   # 0 = 关闭时间衰减

# P1 默认 user；可选 system_volatile（见 §4.1）
l1_inject_position = "user"

embedding_provider = "openai"   # none | openai
embedding_model = "text-embedding-3-large"
embedding_base_url = "https://api.example.com"
embedding_api_key = ""          # or DEEPSEEK_EMBEDDING_API_KEY
embedding_dedup_threshold = 0.92
embedding_timeout_ms = 90000
```

### 4.5 Agent 工具（P2）

`memory_search` / `conversation_search`，参数含 `workspace`（默认当前 cwd）。

---

## 5. 数据与作用域

| 数据 | 路径 | 作用域 | 说明 |
|------|------|--------|------|
| 智能记忆 | `~/.deepseek/memory_data/` | 用户 | L0/L1/store |
| 快速笔记 | `~/.deepseek/memory.md` | 用户 | hybrid 补充 |
| handoff | `<workspace>/.deepseek/handoff.md` | **项目** | 进行中任务 |
| transcript | `state.db` | 线程 | UI 权威 |
| L1 元数据 | `workspace` 列 | 过滤/加权 | 多仓库用户必备 |

### thread_id 约定（SSOT）

| 宿主 | `memory_thread_id` 来源 |
|------|-------------------------|
| Workbench | `ThreadRecord.id`（`thr_*`） |
| TUI | `--resume` / `--fork` 的 session id，否则 `cycle_session_id` |

`memory_mode`：Workbench 来自 `ThreadRecord`；TUI resume 读 session JSON `metadata.memory_mode`。

---

## 6. 分阶段路线图与验收标准

### P1 — Native 最小闭环（**默认路径**）

**交付**

1. `MemoryProvider` + `NativeMemoryProvider`（L0+L1+FTS）
2. `MemoryCoordinator`（门控 + recall/capture/flush）
3. `build_system_prompt(memory_recall=…)` 分层注入
4. `workspace` 全链路传递
5. Config `[memory.smart]`

**验收**

| # | 操作 | 预期 |
|---|------|------|
| 1 | `memory.smart.enabled=false` | 与现网一致 |
| 2 | `hybrid` + 5 轮有实质对话 | `memory_data/l0/` 有 JSONL；L1 表有记录 |
| 3 | 多 workspace 两项目各聊不同话题 | 在 B 项目 recall 不注入 A 项目专属事实（workspace 过滤） |
| 4 | 连续 3 轮「好的」「继续」无 tool | 不触发 capture（或 L0 无增长） |
| 4b | 短指令「帮我把这个函数改成 async」+ 有 tool | **应** capture（验证门槛 20 与 had_tool_calls 规则） |
| 5 | 新 thread 问上轮事实 | `l1_context` 注入 / 回答正确 |
| 8b | 插入 200 天前的 L1，另有近期同类记忆 | recall 排序偏近期（时间衰减） |
| 6 | 检查 system prompt 层位 | L3/导航在 Environment 后、handoff 前 |
| 7 | 持久化 user 消息 | 无 `<relevant-memories>` 残留 |

**不要求**：Node、Gateway、embedding、L2/L3。

### P2 — 语义与工具

- ✅ embedding + hybrid RRF（FTS + LIKE + 向量，RRF 合并）
- ✅ `memory_search` / `conversation_search`（`tools/memory_tools.py`，需 `[memory.smart] enabled`）
- ✅ `remember` → L1 instruction 双写（smart + `memory.enabled` 时）
- ✅ `memory_mode` per-thread（`ThreadRecord` + `UpdateThreadRequest` + Engine）
- ⚠️ L1 语义去重：hash + 前缀近似（无 embedding 向量去重）

### P3 — 归纳层（Native 已实现）

- ✅ L2 场景块（`scene_blocks/` + recall 导航）
- ✅ L3 Persona（`persona.md` 自 L1 persona 行刷新）

### P4 — 刻意不做

- Sidecar / TencentDB Gateway（deepseek-tui 仅 Native）
- TCVDB / spillover（非 Offload）

---

## 7. 刻意不做清单

（不变）不替换 SQLite transcript；不第一期 Offload；不每 tool 后 L1；不关 compaction；不默认 TCVDB。

---

## 8. 决策结论（原 §8 已关闭）

| 项 | v2 结论 |
|----|---------|
| P1 技术栈 | **默认 B：纯 Python Native** |
| Sidecar | 可选，`provider=sidecar`，服务要完整栈/Tencent 云的用户 |
| workspace | **必选** recall/capture 参数 |
| Prompt | **recall 进 build_system_prompt** |
| 质量 | **Coordinator 门控 + L1 confidence** |

---

## 9. 文件布局（P1 优先）

实施顺序与逐 PR 改动见 [MEMORY_INTEGRATION_P1_CHECKLIST.md](./MEMORY_INTEGRATION_P1_CHECKLIST.md)。

```
src/deepseek_tui/memory/
├── user_memory.py
├── provider.py
├── coordinator.py          # 含 should_capture_turn
├── gates.py              # 门控规则（可测）
├── native/
│   ├── provider.py       # NativeMemoryProvider
│   ├── l0_recorder.py
│   ├── l1_extractor.py
│   ├── scheduler.py
│   └── store/sqlite_store.py
├── sidecar_provider.py   # 可选，P4
└── supervisor.py         # 可选，P4

engine/prompts.py         # 扩展 memory_recall 参数与分层
```

---

## 10. 评审对照

### 第一轮（v2）

| 优化点 | 采纳 |
|--------|------|
| P1 纯 Python 默认 | ✅ |
| workspace | ✅ |
| 质量门控 | ✅ |
| prompt 内化 | ✅ |

### 第二轮（v3，锦上添花）

| 建议 | 采纳 | 说明 |
|------|------|------|
| `capture_min_user_chars` 50→20 | ✅ | 写清 **AND** + `had_tool_calls` 豁免；config 注释防误读 |
| `inject_position` 预留 | ✅ | 默认 `user`；澄清「只改当前 turn」与 cache 关系 |
| L1 时间衰减 + 时间字段 | ✅ | **纳入 P1 schema**，SQL 加权零额外服务 |

**保留意见**

1. Sidecar 仍作可选 `MemoryProvider`。
2. 实现体量预留 **800–1200 行**（含测试）。
3. L3 未生成前 `append_system` 留空。
4. **按 token 门控** 放 P2；P1 字符数 + tool 豁免已覆盖中文短指令主场景。
5. `system_volatile` 是否更利于 cache **尚无定论**（变动在 system 尾部 vs user 当前条）；以配置开关做实验，不在 P1 强推。

### 评审评分（认同 Claude 结论）

| 维度 | v3 自评 | 说明 |
|------|---------|------|
| 实用性 | 9/10 | 验收 #4b/#8b 覆盖中文短指令与过期记忆 |
| 通用性 | 9/10 | Protocol + 可选 sidecar / inject_position |
| 泛化性 | **9/10**（v2 为 8） | 补时间衰减与多语言门槛 |

**结论：v3 可进入 P1 实施；上述 3 点非阻塞，其中时间字段建议 P1 建表时一次性带上。**

---

## 11. 一句话总结（v3）

**默认 Native（L0+L1+FTS+门控+workspace+时间衰减），recall 分层注入 `build_system_prompt`，动态 L1 默认仅进当前 user；Sidecar 可选。**

下一步：P1 逐文件 PR 清单（按 v3）。
