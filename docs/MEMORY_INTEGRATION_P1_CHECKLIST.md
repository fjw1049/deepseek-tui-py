# P1 实施清单 — 智能记忆（Native L0+L1+FTS）

> 依据 [`MEMORY_INTEGRATION.md`](./MEMORY_INTEGRATION.md) **v3**。  
> 目标：可拆 PR、可验收、不改 Engine 主循环结构。  
> **本阶段不写**：Sidecar、embedding、L2/L3、`memory_search` 工具（属 P2）。

---

## 0. P1 交付边界（一页纸）

| 做 | 不做 |
|----|------|
| `MemoryProvider` + `NativeMemoryProvider` | Node Gateway / Sidecar |
| L0 JSONL + L1 SQLite FTS + 时间衰减 | L2 scene / L3 persona 生成 |
| Turn 前 recall、Turn 后 capture、thread flush | Context Offload / MMD |
| `build_system_prompt(memory_recall=…)` 分层 | 改写历史 `session_messages` |
| 门控 + workspace + 剥离 `<relevant-memories>` | 替换 SQLite transcript |

**建议 PR 顺序**：PR-1 配置与协议 → PR-2 存储与 L0 → PR-3 L1+调度 → PR-4 Engine 挂接 → PR-5 测试与文档。

**实现状态（2026-05-29）**：Native 全链路已接线；`tests/memory/` + contract **33 passed**；live `-m live` **2 passed**（需有效 API key）。  
**延后**：§6 手验 C–F → [`MEMORY_INTEGRATION_BACKLOG.md`](./MEMORY_INTEGRATION_BACKLOG.md)。Sidecar 不实现。

---

## PR-1：配置、协议、Coordinator 骨架

### 新建文件

| 文件 | 职责 | 要点 |
|------|------|------|
| `src/deepseek_tui/memory/provider.py` | `RecallResult`、`CaptureInput`、`MemoryProvider` Protocol | `inject_position`；`l1_context` 非 `prepend_user` |
| `src/deepseek_tui/memory/gates.py` | `should_capture_turn()` | 见 v3 §3.3；单测友好 |
| `src/deepseek_tui/memory/coordinator.py` | `MemoryCoordinator` | 读 config；调 provider；门控；超时 recall |
| `src/deepseek_tui/memory/formatting.py` | `wrap_relevant_memories()` / `strip_relevant_memories()` | 与 TencentDB 标签一致，供持久化清洗 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/deepseek_tui/config/models.py` | 新增 `MemorySmartConfig`（或扩展 `MemoryConfig`）：`enabled`, `provider="native"`, `data_dir`, `recall_*`, `capture_min_user_chars=20`, `l1_*`, `l1_decay_half_life_days=180`, `l1_inject_position="user"` |
| `src/deepseek_tui/config/models.py` | `Config` 增加 `memory_smart: MemorySmartConfig`；`smart_memory_enabled()` 辅助方法 |
| `config.example.toml` | 增加 `[memory.smart]` 注释块（默认 `enabled = false`） |
| `src/deepseek_tui/memory/__init__.py` | 导出 Coordinator、RecallResult 等 |

### `gates.py` 逻辑（实现时照抄 v3）

```python
def should_capture_turn(
    user_text: str,
    *,
    had_tool_calls: bool,
    success: bool,
    min_chars: int = 20,
    skip_slash: bool = True,
) -> bool:
    if not success:
        return False
    if had_tool_calls:
        return True
    text = user_text.strip()
    if skip_slash and text.startswith("/"):
        return False
    if len(text) < min_chars:
        return False
    # 可选：纯确认语正则
    return True
