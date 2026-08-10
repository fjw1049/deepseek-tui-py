# 上下文 / KV 前缀优化跟进清单

> 起始：2026-08-10 · 状态：活文档，做完一条就改状态并补上实测数字
> 来源：codex 的五条架构建议 → 逐条对照源码复核后重排出的账单

这份清单的排序原则和 codex 的原提案不同：**先修今天就在错的东西，再修每个 turn 都在多付的钱，契约文档排在它们后面**——因为语义表里「对 KV cache 的影响」那一列该填什么数字，得先量出来。

状态标记：`DONE` 已落地并有测试 · `TODO` 待做 · `DATA` 等真实数据再决定 · `WONTFIX` 明确不做

---

## 一、已完成

### 1. steer 在最后一轮静默丢失 · DONE

`drain_steers()` 只在每轮开头调用，turn 结束时不再读。用户在最终答案流式输出时输入的内容，UI 已经把它持久化成一条「已送达」的用户消息，但模型永远看不到。现在队列非空会成为 turn-end gate，多跑一轮让轮首的 drain 取走。

改动：`engine/handle.py`（`has_pending_steers`）· `engine/orchestrator/core.py`
测试：`tests/engine/test_turn_end_gates.py`

### 2. `turn_end` stop hook 没有次数上限 · DONE

checklist gate 有 `_CHECKLIST_GATE_MAX_FIRES = 3`，stop hook 什么兜底都没有，唯一的终点是 `max_tool_round_trips`（默认 200）。一个无条件 block 的 hook 能让单个 turn 空转 200 轮、按未命中价重发 200 次完整上下文。现在加了同量级的 `_STOP_HOOK_MAX_FIRES = 3`。

改动：`engine/orchestrator/core.py`
测试：`tests/engine/test_turn_end_gates.py`

### 3. Anthropic 投影缺 orphan tool_call 清理 · DONE

OpenAI 路径一直有 `_strip_orphaned_tool_calls` 兜底，Anthropic 路径没有——而两种 wire 格式都会拒绝没有配对 `tool_result` 的 `tool_use`。配对失效不需要谁写 bug：压缩和 L0 按下标挑消息，被 pin 住的 `assistant(tool_use)` 可能活下来，而它的 `tool_result` 已被摘要掉。

抽成了 provider 无关的 `client/normalize.py::drop_orphaned_tool_blocks`，在 `Message` 层做，两条投影路径共用，以后新增 provider 不可能漏。

改动：`client/normalize.py`（新增）· `client/chat_messages.py` · `client/anthropic.py`
测试：`tests/test_tool_pairing_projection.py`

### 4. L0 hard clear 每轮打断 KV 前缀 · DONE

工具结果的「年龄」按用户轮次递增（`_turn_index_from_end` 数的是这条消息之后还出现过几条 USER 消息），所以长会话里**每一轮**都有一批结果刚好跨过 `hard_clear_age_turns = 10`。清理它们会重写位于 payload 深处的内容，而前缀缓存从头匹配，于是整条尾巴每轮按全价重新计费。

25 轮工具密集会话实测（合成，非真实会话）：

| 策略 | 可缓存前缀 | 平均 payload | 有效输入计费 |
|---|---|---|---|
| 每轮清理（原状） | 26.7% | 59,990 字符 | 基准 |
| 每 4 轮 | 57.9% | +7.5% | **−32.3%** |
| 每 8 轮 | 65.5% | +17.6% | **−36.5%** |
| 完全不清理 | 75.4% | +43% | −39.7% |

**注意结论里被推翻的那一半：** hard clear 不是边角料，它撑起将近一半的窗口（去掉它 payload 平均涨 43%、最终窗口翻倍，会更频繁触发 rewrite/cycle）。所以做法是**批量化，不是移除**。

实现：`ToolPruneConfig.hard_clear_min_reclaim`（默认 0 保持原行为），先只读试算可回收字符数，不够就本轮不清、内容维持软裁剪状态、前缀完整；攒够 `L0_HARD_CLEAR_MIN_RECLAIM = 16_000` 一次性清掉。压力到 rewrite 档（0.75）时无条件清理——那时窗口比缓存重要，且 rewrite 本来就要打断前缀。

顺带修掉一个既有浪费：eager 清理连 5 字符的 `"short"` 结果也会重写成 31 字符占位符（**内容变大了还顺手打掉前缀**）。试算把负收益记为 0，自然跳过。

改动：`engine/capacity.py` · `engine/orchestrator/maintenance.py`
测试：`tests/contract/test_l0_hard_clear_batching.py`

