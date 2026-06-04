# Experience Evolution 最终实现规格（定稿）

> **版本**: 1.0  
> **目标**: 在 deepseek-tui 中完整实现 Hermes 式自进化（策展记忆 + 技能演化 + 后台复盘 + 丢失前抢救），并与现有 Smart Memory（L0→L3）并行、不重复造轮子。  
> **架构定稿**: PostTurn 共享运行时 + Experience Backends + Experience Ledger  
> **遗留 / 待办**: [EXPERIENCE_EVOLUTION_BACKLOG.md](./EXPERIENCE_EVOLUTION_BACKLOG.md)

---

## 目录

1. [设计原则与红线](#1-设计原则与红线)
2. [文件清单：新增 / 修改 / 精简 / 禁止重复](#2-文件清单新增--修改--精简--禁止重复)
3. [总体架构](#3-总体架构)
4. [Layer 1：PostTurn Runtime（共享）](#4-layer-1postturn-runtime共享)
5. [Layer 2：Experience Backends（分化）](#5-layer-2experience-backends分化)
6. [Layer 3：Experience Ledger（审计与审批）](#6-layer-3experience-ledger审计与审批)
7. [工具层（主 Agent 入口）](#7-工具层主-agent-入口)
8. [Prompt 注入规范](#8-prompt-注入规范)
9. [Engine 接入（精确位置）](#9-engine-接入精确位置)
10. [配置规范](#10-配置规范)
11. [数据库迁移](#11-数据库迁移)
12. [运行时流程（逐步）](#12-运行时流程逐步)
13. [分期实现 Checklist](#13-分期实现-checklist)
14. [测试清单](#14-测试清单)
15. [反模式：禁止重复清单](#15-反模式禁止重复清单)

---

## 1. 设计原则与红线

### 1.1 核心分工

| 子系统 | 职责 | 产物 | Prompt 注入 |
|--------|------|------|-------------|
| **Smart Memory**（已有） | 自动结构化记忆 | L0/L1/L2/L3 | user / system_volatile |
| **Experience Evolution**（新增） | Agent 策展 + 技能演化 | curated MEMORY/USER + SKILL.md | stable 快照 + volatile 通知 |
| **Legacy memory.md**（保留） | 用户可见笔记 | `~/.deepseek/memory.md` | volatile `<user_memory>` |

**口诀**: Memory 管「知道什么」；Evolution 管「下次怎么做更好」。

### 1.2 三层架构

```text
Layer 1  post_turn/          Turn 结束后怎么处理（Memory + Evolution 共用）
Layer 2  evolution/backends/ 沉淀成什么（Curated / Skill / 未来插件）
Layer 3  evolution/ledger.py  能不能写、谁批准、审计记录
```

### 1.3 红线（违反即架构失败）

1. **禁止** fork / embed Hermes `AIAgent`（sync loop）
2. **禁止** 新建第二套 subagent loop（必须走 `post_turn/subagent_runner.py` → `run_memory_subagent_loop`）
3. **禁止** 新建平行 `session_search` 工具栈（P5 扩展 `MemoryProvider.search_conversations(summarize=...)`）
4. **禁止** 把 skill 写入 L1/L2/L3 pipeline
5. **禁止** review/flush 修改 `Engine.session_messages`
6. **禁止** 每 turn 重建 curated stable prompt（session 级 frozen snapshot）
7. **禁止** Hook 直接写 skill/memory（Hook 仅 Optional Sink 观察）
8. **禁止** v1 实现 `AssetRegistry` / `PromptAsset` / `ToolProfileAsset`（P7+ 再议）
9. **禁止** 同时存在「Engine 直调 capture」与「Orchestrator 调 capture」两套路径（P0 完成后只保留 Orchestrator）

---

## 2. 文件清单：新增 / 修改 / 精简 / 禁止重复

### 2.1 图例

| 标记 | 含义 |
|------|------|
| 🆕 **NEW** | 新建文件，此前不存在 |
| ✏️ **MODIFY** | 现有文件增加/调整逻辑 |
| 📉 **THIN** | 现有文件**删逻辑、留 re-export/委托**，避免与 NEW 重复 |
| ⛔ **NO NEW** | 不要创建该路径的独立实现（已有等价物） |

### 2.2 🆕 新增文件（完整列表）

```text
src/deepseek_tui/post_turn/
├── __init__.py                    🆕 导出 Orchestrator, TurnEvidence, gates
├── evidence.py                    🆕 TurnEvidence
├── gates.py                       🆕 passes_base_gate, should_capture, should_review
├── scheduler.py                   🆕 PeriodicTurnScheduler（从 L1Scheduler 抽象）
├── subagent_runner.py             🆕 run_bounded_tool_loop() 薄包装
├── pipeline.py                    🆕 PostTurnPipeline Protocol
├── orchestrator.py                🆕 PostTurnOrchestrator
└── pipelines/
    ├── __init__.py                🆕
    └── memory_pipeline.py         🆕 MemoryPipeline 包装 MemoryCoordinator

src/deepseek_tui/evolution/
├── __init__.py                    🆕
├── protocols.py                   🆕 ExperienceMutation, EvolutionBackend, EvolutionPolicy
├── pipeline.py                    🆕 EvolutionPipeline(PostTurnPipeline)
├── policy.py                      🆕 DefaultEvolutionPolicy
├── signals.py                     🆕 EvolutionSignals（仅信号，不含 base gate）
├── events.py                      🆕 EvolutionSuggested/Applied/RejectedEvent
├── ledger.py                      🆕 ExperienceLedger
├── prompts.py                     🆕 REVIEW/FLUSH/GUIDANCE 常量文案
├── safety.py                      🆕 scan_memory_content（curated + L1 共用）
├── curated/
│   └── store.py                   🆕 CuratedMemoryStore
├── procedural/
│   └── skill_store.py             🆕 ProceduralSkillStore
├── backends/
│   ├── __init__.py                🆕
│   ├── curated_memory.py          🆕 CuratedMemoryBackend
│   └── procedural_skill.py        🆕 ProceduralSkillBackend
├── review/
│   └── runner.py                  🆕 run_evolution_review()
└── flush/
    └── runner.py                  🆕 run_evolution_flush() → 复用 review runner

src/deepseek_tui/tools/
├── memory_curate_tool.py          🆕
└── skill_manage_tool.py           🆕

tests/post_turn/
├── test_evidence.py               🆕
├── test_gates.py                  🆕
├── test_scheduler.py              🆕
├── test_orchestrator.py           🆕
└── test_memory_pipeline.py        🆕

tests/evolution/
├── test_curated_store.py          🆕
├── test_skill_store.py            🆕
├── test_signals.py                🆕
├── test_policy.py                 🆕
├── test_ledger.py                 🆕
├── test_review_runner.py          🆕
├── test_pipeline.py               🆕
└── test_tools.py                  🆕

docs/
└── EXPERIENCE_EVOLUTION_IMPLEMENTATION.md   🆕 本文档
```

**运行时数据目录（非代码，运行时创建）**:

```text
~/.deepseek/memories/MEMORY.md     🆕 策展 agent 笔记
~/.deepseek/memories/USER.md       🆕 策展用户画像
{workspace}/.deepseek/skills/      已有路径，Evolution 默认写入项目级
```

### 2.3 ✏️ 修改文件（现有）

| 文件 | 修改内容 | Phase |
|------|----------|-------|
| `engine/engine.py` | 挂载 `post_turn: PostTurnOrchestrator`；TurnComplete 改调 orchestrator；compact 前 flush；tool dispatch 通知 evolution；**删除**直调 `capture_after_turn` | P0/P3/P4 |
| `engine/prompts.py` | stable 注入 curated + guidance；volatile 注入 `<session-evolution>` | P1 |
| `engine/events.py` | 新增 `EvolutionSuggestedEvent` 等（或放 evolution/events.py 再 import） | P3 |
| `config/models.py` | `PostTurnConfig`, `EvolutionConfig`, `EvolutionCuratedConfig`, ... | P0 |
| `config.example.toml` | 新增 `[post_turn]`、`[evolution.*]` 段 | P0 |
| `config/paths.py` | `user_curated_memories_dir()` 等 | P1 |
| `tools/builder.py` | 条件注册 `MemoryCurateTool`, `SkillManageTool` | P1/P2 |
| `tools/context.py` | 文档化 metadata keys（见 §7.2） | P1 |
| `state/schema.py` | `evolution_events` 表 + migration version bump | P2 |
| `state/database.py` | 无逻辑改，随 schema 迁移 | P2 |
| `app_server/thread_manager.py` | thread 销毁：`post_turn.flush_before_loss` 再 memory flush | P4 |
| `tui/app.py` | exit / new_session：`post_turn.flush_before_loss` | P4 |
| `memory/native/l1_extractor.py` | capture 前可选调 `evolution.safety.scan_memory_content` | P2 |
| `memory/native/provider.py` | P5: `search_conversations(..., summarize=False)` 扩展 | P5 |
| `skills/__init__.py` | 新增 `invalidate_skills_prompt_cache()` | P2 |
| `hooks/build.py` | P7: 可选注册 TrajectorySink | P7 |

### 2.4 📉 精简文件（删重复逻辑，保留兼容）

> **目的**: 阅读代码时只有一处真实现，旧路径仅 re-export 或薄包装。

| 文件 | 精简方式 | 真实现迁到 |
|------|----------|------------|
| `memory/gates.py` | **删函数体**，改为 `from deepseek_tui.post_turn.gates import should_capture_turn` 等 re-export；或保留 `should_capture_turn` 名作为 alias | `post_turn/gates.py` |
| `memory/native/scheduler.py` | **L1Scheduler 改为包装** `PeriodicTurnScheduler`，删除重复的 every_n/idle 状态机代码 | `post_turn/scheduler.py` |
| `memory/native/agent_loop.py` | **不删文件**；`post_turn/subagent_runner.py` **import 并 re-export**，不在 post_turn 重写 loop | 保持本文件为唯一 loop 实现 |
| `memory/coordinator.py` | **删** `should_capture_turn` 内联 gate 调用以外的重复；capture/flush **仅**被 `MemoryPipeline` 调用，Engine 不再直调 | 门控在 `post_turn/gates.py` |
| `memory/coordinator.py` | `capture_after_turn` **保留**方法签名，供 MemoryPipeline 委托 | — |

**📉 精简后 `memory/coordinator.py` 应只剩**:

- recall 相关（不变）
- `capture_after_turn` / `flush_session`（供 MemoryPipeline 调用）
- `should_capture_turn` → 委托 `post_turn.gates.should_capture`（或删除此方法，Pipeline 直接调 gates）

**⛔ 精简后禁止再出现**:

- `memory/evolution_*.py` — 不存在，Evolution 只在 `evolution/`
- `memory/post_turn/` — PostTurn 在顶层 `post_turn/`，不在 memory 子包
- 第二个 `EvolutionCoordinator` 与 `PostTurnOrchestrator` 并行挂载 Engine

### 2.5 ⛔ 禁止新建（防重复）

| 不要创建 | 原因 | 应使用 |
|----------|------|--------|
| `evolution/coordinator.py`（独立 Engine 挂载） | 与 Orchestrator 重复 | `evolution/pipeline.py` + `post_turn/orchestrator.py` |
| `evolution/subagent_loop.py` | 重复 agent_loop | `post_turn/subagent_runner.py` |
| `evolution/gates.py` | 重复 post_turn gates | `post_turn/gates.py` + `evolution/signals.py` |
| `evolution/scheduler.py` | 重复 PeriodicTurnScheduler | `post_turn/scheduler.py` |
| `tools/session_search_tool.py` | 重复 memory search | 扩展 `MemoryProvider` |
| `memory/curated_store.py` | 领域应在 evolution | `evolution/curated/store.py` |
| `experience/` 顶层包与 `post_turn/`+`evolution/` 同时存在 | 命名分裂 | 仅 `post_turn/` + `evolution/` |
| `AssetRegistry` / `assets/prompt_rule.py`（v1） | 过度设计 | `EvolutionBackend` 列表 |

---

## 3. 总体架构

```text
                         User Turn
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  MemoryCoordinator    build_system_prompt    TurnLoop + tools
  .recall()            (stable + volatile)     memory_curate / skill_manage
                             │
                             ▼
                      TurnComplete
                             │
                   build TurnEvidence (once)
                             │
                             ▼
              ┌──────────────────────────────┐
              │   PostTurnOrchestrator        │
              │   after_turn()                │
              │   flush_before_loss()         │
              └──────────┬─────────┬──────────┘
                         │         │
            MemoryPipeline         EvolutionPipeline
                         │         │
              Smart L0→L3          Backends → Ledger → disk/DB
```

---

## 4. Layer 1：PostTurn Runtime（共享）

### 4.1 `TurnEvidence`（`post_turn/evidence.py`）

```python
@dataclass(slots=True)
class TurnEvidence:
    thread_id: str
    user_text: str
    workspace: str                          # 绝对路径字符串
    messages: list[dict[str, Any]]          # OpenAI-ish dict，与 CaptureInput 一致
    had_tool_calls: bool
    success: bool
    tool_rounds: int = 0                    # 本 turn 内 LLM↔tool 往返次数
    user_turn_index: int = 0                # Engine 会话内 user turn 计数（从 1 递增）
    turn_id: str = ""
    flush_mode: bool = False                  # compaction/exit/thread-end 时为 True

    def to_capture_input(self) -> CaptureInput:
        return CaptureInput(
            thread_id=self.thread_id,
            user_text=self.user_text,
            workspace=self.workspace,
            messages=self.messages,
            had_tool_calls=self.had_tool_calls,
            success=self.success,
        )
```

**构建位置**: `Engine._handle_send_message_inner`，TurnComplete 之前，**只构建一次**。

**字段来源**:

| 字段 | 来源 |
|------|------|
| `thread_id` | `_resolve_memory_thread_id()` |
| `workspace` | `str(tool_context.working_directory.resolve())` |
| `messages` | `_messages_for_capture(turn_slice)` |
| `had_tool_calls` | `_turn_had_tool_calls(turn_slice)` |
| `success` | `result.outcome == TurnOutcomeStatus.SUCCESS` |
| `tool_rounds` | `_run_conversation` 内 loop 计数 |
| `user_turn_index` | `Engine._user_turn_index`（新增字段，每 user message +1） |

### 4.2 `TurnGate`（`post_turn/gates.py`）

```python
@dataclass(frozen=True)
class GateConfig:
    min_chars: int = 20
    skip_slash: bool = True
    skip_confirmations: bool = True
    require_success: bool = True

def passes_base_gate(evidence: TurnEvidence, cfg: GateConfig) -> bool:
    """success、slash、confirm-only、min_chars — Memory 与 Evolution 共用。"""

def should_capture(evidence: TurnEvidence, cfg: GateConfig) -> bool:
    """Memory capture 门控：had_tool_calls OR passes_base_gate。"""
    if not evidence.success:
        return False
    if evidence.had_tool_calls:
        return True
    return passes_base_gate(evidence, cfg)

def should_review(
    evidence: TurnEvidence,
    *,
    cfg: GateConfig,
    scheduler_due: bool,
    signals: EvolutionSignals,
) -> bool:
    """Evolution review 门控：flush_mode 单独处理；否则 base_gate AND (scheduler OR signals)。"""
    if evidence.flush_mode:
        return True
    if not evidence.success:
        return False
    if not passes_base_gate(evidence, cfg):
        return False
    return scheduler_due or signals.any()
```

**`memory/gates.py` 精简后**:

```python
# 仅 re-export，无独立实现
from deepseek_tui.post_turn.gates import GateConfig, passes_base_gate

def should_capture_turn(user_text, *, had_tool_calls, success, min_chars=20, ...):
    # 构造最小 TurnEvidence 或直接调用 passes_base_gate + had_tool_calls 逻辑
    ...
```

现有测试 `tests/memory/test_gates.py` **改为** import `post_turn.gates`，旧模块保留兼容 alias。

### 4.3 `PeriodicTurnScheduler`（`post_turn/scheduler.py`）

从 `memory/native/scheduler.py` 的 `L1Scheduler` **抽取**通用逻辑：

```python
class PeriodicTurnScheduler:
    def __init__(self, *, every_n: int, idle_timeout_s: float, warmup_enabled: bool = True): ...

    def notify(self, key: str, payload: Any) -> None:
        """每 turn 调用，累积 payload（如 messages batch 或 TurnEvidence）。"""

    def is_due(self, key: str) -> bool:
        """当前 key 是否达到 every_n 阈值。"""

    def reset(self, key: str) -> None:
        """tool 调用 memory_curate / skill_manage 后重置对应 scheduler。"""
```

**使用者**:

| 实例 | 挂载位置 | every_n 配置 | reset 条件 |
|------|----------|--------------|------------|
| L1 内部 | `NativeMemoryProvider` / 薄 L1Scheduler | `memory.smart.l1_every_n` | L1 job 提交后 |
| `review_memory_sched` | `EvolutionPipeline` | `evolution.schedulers.memory_nudge_every_n` | `memory_curate` 调用 |
| `review_skill_sched` | `EvolutionPipeline` | 按 `tool_rounds` 阈值 | `skill_manage` 调用 |

**`memory/native/scheduler.py` 精简后**: `L1Scheduler` 类保留 public API，内部 `self._sched = PeriodicTurnScheduler(...)`。

### 4.4 `SubagentRunner`（`post_turn/subagent_runner.py`）

```python
from deepseek_tui.memory.native.agent_loop import (
    MemorySubagentLoopResult,
    run_memory_subagent_loop,
)

async def run_bounded_tool_loop(
    client: LLMClient,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    context: ToolContext,
    max_steps: int = 8,
    max_tokens: int = 4096,
) -> MemorySubagentLoopResult:
    return await run_memory_subagent_loop(
        client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        registry=registry,
        context=context,
        max_steps=max_steps,
        max_tokens=max_tokens,
    )
```

⛔ **禁止** 在 `evolution/review/runner.py` 再写 while loop。

### 4.5 `PostTurnPipeline` + `PostTurnOrchestrator`

```python
# post_turn/pipeline.py
class PostTurnPipeline(Protocol):
    name: str
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def after_turn(self, evidence: TurnEvidence) -> None: ...
    async def flush_before_loss(self, evidence: TurnEvidence) -> None: ...

# post_turn/orchestrator.py
class PostTurnOrchestrator:
    def __init__(self, pipelines: list[PostTurnPipeline], *, flush_timeout_s: float = 30.0): ...

    async def start(self) -> None:
        for p in self._pipelines:
            await p.start()

    async def stop(self) -> None:
        for p in reversed(self._pipelines):
            await p.stop()

    async def after_turn(self, evidence: TurnEvidence) -> None:
        for p in self._pipelines:
            try:
                await p.after_turn(evidence)
            except Exception:
                logger.exception("post_turn after_turn failed pipeline=%s", p.name)

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        flush_ev = replace(evidence, flush_mode=True)
        for p in self._pipelines:
            try:
                await asyncio.wait_for(
                    p.flush_before_loss(flush_ev),
                    timeout=self._flush_timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning("post_turn flush timeout pipeline=%s", p.name)
            except Exception:
                logger.exception("post_turn flush failed pipeline=%s", p.name)

    def on_main_tool_called(self, tool_name: str) -> None:
        """仅 EvolutionPipeline 消费；MemoryPipeline 可 no-op。"""
        for p in self._pipelines:
            if hasattr(p, "on_main_tool_called"):
                p.on_main_tool_called(tool_name)
```

### 4.6 `MemoryPipeline`（`post_turn/pipelines/memory_pipeline.py`）

```python
class MemoryPipeline:
    name = "memory"

    def __init__(self, coordinator: MemoryCoordinator, config: Config): ...

    async def after_turn(self, evidence: TurnEvidence) -> None:
        if not self._coordinator.enabled:
            return
        cfg = GateConfig(
            min_chars=self._config.memory.smart.capture_min_user_chars,
            skip_slash=self._config.memory.smart.capture_skip_slash_commands,
        )
        if not should_capture(evidence, cfg):
            return
        inp = evidence.to_capture_input()
        await self._coordinator.capture_after_turn(
            thread_id=inp.thread_id,
            user_text=inp.user_text,
            workspace=inp.workspace,
            messages=inp.messages,
            had_tool_calls=inp.had_tool_calls,
            success=inp.success,
        )

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        await self._coordinator.flush_session(evidence.thread_id)
```

**注意**: `MemoryCoordinator.should_capture_turn` 可删除，gate 统一在 `post_turn/gates.py`。

---

## 5. Layer 2：Experience Backends（分化）

### 5.1 协议（`evolution/protocols.py`）

```python
@dataclass(slots=True)
class ExperienceMutation:
    kind: Literal[
        "memory_curate_add",
        "memory_curate_replace",
        "memory_curate_remove",
        "skill_create",
        "skill_patch",
        "skill_edit",
        "skill_delete",
        "skill_write_file",
        "skill_remove_file",
    ]
    payload: dict[str, Any]       # 与 tool args 对齐
    target_path: str | None       # 落盘路径（审计用）
    risk: Literal["low", "medium", "high"]
    reason: str = ""
    diff_before: str | None = None
    diff_after: str | None = None

@dataclass(slots=True)
class ApplyResult:
    success: bool
    message: str = ""
    path: str | None = None
    diff: str | None = None

class EvolutionBackend(Protocol):
    name: str

    def mutation_from_tool(self, tool_name: str, args: dict[str, Any]) -> ExperienceMutation | None: ...

    def mutations_from_subagent_tool_results(
        self, tool_results: list[tuple[str, dict, str]]
    ) -> list[ExperienceMutation]: ...

    async def apply(self, mutation: ExperienceMutation) -> ApplyResult: ...

    def stable_prompt_block(self) -> str | None:
        """Session 级 frozen snapshot 片段；无则 None。"""

    def volatile_prompt_lines(self) -> list[str]:
        """本 session 新 skill 等 volatile 提示。"""
```

**Backend 注册**（⛔ 不用 AssetRegistry）:

```python
# evolution/pipeline.py 内
self._backends: list[EvolutionBackend] = [
    CuratedMemoryBackend(store),
    ProceduralSkillBackend(skill_store),
]
```

### 5.2 `CuratedMemoryStore`（`evolution/curated/store.py`）

| 项 | 值 |
|----|-----|
| 路径 | `{curated_dir}/MEMORY.md`, `{curated_dir}/USER.md` |
| 默认 dir | `~/.deepseek/memories/`（`config/paths.user_curated_memories_dir()`） |
| 分隔符 | `\n§\n` |
| 上限 | MEMORY 2200 chars / USER 1375 chars（可配置） |
| 并发 | `fcntl` 文件锁 + `os.replace` 原子写 |
| 安全 | 写入前 `evolution.safety.scan_memory_content()` |
| 快照 | `load_snapshot() -> CuratedSnapshot` 在 session 创建时调用一次 |

```python
@dataclass(frozen=True)
class CuratedSnapshot:
    memory_block: str | None
    user_block: str | None
```

API: `add(target, content)`, `replace(target, old_text, content)`, `remove(target, old_text)` → 返回与 Hermes memory_tool 类似的 dict。

### 5.3 `ProceduralSkillStore`（`evolution/procedural/skill_store.py`）

| 项 | 值 |
|----|-----|
| 默认 scope | `project` → `{workspace}/.deepseek/skills/{name}/` |
| user scope | `~/.deepseek/skills/{name}/` |
| 文件 | `SKILL.md` + `references|templates|scripts|assets/` |
| 校验 | YAML frontmatter `name`, `description`；禁止 `..` |
| 安全 | 写入后 scan（可选 block） |
| cache | 成功后 `skills.invalidate_skills_prompt_cache()` |

Actions: `create`, `patch`, `edit`, `delete`, `write_file`, `remove_file` — schema 对齐 Hermes `skill_manage`。

### 5.4 `EvolutionSignals`（`evolution/signals.py`）

**仅检测 Evolution 专有信号**（不重复 base gate）:

```python
@dataclass(slots=True)
class EvolutionSignals:
    high_tool_rounds: bool = False          # tool_rounds >= min_tool_calls (default 5)
    recovery_after_failure: bool = False    # 本 turn 有 tool error 后又有 success tool
    user_correction: bool = False           # 启发式：用户消息含「不对/应该/别用/error」等
    explicit_remember_procedure: bool = False  # 「记住流程/保存为 skill」等
    load_skill_gap: bool = False          # 本 turn 调了 load_skill 且后续 tool 失败（可选 P3+）

    def any(self) -> bool:
        return any(vars(self).values())
```

`detect(evidence: TurnEvidence, messages: list[dict]) -> EvolutionSignals`

### 5.5 `EvolutionPipeline`（`evolution/pipeline.py`）

```python
class EvolutionPipeline:
    name = "evolution"

    async def after_turn(self, evidence: TurnEvidence) -> None:
        if not self._enabled:
            return
        self._review_memory_sched.notify(evidence.thread_id, evidence)
        signals = detect_signals(evidence, evidence.messages)
        scheduler_due = self._review_memory_sched.is_due(evidence.thread_id)
        skill_due = evidence.tool_rounds >= self._skill_nudge_tool_rounds

        if not should_review(
            evidence,
            cfg=self._gate_cfg,
            scheduler_due=scheduler_due or skill_due,
            signals=signals,
        ):
            return

        asyncio.create_task(
            self._run_review(evidence, review_memory=scheduler_due, review_skill=skill_due),
            name=f"evolution-review-{evidence.turn_id}",
        )

    async def _run_review(self, evidence, *, review_memory: bool, review_skill: bool):
        mutations = await run_evolution_review(
            self._client,
            model=self._review_model,
            evidence=evidence,
            backends=self._backends,
            review_memory=review_memory,
            review_skill=review_skill,
        )
        for m in mutations:
            await self._ledger.submit(m, source="review", evidence=evidence)

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        if evidence.user_turn_index < self._flush_min_turns:
            return
        mutations = await run_evolution_flush(self._client, self._review_model, evidence, self._backends)
        for m in mutations:
            await self._ledger.submit(m, source="flush", evidence=evidence)

    def on_main_tool_called(self, tool_name: str) -> None:
        if tool_name == "memory_curate":
            self._review_memory_sched.reset(self._current_thread_id)
        elif tool_name == "skill_manage":
            pass  # skill nudge 按 tool_rounds，在 after_turn 判断

    def curated_stable_block(self) -> str | None: ...
    def volatile_lines(self) -> list[str]: ...
```

### 5.6 Review / Flush Runner（`evolution/review/runner.py` + `flush/runner.py`）

```python
# review/runner.py
EVOLUTION_REVIEW_SYSTEM = "..."  # 来自 evolution/prompts.py

def build_review_user_prompt(evidence, *, review_memory, review_skill, flush_mode) -> str:
    # 组合 Hermes _MEMORY_REVIEW / _SKILL_REVIEW / _COMBINED / flush 语义

async def run_evolution_review(...) -> list[ExperienceMutation]:
    registry = ToolRegistry()
    registry.register(MemoryCurateTool(...))   # 仅 review 用 narrow handler
    registry.register(SkillManageTool(...))
    # sandbox context: workspace locked, 无 file/terminal 工具
    result = await run_bounded_tool_loop(...)
    return collect_mutations_from_tool_results(result, backends)

# flush/runner.py
async def run_evolution_flush(...) -> list[ExperienceMutation]:
    return await run_evolution_review(..., flush_mode=True)
```

**Review 使用独立 messages 列表**: 从 `evidence.messages` 深拷贝，**不** append 到 Engine session。

---

## 6. Layer 3：Experience Ledger（审计与审批）

### 6.1 `DefaultEvolutionPolicy`（`evolution/policy.py`）

```python
class DefaultEvolutionPolicy:
    def decide(self, mutation: ExperienceMutation, *, source: str) -> Literal["auto", "propose", "deny"]:
        if mutation.kind.startswith("memory_curate"):
            return self._cfg.ledger.memory_curate  # default "auto"
        if mutation.kind == "skill_patch" and mutation.risk == "low":
            return self._cfg.ledger.skill_patch       # default "auto"
        if mutation.kind in ("skill_create", "skill_delete", "skill_edit"):
            return self._cfg.ledger.skill_create      # default "propose"
        if source == "review" and self._cfg.mode == "suggest":
            return "propose"
        return "propose"
```

### 6.2 `ExperienceLedger`（`evolution/ledger.py`）

```python
class ExperienceLedger:
    async def submit(
        self,
        mutation: ExperienceMutation,
        *,
        source: Literal["main_tool", "review", "flush"],
        evidence: TurnEvidence,
    ) -> LedgerRecord:
        decision = self._policy.decide(mutation, source=source)
        record = self._audit.insert_proposed(mutation, evidence, source, decision)

        if decision == "deny":
            return record

        if decision == "propose":
            await self._emit(EvolutionSuggestedEvent(record))
            return record

        # auto apply
        backend = self._backend_for(mutation)
        result = await backend.apply(mutation)
        if result.success:
            await self._audit.mark_applied(record.id, result)
            await self._emit(EvolutionAppliedEvent(record, result))
            self._pipeline_note_volatile(mutation, result)
        else:
            await self._audit.mark_failed(record.id, result.message)
        return record

    async def approve(self, record_id: str) -> LedgerRecord: ...  # P6 Workbench
    async def reject(self, record_id: str) -> LedgerRecord: ...
```

### 6.3 事件（`evolution/events.py`）

```python
@dataclass(frozen=True)
class EvolutionSuggestedEvent:
    record_id: str
    kind: str
    summary: str
    asset_path: str | None

@dataclass(frozen=True)
class EvolutionAppliedEvent:
    record_id: str
    summary: str

@dataclass(frozen=True)
class EvolutionRejectedEvent:
    record_id: str
    reason: str
```

TUI: 订阅 `EvolutionAppliedEvent` → toast `💾 {summary}`（`config.evolution.notify`）。

---

## 7. 工具层（主 Agent 入口）

### 7.1 工具注册（`tools/builder.py`）

```python
if config.evolution.enabled and config.evolution.curated.enabled:
    registry.register(MemoryCurateTool())
if config.evolution.enabled and config.evolution.procedural.enabled:
    registry.register(SkillManageTool())
```

### 7.2 `ToolContext.metadata` 键（集中定义，⛔ 禁止散落 magic string）

在 `evolution/constants.py` 🆕 或 `tools/memory_curate_tool.py` 顶部定义:

```python
CURATED_MEMORY_STORE_KEY = "curated_memory_store"
SKILL_STORE_KEY = "skill_store"
EVOLUTION_LEDGER_KEY = "evolution_ledger"
POST_TURN_ORCHESTRATOR_KEY = "post_turn_orchestrator"  # 可选
```

`Engine.create` 注入:

```python
engine.tool_context.metadata[CURATED_MEMORY_STORE_KEY] = curated_store
engine.tool_context.metadata[SKILL_STORE_KEY] = skill_store
engine.tool_context.metadata[EVOLUTION_LEDGER_KEY] = ledger
```

### 7.3 `MemoryCurateTool` schema

```json
{
  "name": "memory_curate",
  "parameters": {
    "action": {"enum": ["add", "replace", "remove"]},
    "target": {"enum": ["memory", "user"]},
    "content": {"type": "string"},
    "old_text": {"type": "string"}
  },
  "required": ["action", "target"]
}
```

**execute 流程**:

1. 从 metadata 取 store + ledger  
2. `mutation = CuratedMemoryBackend.mutation_from_tool(...)`  
3. `await ledger.submit(mutation, source="main_tool", evidence=...)`  
4. 返回 JSON 给模型  

⛔ **禁止** tool 内直接写盘绕过 Ledger（review flush 除外，也走 Ledger）。

### 7.4 `SkillManageTool` schema

与 Hermes `skill_manage` 对齐：`action` ∈ create/patch/edit/delete/write_file/remove_file，`name`, `content`, `old_string`, `new_string`, `file_path`, `file_content`, `category`, `replace_all`。

### 7.5 `remember` 双写（可选 P2）

`RememberTool` 在 evolution enabled 时:

- 继续 append `memory.md`  
- 可选：`ledger.submit` curated USER add（low risk auto）  
- 已有：`provider.remember_instruction` → L1  

---

## 8. Prompt 注入规范

### 8.1 常量文案（`evolution/prompts.py` 🆕）

```python
EVOLUTION_GUIDANCE = """..."""           # 何时 memory_curate
SKILLS_EVOLUTION_GUIDANCE = """..."""    # 何时 skill_manage / patch
EVOLUTION_REVIEW_SYSTEM = """..."""
MEMORY_REVIEW_USER = """..."""          # 对齐 Hermes _MEMORY_REVIEW_PROMPT
SKILL_REVIEW_USER = """..."""
COMBINED_REVIEW_USER = """..."""
FLUSH_USER = """..."""                  # 对齐 Hermes flush + gateway flush
```

### 8.2 `build_system_prompt` 修改（`engine/prompts.py`）

**Stable 层**（在 Environment 之后、Skills index 之前）:

```python
if evolution_enabled and curated_snapshot:
    full_prompt += "\n\n" + curated_snapshot
if evolution_enabled:
    full_prompt += "\n\n" + EVOLUTION_GUIDANCE
    full_prompt += "\n\n" + SKILLS_EVOLUTION_GUIDANCE
```

**Volatile 层**（在 working_set 之前）:

```python
if session_evolution_lines:
    full_prompt += "\n\n<session-evolution>\n"
    full_prompt += "\n".join(session_evolution_lines)
    full_prompt += "\n</session-evolution>"
```

**curated_snapshot 来源**: `Engine` 在 session/thread 创建时从 `EvolutionPipeline.curated_stable_block()` 读取并缓存到 `Engine._curated_snapshot`（新字段），**mid-session 不更新**。

**session_evolution_lines 来源**: `EvolutionPipeline.volatile_lines()`，Ledger apply skill 后 append。

⛔ **禁止** skill 写入后调用全量 `discover_in_workspace` 重建 stable skills block。

---

## 9. Engine 接入（精确位置）

### 9.1 `Engine.create()`（`engine/engine.py` ~L459 后）

```python
from deepseek_tui.post_turn.orchestrator import PostTurnOrchestrator
from deepseek_tui.post_turn.pipelines.memory_pipeline import MemoryPipeline

pipelines = []
if engine.memory_coordinator is not None:
    pipelines.append(MemoryPipeline(engine.memory_coordinator, cfg))

if cfg.evolution.enabled:
    from deepseek_tui.evolution.pipeline import build_evolution_pipeline
    evo = build_evolution_pipeline(cfg, client, engine.tool_context.working_directory)
    pipelines.append(evo)
    engine._curated_snapshot = evo.curated_stable_block()
    engine._evolution_pipeline = evo
else:
    engine._curated_snapshot = None
    engine._evolution_pipeline = None

if cfg.post_turn.enabled and pipelines:
    engine.post_turn = PostTurnOrchestrator(pipelines, flush_timeout_s=cfg.evolution.flush_timeout_s)
    await engine.post_turn.start()
else:
    engine.post_turn = None
```

保留 `engine.memory_coordinator` **仅用于 recall** 与 MemoryPipeline 构造。

### 9.2 `_handle_send_message_inner` TurnComplete（~L1085-1100）

**删除**:

```python
await coordinator.capture_after_turn(...)  # 整段删除
```

**替换为**:

```python
self._user_turn_index += 1
evidence = TurnEvidence(
    thread_id=thread_id,
    user_text=processed.model_text or op.content or "",
    workspace=workspace_str,
    messages=self._messages_for_capture(turn_slice),
    had_tool_calls=self._turn_had_tool_calls(turn_slice),
    success=turn_ok,
    tool_rounds=result.tool_round_count,  # TurnResult 需暴露或 Engine 计数
    user_turn_index=self._user_turn_index,
    turn_id=turn_id,
)
if self.post_turn is not None:
    await self.post_turn.after_turn(evidence)
```

### 9.3 `_run_conversation` compact 前（~L1236 前）

```python
if self.post_turn is not None and messages:
    evidence = self._build_flush_evidence(messages)  #  helper
    await self.post_turn.flush_before_loss(evidence)
```

### 9.4 Tool dispatch 后（`_execute_tool_calls` 或 `_invoke_tool` 末尾）

```python
if self.post_turn is not None:
    self.post_turn.on_main_tool_called(function_name)
```

### 9.5 `build_system_prompt` 调用处（~L992）

传入:

```python
curated_snapshot=getattr(self, "_curated_snapshot", None),
session_evolution_lines=(
    self._evolution_pipeline.volatile_lines()
    if self._evolution_pipeline else None
),
evolution_enabled=bool(self._evolution_pipeline),
```

### 9.6 `thread_manager.py` thread 销毁（~L448）

**替换** 直调 `coordinator.flush_session`:

```python
if state.engine.post_turn is not None:
    evidence = build_evidence_from_engine(state.engine, flush_mode=True)
    await state.engine.post_turn.flush_before_loss(evidence)
elif coordinator is not None:
    await coordinator.flush_session(thread_id)
```

Evolution flush 已链式调用 MemoryPipeline.flush → 最终 **只调 post_turn** 即可。

### 9.7 `Engine` 新增字段

```python
self.post_turn: PostTurnOrchestrator | None = None
self._user_turn_index: int = 0
self._curated_snapshot: str | None = None
self._evolution_pipeline: EvolutionPipeline | None = None
```

`new session` / thread 新建时: `_user_turn_index = 0`，刷新 `_curated_snapshot`。

---

## 10. 配置规范

### 10.1 `config/models.py` 新增

```python
class PostTurnConfig(BaseModel):
    enabled: bool = True

class EvolutionCuratedConfig(BaseModel):
    enabled: bool = True
    dir: str = ""
    memory_char_limit: int = 2200
    user_char_limit: int = 1375

class EvolutionProceduralConfig(BaseModel):
    enabled: bool = True
    default_scope: Literal["project", "user"] = "project"

class EvolutionSchedulersConfig(BaseModel):
    memory_nudge_every_n: int = 10
    skill_nudge_tool_rounds: int = 10
    review_idle_timeout_seconds: int = 600
    min_tool_calls_signal: int = 5

class EvolutionLedgerConfig(BaseModel):
    enabled: bool = True
    retain_days: int = 90
    memory_curate: Literal["auto", "propose", "deny"] = "auto"
    skill_patch: Literal["auto", "propose", "deny"] = "auto"
    skill_create: Literal["auto", "propose", "deny"] = "propose"

class EvolutionSinksConfig(BaseModel):
    trajectory_enabled: bool = False
    trajectory_path: str = ""

class EvolutionConfig(BaseModel):
    enabled: bool = False
    mode: Literal["suggest", "auto_patch"] = "suggest"
    review_model: str = ""
    review_max_steps: int = 8
    flush_min_user_turns: int = 6
    flush_timeout_s: float = 30.0
    notify: bool = True
    curated: EvolutionCuratedConfig = Field(default_factory=EvolutionCuratedConfig)
    procedural: EvolutionProceduralConfig = Field(default_factory=EvolutionProceduralConfig)
    schedulers: EvolutionSchedulersConfig = Field(default_factory=EvolutionSchedulersConfig)
    ledger: EvolutionLedgerConfig = Field(default_factory=EvolutionLedgerConfig)
    sinks: EvolutionSinksConfig = Field(default_factory=EvolutionSinksConfig)

class Config(BaseModel):
    post_turn: PostTurnConfig = Field(default_factory=PostTurnConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    # memory / memory.smart 不变
```

### 10.2 `config.example.toml` 追加

```toml
[post_turn]
enabled = true

[evolution]
enabled = false
mode = "suggest"
review_model = ""
review_max_steps = 8
flush_min_user_turns = 6
flush_timeout_s = 30.0
notify = true

[evolution.curated]
enabled = true
# dir = ""  # default ~/.deepseek/memories
memory_char_limit = 2200
user_char_limit = 1375

[evolution.procedural]
enabled = true
default_scope = "project"

[evolution.schedulers]
memory_nudge_every_n = 10
skill_nudge_tool_rounds = 10
review_idle_timeout_seconds = 600
min_tool_calls_signal = 5

[evolution.ledger]
enabled = true
retain_days = 90
memory_curate = "auto"
skill_patch = "auto"
skill_create = "propose"

[evolution.sinks]
trajectory_enabled = false
# trajectory_path = "~/.deepseek/trajectories"
```

**开关语义**:

| 配置 | 效果 |
|------|------|
| `post_turn.enabled=false` | 不挂 Orchestrator，**回退现网**（仅 recall + memory.md） |
| `evolution.enabled=false` | 仅 MemoryPipeline（Smart capture 若开启） |
| `memory.smart.enabled=false` + `evolution.enabled=true` | Evolution 独立运行，不依赖 L0-L3 |

---

## 11. 数据库迁移

### 11.1 `state/schema.py`

在 `SCHEMA_STATEMENTS` 末尾追加 migration version **3**（当前最后为 2，以仓库为准 bump）:

```sql
CREATE TABLE IF NOT EXISTS evolution_events (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    asset_path TEXT,
    diff_json TEXT,
    reason TEXT,
    source TEXT NOT NULL,
    source_turn_id TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evolution_events_thread
ON evolution_events(thread_id, created_at DESC);
INSERT OR IGNORE INTO schema_migrations(version) VALUES (3);
```

### 11.2 `evolution/audit/store.py`

封装 insert / mark_applied / mark_failed / list_pending / get。

---

## 12. 运行时流程（逐步）

### 12.1 Session 启动

1. `Engine.create()`  
2. 创建 MemoryCoordinator（若 smart enabled）  
3. 创建 Evolution 组件（若 evolution enabled）  
4. `CuratedMemoryStore.load_snapshot()` → `Engine._curated_snapshot`  
5. `PostTurnOrchestrator.start()`  

### 12.2 每 User Turn

1. `recall_for_turn()` — 不变  
2. `build_system_prompt(stable curated + volatile evolution + ...)`  
3. `_run_conversation` loop  
4. 每次 tool round: `iters`/tool_rounds 计数；`on_main_tool_called`  
5. 主 agent 调 `memory_curate` / `skill_manage` → Ledger → apply/propose  
6. TurnComplete → 构建 `TurnEvidence`  
7. `post_turn.after_turn(evidence)`  
   - MemoryPipeline: gate → capture  
   - EvolutionPipeline: scheduler → signals → maybe `create_task(review)`  
8. Review task（异步）: subagent loop → mutations → Ledger  
9. Emit events → TUI toast  

### 12.3 Compaction

1. `_build_flush_evidence`  
2. `post_turn.flush_before_loss`  
   - Evolution: review flush prompt → Ledger  
   - Memory: flush_session  
3. `compact_messages_safe`  

### 12.4 Thread 销毁 / TUI exit

同 12.3 flush 链，best-effort，不阻塞 UI 过久。

---

## 13. 分期实现 Checklist

### P0 — PostTurn 骨架（零行为变化）

- [ ] 🆕 `post_turn/*` 除 `EvolutionPipeline` 外全部  
- [ ] 🆕 `MemoryPipeline`  
- [ ] ✏️ `engine/engine.py` 挂 Orchestrator，**Behavior**: smart capture 仍工作，路径改为 Pipeline  
- [ ] ✏️ `config/models.py` + `config.example.toml`  
- [ ] 📉 准备 `memory/gates.py` re-export（可先不删旧实现，P0.5 再迁）  
- [ ] ⛔ 不创建 `evolution/` 业务逻辑（可空包）  
- [ ] 验收: `evolution.enabled=false`，全测试绿，capture 行为不变  

### P0.5 — 抽取共享（refactor）

- [ ] 🆕 `post_turn/scheduler.py` 真实现  
- [ ] 📉 `memory/native/scheduler.py` 改为薄包装  
- [ ] 📉 `memory/gates.py` → re-export `post_turn/gates.py`  
- [ ] 🆕 `post_turn/subagent_runner.py` → import `agent_loop`  
- [ ] ✏️ `tests/memory/test_gates.py` → 测 `post_turn.gates`  
- [ ] 验收: L1 触发时机与 refactor 前一致  

### P1 — Curated 声明式

- [ ] 🆕 `evolution/curated/store.py`, `safety.py`, `backends/curated_memory.py`  
- [ ] 🆕 `tools/memory_curate_tool.py`  
- [ ] 🆕 `evolution/ledger.py`（仅 memory_curate auto）  
- [ ] ✏️ `engine/prompts.py` stable 注入  
- [ ] ✏️ `tools/builder.py`  
- [ ] ✏️ `config/paths.py`  
- [ ] 验收: 新 session prompt 含 curated；同 session 写入后不更新 stable  

### P2 — Skill + Audit

- [ ] 🆕 `procedural/skill_store.py`, `backends/procedural_skill.py`, `tools/skill_manage_tool.py`  
- [ ] 🆕 `state/schema.py` migration + `audit/store.py`  
- [ ] ✏️ `skills/__init__.py` cache invalidate  
- [ ] ✏️ `memory/native/l1_extractor.py` safety 钩子  
- [ ] 验收: skill 落盘 + load_skill + evolution_events 有记录  

### P3 — Review 闭环

- [ ] 🆕 `signals.py`, `review/runner.py`, `evolution/pipeline.py` 完整  
- [ ] 🆕 `events.py`  
- [ ] ✏️ `engine/engine.py` tool_round 计数 + 删旧 capture 直调  
- [ ] 验收: 10 turns 或 5+ tool rounds 触发 review；不改 session_messages  

### P4 — Flush 链

- [ ] 🆕 `flush/runner.py`  
- [ ] ✏️ compact 前 + thread_manager + tui exit  
- [ ] 验收: compact 前 curated/skill 抢救；transcript 无 flush 假 user 消息  

### P5 — Recall 摘要（可选）

- [ ] ✏️ `memory/native/provider.py` search_conversations(summarize=...)  
- [ ] 验收: conversation_search 返回摘要而非 raw 堆砌  

### P6 — Workbench 审批 UI（可选）

- [ ] Ledger approve/reject API + SSE  
- [ ] `evolution.mode=auto_patch` 低风险 patch  

### P7 — Optional Sinks（可选）

- [ ] 🆕 `evolution/sinks/trajectory.py`  
- [ ] ✏️ `hooks/build.py`  
- [ ] ⛔ 不实现 AssetRegistry  

---

## 14. 测试清单

| 测试文件 | 覆盖 |
|----------|------|
| `tests/post_turn/test_gates.py` | base/capture/review 门控 |
| `tests/post_turn/test_scheduler.py` | every_n / idle / reset |
| `tests/post_turn/test_orchestrator.py` | 多 pipeline 调度、flush 顺序 |
| `tests/evolution/test_curated_store.py` | § 分隔、limit、scan、lock |
| `tests/evolution/test_skill_store.py` | create/patch、traversal |
| `tests/evolution/test_ledger.py` | auto/propose/deny、audit 行 |
| `tests/evolution/test_review_runner.py` | mock LLM，无 session 污染 |
| `tests/memory/test_engine_memory_wiring.py` | 更新为 post_turn 路径 |
| `tests/contract/test_memory_acceptance.py` | regression |

---

## 15. 反模式：禁止重复清单

实现 PR review 时对照：

- [ ] Engine 内是否仍存在 `capture_after_turn` 直调（应只有 Orchestrator）  
- [ ] 是否存在两处 `should_capture_turn` 实现（应只有 `post_turn/gates.py`）  
- [ ] 是否存在两处 PeriodicScheduler 状态机（应只有 `post_turn/scheduler.py`）  
- [ ] 是否存在第三个 subagent while loop  
- [ ] tool 是否绕过 Ledger 直接写 curated/skill 文件  
- [ ] review 是否 append 到 `session_messages`  
- [ ] skill 写入是否触发全量 skills prompt 重建  
- [ ] 是否新建 `session_search_tool` 而非扩展 Provider  
- [ ] 是否同时挂载 `EvolutionCoordinator` 与 `PostTurnOrchestrator`  
- [ ] `memory/` 下是否出现 `evolution_*` 文件  
- [ ] Hook 是否直接写资产（只允许 Sink 观察）  

---

## 附录 A：Hermes 五件事对照

| Hermes | 本规格 |
|--------|--------|
| MEMORY.md / USER.md | CuratedMemoryStore + memory_curate |
| skill_manage | SkillManageTool + ProceduralSkillStore |
| background review | EvolutionPipeline + review/runner + subagent |
| nudge counters | PeriodicTurnScheduler |
| flush_memories | flush/runner + Orchestrator.flush_before_loss |
| session_search | P5 Provider 扩展（非新工具栈） |
| Honcho | 不在 v1；可选 MemoryProvider P7 |

---

## 附录 B：一句话定稿

**PostTurnOrchestrator 统一 Turn 后处理；MemoryPipeline 包装 Smart Memory；EvolutionPipeline 经 Backends 产 Mutation、Ledger 审后落盘；共享 gates/scheduler/subagent_runner；新增文件见 §2.2，精简文件见 §2.4，禁止重复见 §2.5 与 §15。**

---

*文档结束 — 实现时严格按 P0→P0.5→P1→P2→P3→P4 顺序，勿跳过 P0.5 refactor。*