```

### 验收（PR-1）

- [ ] `Config` 解析 `config.example.toml` 不报错
- [ ] `should_capture_turn("好的", had_tool_calls=False)` → False
- [ ] `should_capture_turn("帮改成 async", had_tool_calls=True)` → True
- [ ] `enabled=false` 时 Coordinator 所有方法 no-op

---

## PR-2：存储层 + L0 录制

### 新建文件

| 文件 | 职责 |
|------|------|
| `src/deepseek_tui/memory/native/__init__.py` | 包导出 |
| `src/deepseek_tui/memory/native/store.py` | `MemoryStore`：建表、FTS、CRUD |
| `src/deepseek_tui/memory/native/l0_recorder.py` | 增量写 JSONL；cursor；sanitize |
| `src/deepseek_tui/memory/native/provider.py` | `NativeMemoryProvider` 骨架（先实现 L0+capture） |

### SQLite Schema（P1 必建）

```sql
-- memories (L1)
CREATE TABLE memories (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  type TEXT NOT NULL,           -- persona | episodic | instruction
  workspace TEXT,              -- 绝对路径，可 NULL 表示全局
  thread_id TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  last_recalled_at INTEGER
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
  content,
  content='memories',
  content_rowid='rowid'
);

-- l0_cursor（每 thread 一条，或 json 文件 sidecar）
CREATE TABLE l0_cursors (
  thread_id TEXT PRIMARY KEY,
  last_timestamp_ms INTEGER NOT NULL,
  last_message_count INTEGER NOT NULL DEFAULT 0
);
```

**Recall 排序 SQL 草图**（`search_memories` / recall 共用）：

```sql
-- bm25 或 fts5 rank + 衰减（在 Python 里算 decay 乘子亦可）
SELECT m.*, rank AS fts_score
FROM memories_fts f
JOIN memories m ON m.rowid = f.rowid
WHERE memories_fts MATCH ?
ORDER BY fts_score * decay(m.created_at) * workspace_boost DESC
LIMIT ?;
```

`decay(created_at)`：`0.5 ** (age_days / half_life)`，`half_life=0` 时返回 1。

### 目录布局

```text
~/.deepseek/memory_data/          # 或 config.memory_smart.data_dir
  l0/{thread_id}.jsonl
  store/memory.db
```

### `l0_recorder.py` 要点

- 输入：`thread_id`, `messages` 增量, `user_text`（净文本）, `workspace`
- 复用/移植 TencentDB 思路：`strip`、跳过空、短消息（L0 用较宽门槛）
- 更新 `l0_cursors` 原子（文件锁或 SQLite 事务）
- **不**在本 PR 调 LLM

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/deepseek_tui/config/paths.py` | 可选：`user_memory_data_dir()` → `~/.deepseek/memory_data` |

### 验收（PR-2）

- [ ] 手动调用 `capture` 后 `l0/{thread_id}.jsonl` 有增量行
- [ ] 重复 capture 同 cursor 不重复写
- [ ] `memory.db` 表存在且 FTS 可 `MATCH '关键词'`

---

## PR-3：L1 提取 + 调度器 + Recall

### 新建文件

| 文件 | 职责 |
|------|------|
| `src/deepseek_tui/memory/native/l1_extractor.py` | 调 `LLMClient`；prompt；解析 JSON；`confidence` 过滤 |
| `src/deepseek_tui/memory/native/scheduler.py` | `every_n` + `idle_timeout`；后台 `asyncio.create_task` |
| `src/deepseek_tui/memory/prompts/l1_extraction.py` | L1 system/user prompt（可从 TencentDB 移植精简） |

### 修改 `native/provider.py`

实现完整：

| 方法 | 行为 |
|------|------|
| `start()` | 打开 DB；确保目录 |
| `recall()` | FTS + 衰减 + workspace boost + threshold；填 `RecallResult`；更新 `last_recalled_at` |
| `capture()` | L0 写入；`notify_conversation` 计数；达阈值触发 L1 job |
| `flush_session()` | flush 该 thread 的 pending buffer / timer |
| `stop()` | 关闭连接；cancel 后台 task |

### L1 提取触发（scheduler）

