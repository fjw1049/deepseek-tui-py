# Experience Evolution — 遗留问题与待办

> **版本**: 1.0  
> **关联规格**: [EXPERIENCE_EVOLUTION_IMPLEMENTATION.md](./EXPERIENCE_EVOLUTION_IMPLEMENTATION.md)  
> **状态**: 主流程已落地；本文仅记录**不挡主流程**的后续项。

---

## 1. 这些能力各自为了什么

| 范围 | 目的 |
|------|------|
| **PostTurn（P0 / P0.5）** | Turn 结束后统一调度 Memory capture 与 Evolution review/flush，避免 Engine 直调与 Orchestrator 双路径 |
| **Evolution core（P1–P4）** | 策展记忆（`MEMORY.md` / `USER.md`）+ 技能演化（`.deepseek/skills/`）+ ledger 审计 + 后台复盘/抢救 |
| **P5 Recall 摘要** | `conversation_search` 返回可读摘要，避免 L0 命中堆砌 |
| **P6 Workbench 审批** | `mode=suggest` 时，高风险变更需用户确认后再落盘 |
| **P7 Trajectory sink** | 可选 JSONL 轨迹，仅观察、不写 skill/memory |

**口诀**（与规格一致）：Smart Memory 管「知道什么」；Evolution 管「下次怎么做更好」。

---

## 2. 必要性 vs 可选

### 2.1 必要（主流程 / 架构依赖）

- `post_turn/` 编排与 `MemoryPipeline` 包装
- `evolution/` stores、backends、ledger、review/flush、pipeline
- Engine 挂载 `PostTurnOrchestrator`；compact / exit 前 flush
- 配置与 DB migration（`evolution_events`）
- **默认 `evolution.enabled = false`**：未开启时行为与改造前一致（Smart Memory 仍经 PostTurn）

### 2.2 可选（体验、运维、质量；不开启也不影响聊天主路径）

| 项 | 说明 | 何时才需要 |
|----|------|------------|
| P5 LLM 摘要 | 当前为 extractive 按 thread 分组摘要 | 召回质量仍不满意时 |
| P6 Workbench UI | 审批卡片 + `/v1/evolution/*` | `evolution.enabled` + `mode=suggest` 且产生 `propose` |
| P7 Trajectory | `evolution.sinks.trajectory_enabled` | 离线分析 / 调试 evolution 决策 |
| `remember` → curated USER 双写 | 规格 P2 可选项 | 希望用户笔记与策展画像自动同步 |
| OpenAPI / contract 测试 | `/v1/evolution/*` 契约 | CI 回归、对外 API 文档 |
| `engine_bridge` evolution 分支 | `evolution.suggested` SSE 序列化 | 非 thread_manager 的 SSE 消费路径需一致时 |

---

## 3. 主流程验收（当前结论）

在 **`evolution.enabled = false`（默认）** 下：

- 聊天、工具、Smart Memory capture 正常；测试：`tests/post_turn`、`tests/memory/` 已通过。
- 无 Evolution 工具注册、无 curated stable 注入、无 review 调度。

在 **`evolution.enabled = true`** 下：

- 主工具 `memory_curate` / `skill_manage` → ledger → backend 落盘。
- Review / flush 子 agent 不污染 `session_messages`。
- `mode=suggest`：propose 项可走 Workbench 审批；`mode=auto_patch`：低风险 `skill_patch` 自动应用。

**结论**：不必为下列 backlog 阻塞发布或日常使用；按需迭代即可。

---

## 4. 待办清单（Backlog）

优先级：**P2** = 有明确用户痛点再做；**P3** = 质量/工程债；**P4** = 低优先级或观望。

### 4.0 已修复（2026-06-02～，原 Codex P1/P2 + P0/P1 优化）

| 项 | 修复 |
|----|------|
| P0 curated store | `.lock` RMW、超限拒绝、dedupe、多 match、`usage`/`current_entries` |
| P0 ledger/tools | `submit` 返回 fresh record；工具 JSON 含 decision/status/usage/entries |
| P0 skill store | patch `file_path`、miss preview、原子写、`write_file` 扫描 |
| P1 review buffer | 最近 8 turn rolling window + 单条 1200 字符截断 |
| P1 skill nudge | 跨 turn 累计 `tool_rounds`；`skill_manage` 后 reset |
| P2 prompts/search | 工具描述 + `conversation_search` workspace 默认排除当前 thread |

### 4.0b 历史修复（2026-06-02，原 Codex P1/P2）