### 5. 前缀打断归因探针 · DONE（有已知盲区，见 P1）

`prefix_cache round=… ratio=…` 只说缓存掉了，不说为什么。新增 `engine/prefix_probe.py`：按 round 给请求的每个可缓存单元打指纹，与上一轮比对，第一个不匹配的就是元凶。

指纹只算 `role + content`，**故意不含 `origin`**——`origin` 是会话内部标签、不上 wire，算进去会报告 provider 根本看不见的「打断」，而一个会误报的诊断比没有诊断更糟。`origin` 反过来是最好的归因标签。`_digest` 也**故意不 `sort_keys`**：provider 看到的是序列化器实际吐出的键序，归一化会掩盖 tools schema 构造不稳这种真问题。

开销 2.6 ms（800 条消息 / 60 万字符），挂在 `logger.isEnabledFor(INFO)` 上。

改动：`engine/prefix_probe.py`（新增）· `engine/orchestrator/core.py`
测试：`tests/engine/test_prefix_probe.py`

---

## 二、现在能观测到什么

两条日志，是后续所有决策的输入：

```
prefix_break round=1 at=43/81 reusable=53% culprit=message[42] role=tool origin=-
l0_hard_clear_deferred reclaimable=2969 threshold=16000
```

`prefix_break` 的读法：
- `at=0` → 静态前缀变了（system prompt 或 tools schema）
- `culprit=… role=tool` → L0 或压缩动了工具结果
- `culprit=… origin=system_reminder` → reminder 注入插在了历史中间
- `origin=compaction_bridge` / `soft_seam` → 压缩/接缝
- **没有这条日志** = 该轮是纯追加，前缀全可复用

`l0_hard_clear_deferred` 的读法：`reclaimable` 每轮递增，说明批量化在生效；它跨过 `threshold` 的那一轮才会出现一次 `prefix_break`。两者的出现频率之比就是实际省下的倍数。

---

## 三、待办

### P1 · 探针的已知盲区（我自己刚引入的，优先补） · TODO

**问题**：`turn.py:311` 实际上 wire 的是 `tools=active_tools or []`，即按 `state.active_tool_names` 过滤后的**子集**；而探针的 slot 0 算的是传给 `_run_conversation` 的**全量** `tools` 目录。deferred 工具一激活，wire 上的 tools 数组就变、同 turn 内前缀就断，**但探针看不到**——而这恰恰是之前判定的最频繁失效源（codex 列的四个失效源全是跨 turn 的，都没覆盖这个）。

**怎么改**：探针需要拿到真正上 wire 的 tools。两条路——把指纹调用下移到 `turn.py` 的 step 循环内（`active_tools` 算出来之后、发请求之前），或让 turn loop 把 `active_tools` 回调上报给 Engine。前者更直接，后者不改 turn.py 的职责。

**验收**：一个测试模拟「tool_search 激活一个 deferred 工具后 `active_tools` 变化」，探针必须报 `at=0`。当前实现下这个测试应该是红的——先确认它红，再修。

### P2 · slot-0 归因太粗 · TODO

现在只能说 `static_prefix(system_prompt|tools)`，无法区分 `tool_activated` / `mcp_discovered` / `plugin_focus` / `system_prompt_changed`。至少把 slot 0 拆成 system_prompt 和 tools 两个单元；tools 那半可以再比对工具**名字集合**的差异，直接把新增/消失的工具名打进日志。

依赖 P1（同一处代码），建议一起做。

### P3 · 拿真实会话校准（不写代码） · DATA

跑几天真实会话，grep 上面两条日志，回答三个问题：

1. `L0_HARD_CLEAR_MIN_RECLAIM = 16_000` 在实际用法下合不合适？（16,000 是在合成会话形态上定的。看 `l0_hard_clear_deferred` 的递增步长和触发间隔：若几十轮都不触发说明太大，若每两轮就触发说明太小。）
2. 除了 L0，还有谁在打前缀？（按 `culprit=` 分组计数。若 `origin=system_reminder` 占大头，那么 reminder 的注入位置比 L0 更值得改。）
3. rewrite 档的无条件绕过是否过于频繁？（`prefix_break` 与 `ratio>=0.75` 同时出现的比例。）

**这一步的结论决定 P4/P5 做多狠**，不要跳过它直接照原提案往下推。

### P4 · 旧 seam 不删，摘要在上下文里存两份 · TODO

L2 触发时 `seam.recompact` 把 L1 的文本合并进新 seam，但全库没有任何地方删掉旧的 L1 消息。为保 prefix 不删是**合理选择**，但这笔 token 税现在没写在任何注释、文档或测试里。