- 维护 per-`thread_id`：`conversation_count`, `pending_messages`, `l1_timer`
- `every_n` 默认 5；`idle_timeout` 默认 600s
- L1 job：读 L0 增量 → `l1_extractor` → insert memories（`should_extract` 过滤）
- P1 **不做** warm-up 翻倍（可 P2 加）

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/deepseek_tui/memory/native/provider.py` | 注入 `LLMClient`（由 Engine 传入） |

### Engine 传入 LLM

在 `Engine.create` 创建 Coordinator 时传入 `client`（与 Rlm 相同模式）。

### 验收（PR-3）

- [ ] 5 轮实质对话后 `memories` 表有新行，`confidence >= 0.6`
- [ ] recall 返回 `l1_context` 含相关条目
- [ ] 200 天前插入测试记忆，recall 排序低于昨天插入的同类记忆（#8b）
- [ ] workspace A 的记忆在 workspace B 的 recall 中不应排第一（#3）

---

## PR-4：Engine / Prompts / 持久化清洗（宿主挂接）

### 4.1 `engine/prompts.py`

**签名扩展**：

```python
def build_system_prompt(
    ...,
    memory_enabled: bool = False,
    memory_path: Path | None = None,
    memory_recall: RecallResult | None = None,  # 新增
) -> str:
```

**拼装顺序**（在现有 `render_environment_block` 之后、`Context Management` 之前）：

```python
# 稳定记忆层
if memory_recall and memory_recall.append_system:
    full_prompt += "\n\n" + memory_recall.append_system

# ... 现有 skills、COMPACT_TEMPLATE ...

# volatile 边界之后、handoff 之前或之后按 inject_position：
if (
    memory_recall
    and memory_recall.l1_context
    and memory_recall.inject_position == "system_volatile"
):
    full_prompt += "\n\n" + wrap_relevant_memories_block(memory_recall.l1_context)
```

**`memory_enabled` / mode 逻辑**：

| `memory.smart.enabled` | `memory.mode` | `memory.md` | recall |
|----------------------|---------------|-------------|--------|
| false | any | 按原 `memory_enabled()` | 无 |
| true | manual | 是 | 无 |
| true | hybrid | 是 | 是 |
| true | auto | 否（或仅 fallback） | 是 |

建议：`Engine` 增加 `smart_memory_mode: str`，由 config 解析。

### 4.2 `engine/engine.py`

**`Engine.create`**（约 454 行附近）：

```python
from deepseek_tui.memory.coordinator import MemoryCoordinator
from deepseek_tui.memory.native.provider import NativeMemoryProvider

# 在 engine 构造后：
if cfg.memory_smart.enabled:
    provider = NativeMemoryProvider(cfg, client, logger)
    await provider.start()
    engine.memory_coordinator = MemoryCoordinator(cfg, provider)
else:
    engine.memory_coordinator = None
```

**`shutdown_session`**：

```python
if self.memory_coordinator:
    await self.memory_coordinator.stop()
```

**`_handle_send_message_inner`**（约 701–774 行）：

```python
# prepare_turn_for_model 之后
workspace = str(self.tool_context.working_directory.resolve())
thread_id = self._resolve_thread_id_for_memory(ctx)  # 见下

memory_recall = None
if self.memory_coordinator:
    memory_recall = await self.memory_coordinator.recall_for_turn(
        thread_id, processed.model_text, workspace=workspace,
    )

# build_system_prompt 传入 memory_recall=memory_recall
# inject user 仅 inject_position == "user"
```

**Turn 末 capture**（`TurnCompleteEvent` 成功后，约 845–857 行）：

```python
if self.memory_coordinator and not result.cancelled:
    await self.memory_coordinator.capture_after_turn(
        thread_id=...,
        user_text=original_user_text,
        messages=...,  # 本轮增量
        workspace=workspace,
        had_tool_calls=len(result.tool_calls) > 0,
        success=True,
    )