| 原 ID | 修复 |
|-------|------|
| P1 evidence | `Engine._sync_tool_turn_evidence`：turn 开始写入进行中 evidence，turn 结束 finalize |
| P1 review store | `run_evolution_review` 注入 `curated_store` / `skill_store` |
| P1 mutation 收集 | `collect_mutations_from_tool_results` 仅收集 `ok: true` JSON |
| P1 skill 路径 | `ProceduralSkillStore._resolve_skill_file_target` 拒绝绝对路径与越界 |
| P2 LRU flush | `_flush_engine_memory(engine, …)`；LRU 用已 pop 的 `evicted_state.engine` 直接 flush |
| P1 fallback capture | `_sync_tool_turn_evidence` 始终写 `_current_turn_evidence`；仅 ledger 存在时写 tool metadata |
| P1 auto_patch policy | `auto_patch` 仅将 `ledger.skill_patch=propose` 升级为 `auto`；`deny`/`auto` 仍尊重配置 |
| P2 evolution scheduler | `EvolutionPipeline` 的 `PeriodicTurnScheduler` 显式 `warmup_enabled=False` |
| P3 孤儿文件 | 删除未引用的 `packages/workbench/.../image.png` |

### 4.1 功能增强

| ID | 优先级 | 标题 | 说明 | 触发条件 |
|----|--------|------|------|----------|
| EE-01 | P2 | P5：LLM 摘要 | 在 `summarize_l0_hits` / Provider 层增加可选 LLM 压缩；保留 `summarize=false` 原始路径 | 对话搜索仍难读、命中过多 |
| EE-02 | P2 | `remember` 双写 curated USER | `remember` 工具成功写入后，可选同步 `USER.md` 段落（需 policy + 去重） | 产品要求用户笔记与策展画像一致 |
| EE-03 | P3 | Trajectory 可观测性 | 文档化 `trajectory_path`、样例 JSONL、与 audit 表关系；可选启动 log | 开启 `trajectory_enabled` 的团队 |

### 4.2 工程与质量

| ID | 优先级 | 标题 | 说明 | 触发条件 |
|----|--------|------|------|----------|
| EE-04 | P3 | Contract / OpenAPI | 为 `GET/POST /v1/evolution/*` 增加 contract 或 acceptance 测试 | Workbench 外客户端接入 API |
| EE-05 | P3 | pytest 模块名冲突 | `tests/post_turn/test_scheduler.py` 与 `tests/memory/test_scheduler.py` 同名；短期用 `--import-mode=importlib`，长期重命名其一 | 本地/CI 偶发 collection 失败 |
| EE-06 | P4 | P0.5 warmup 完全 parity | `memory/native/scheduler.py` 的 warmup 路径仍用 `_ThreadScheduleState`；非 warmup 已委托 `PeriodicTurnScheduler` | L1 warmup 行为与 refactor 前 diff 可疑 |
| EE-07 | P4 | `engine_bridge` 全覆盖 | 已支持 `EvolutionProposalEvent`；确认 `/prompt/stream` 等路径均经 bridge 或 thread_manager | 出现「SSE 有事件但 UI 无卡片」 |

### 4.3 文档与配置

| ID | 优先级 | 标题 | 说明 |
|----|--------|------|------|
| EE-08 | P3 | 运维 Runbook | `enabled` / `mode` / `ledger.*` 组合表；故障：review 不触发、审批 503 `evolution_disabled` |
| EE-09 | P4 | 规格 Checklist 勾选 | 将 [EXPERIENCE_EVOLUTION_IMPLEMENTATION.md §13](./EXPERIENCE_EVOLUTION_IMPLEMENTATION.md#13-分期实现-checklist) 与仓库实际状态对齐 |

---

## 5. 已实现快照（避免重复劳动）

以下在 backlog 中**不必再做**，除非回归失败：

- PostTurn：`evidence`, `gates`, `scheduler`, `orchestrator`, `memory_pipeline`
- Evolution：curated/skill stores & backends, `ledger`, `audit`, `signals`, `review`/`flush`, `pipeline`, tools
- Engine / prompts / thread_manager / TUI flush 接入
- P5 extractive：`memory/native/l0_summarize.py`，`search_conversations(summarize=...)`
- P6 后端：`/v1/evolution/pending|approve|reject`，SSE `evolution.suggested`；Workbench `EvolutionBubble`
- P7：`evolution/sinks/trajectory.py`（pipeline 接入；**非** hooks 写入）
- 测试：`tests/post_turn/`、`tests/evolution/`、memory 回归（含 scheduler / l0_summarize）

---

## 6. 快速配置参考

```toml
[post_turn]
enabled = true

[evolution]
enabled = false          # 默认关闭；主流程零影响
mode = "suggest"         # 或 "auto_patch"

[evolution.sinks]
trajectory_enabled = false
```

开启 Evolution 后若审批列表为空，检查：`mode`、ledger 决策是否为 `propose`、线程 engine 是否已加载（API 503 `evolution_disabled`）。

---

## 7. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-06-02 | 初版：区分必要/可选，主流程验收通过，登记 EE-01～EE-09 |
| 2026-06-02 | 修复 Codex P1/P2 五项；新增 `tests/evolution/test_main_tool_evidence.py` 等 |

---

*主流程无问题时，以本文 backlog 为准排期；新项请追加表格行并更新 §7。*