两条出路，二选一，别让它继续处于「没人知道」的状态：
- 删掉旧 seam：承认付一次 miss，换回重复的 token；
- 或写进文档 + 加一个断言两份共存的测试，明确「这是我们知情并接受的成本」。

codex 那条建议真正的价值就在这里。

### P5 · 四层语义表 · TODO（等 P3 数据）

同意要做，但反对凭审美填。等 P3 给出真实数字再填「对 KV cache 的影响」那一列。每层回答四句话：**动不动历史 / 保不保 cache / 丢的东西去哪了 / 谁能读回来**。约定：新增压缩手段必须先填表。

### P6 · 两处小账一起清 · TODO

**(a) 注释和代码不一致**：`orchestrator/maintenance.py` 里注释说只 prune「最后一个」soft-seam 之前（`the last soft-seam insert`），代码取的是**第一个**（命中即 `break`）。二者选一并对齐——注意这会改变 L0 的可变边界，需要一个测试锁住选定语义。

**(b) 可见性**：把 `_emit_checklist_turn_end_reconcile` 从 turn 末尾自动执行，挪到 gate 放行的那个分支里显式调用。**行为完全不变**，只是让「模型不听话时是谁替它改了 todo 状态」在代码里看得见。

### P7 · 体验 · TODO

- steer 排队时给 UI 一句提示（「将在当前命令结束后注入」）。零引擎风险，把体验坑变成体验预期。修完 §一.1 之后这条措辞才是诚实的。
- 只给 `exec_shell` 一档 soft signal：`steering_event` 置位时把前台进程转后台、返回 `process_id`。shell 已经有后台启动、`wait_background_process`、`cancel_background_process`、发 stdin 的全套能力，唯一缺的就是「运行中转后台」这一步。其他工具一律忽略这个信号。

---

## 四、明确不做

| 建议 | 为什么不做 |
|---|---|
| SoftRequirement 统一框架 | 6 处各自能跑的 gate，抽象它撞 `AGENTS.md` 第 2 条。等第 7 个 gate 真要加时再说 |
| 「唯一 to_provider」大重构 | 前提不成立——resume 并没有独立投影，它产出 `Message` 后走同一个函数。真问题只有 orphan 清理不对等，已在 §一.3 修掉 |
| 全工具中断策略表 | 四档策略是为想象中的场景设计的。今天只有 foreground shell 一个真缺口 |
| 拆 `core.py` | 139KB、`_run_conversation` 极长，确实是负担，但没引发过事故，改动风险和收益不成比例。等下次真要动那块时顺手拆 |

---

## 五、顺手记下的无关死代码（按规矩只提不删）

- `strict_tool_mode` 只剩一句过期注释
- `force_update_plan_first` 永远传 `False`，`engine/tools.py:321` 那段收窄逻辑不可达
- `invalidate_skills_prompt_cache()` 无任何调用者
- `seam.recompact` 里叫 `recent` 的那个变量，装的其实是**旧**消息段，命名是反的
- `tests/engine/test_context_compression_policy.py` 的 `test_should_compact_uses_rewrite_ratio` 和 `test_measure_context_pressure_prefers_real` **依赖执行顺序**：单独跑绿，一旦有任何测试先导入过 Engine 模块（`engine.orchestrator.core`）就红。根因是模型窗口的全局 override 在导入时被写入，`context_window_for_model` 随之改变。写新测试时若要断言压力比例，**按窗口比例推导 token 数**而不要硬编码（见 `test_l0_hard_clear_batching.py` 的做法）

---

## 六、验证基线（改动这些路径时照此复核）

全量测试对比 HEAD 快照，而不是只看绝对失败数——仓库里有 120 条既有失败（沙箱内的 git / 网络 / shell 限制）：

```bash
mkdir .baseline && git archive HEAD | tar -x -C .baseline --exclude='.cursor*'
(cd .baseline && python -m pytest tests -q -p no:cacheprovider) 2>&1 \
  | grep -E "^(FAILED|ERROR)" | sed 's/ - .*//' | sort > /tmp/base.txt
python -m pytest tests -q -p no:cacheprovider 2>&1 \
  | grep -E "^(FAILED|ERROR)" | sed 's/ - .*//' | sort > /tmp/now.txt
comm -13 /tmp/base.txt /tmp/now.txt   # 有输出即为回归
```

lint / mypy 同理：`capacity.py`、`core.py` 都有既有告警，按**内容**（而非行号）对比基线。