```

**`thread_id` 来源（关键）**：

| 运行方式 | 建议 |
|----------|------|
| Workbench / Runtime | `ThreadManager` 在 `start_turn` 时 `engine._memory_thread_id = thread_id` |
| TUI CLI | `session_id` 或 `_cycle_session_id` 或持久化 session 文件 id |

P1 最小方案：在 `Engine` 增加 `memory_thread_id: str | None`，由 `RuntimeThreadManager.start_turn` 赋值；TUI 用 `uuid` session 或 cwd hash fallback。

### 4.3 `app_server/thread_manager.py`

| 位置 | 改动 |
|------|------|
| `start_turn` / 创建 engine 后 | `engine.memory_thread_id = thread_id` |
| 线程淘汰/删除前 | `await engine.memory_coordinator.flush_session(thread_id)` |
| 持久化 turn items 前（若有 user 文本） | `strip_relevant_memories(content)` |

搜索 `persist` / `TurnItem` 写入点，在 **user role** 入库前 strip。

### 4.4 `engine/context.py` 或 `tui/app.py`

若 TUI 路径也调 `build_system_prompt`，确保传入相同 `memory_recall` 参数（或 TUI P1 仅 Workbench 启用，文档注明）。

### 验收（PR-4）

- [ ] v3 验收表 #1–#7 全部通过
- [ ] `build_system_prompt` 单测：有/无 `memory_recall` 时层位正确
- [ ] Engine 外无 `system_prompt += recall` 拼接

---

## PR-5：测试与文档

### 新建测试

| 文件 | 覆盖 |
|------|------|
| `tests/memory/test_gates.py` | 门控 AND、slash、tool 豁免 |
| `tests/memory/test_store.py` | FTS、衰减排序、workspace boost |
| `tests/memory/test_l0_recorder.py` | cursor 不重复 |
| `tests/memory/test_coordinator.py` | enabled=false no-op；recall 超时 |
| `tests/memory/test_prompts_memory.py` | `inject_position` 两种拼装 |

### 修改

| 文件 | 改动 |
|------|------|
| `README.md` 或 `docs/MEMORY_INTEGRATION.md` | 增加「如何开启 P1」：`[memory.smart] enabled = true` |
| `config.example.toml` | 示例配置 |

### 可选（P1.5，不阻塞）

| 项 | 说明 |
|----|------|
| `RememberTool` → L1 | `remember` 除写 `memory.md` 外 enqueue 一条高 confidence L1 |
| `threads.memory_mode` | 创建 thread 时写入 meta（P2 也可） |

---

## 文件改动总览

### 新建（约 15 个）

```
src/deepseek_tui/memory/
  provider.py
  gates.py
  coordinator.py
  formatting.py
  prompts/l1_extraction.py
  native/
    __init__.py
    provider.py
    store.py
    l0_recorder.py
    l1_extractor.py
    scheduler.py
tests/memory/
  test_gates.py
  test_store.py
  test_l0_recorder.py
  test_coordinator.py
  test_prompts_memory.py
```

### 修改（约 8 个）

```
src/deepseek_tui/config/models.py
src/deepseek_tui/config/paths.py          # 可选
src/deepseek_tui/engine/prompts.py
src/deepseek_tui/engine/engine.py
src/deepseek_tui/app_server/thread_manager.py
src/deepseek_tui/memory/__init__.py
config.example.toml
docs/MEMORY_INTEGRATION.md              # 加「P1 已实施」链接
```

### 明确不改（P1）

```
src/deepseek_tui/engine/turn_loop.py      # 主循环
src/deepseek_tui/engine/compaction.py
src/deepseek_tui/tools/spillover.py
src/deepseek_tui/tools/builder.py         # P2 再注册 memory_search
```

---

## 实施顺序与依赖

```mermaid
flowchart LR
  PR1[PR-1 Config+Coordinator] --> PR2[PR-2 L0+Store]
  PR2 --> PR3[PR-3 L1+Recall]
  PR3 --> PR4[PR-4 Engine挂接]
  PR4 --> PR5[PR-5 测试]
```

每 PR 应保持 CI 绿：PR-1~3 可用 `pytest tests/memory`；PR-4 前 Engine 行为不变（`enabled=false`）。

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| TUI 无 `thread_id` | P1 文档写明 Workbench-first；TUI 用 fallback id |
| L1 提取拖慢 API | 后台 task；capture 不 await L1 |
| recall 阻塞 turn | `wait_for` + timeout；失败跳过 |
| FTS 中文分词弱 | P2 jieba 或 embedding；P1 接受英文/中文混合弱召回 |
| 与 `memory.md` 重复注入 | hybrid：L3 空时仍可用 memory.md；auto 关 md |

---

## 完成后对照 v3 验收表

复制 [`MEMORY_INTEGRATION.md` §6 P1](./MEMORY_INTEGRATION.md) 表格 #1–#8b，在 PR-5 合并前逐项勾选。

---

## 下一步（P2 预览，本清单不实施）

- `memory_search` / `conversation_search` 工具
- embedding + hybrid RRF
- `RememberTool` → L1 联动
- `inject_position` 实验与指标
- 可选 Sidecar provider
