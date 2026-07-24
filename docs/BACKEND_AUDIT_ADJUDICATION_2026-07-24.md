# 后端 Bug 报告复审裁决（对照源码 × GLM 反馈）

> 日期：2026-07-24（复审）  
> 方法：对 GLM 标为「不成立 / 部分属实 / 降级」的条目，逐条读当前源码并做最小复现  
> 结论先行：**原报告整体可信；GLM 命中率判断大体合理，但对 P0#12 的否决是错的；若干条应降级或收窄前提**

---

## 最终结论（一句话）

原报告可作为修复蓝图；**剔除/修正 3 类问题后照修**：  
（1）GLM 正确否决或降级的条目；（2）我方 Critical 描述过度绝对的条目；（3）**驳回 GLM 对 P0#12 的否决——Workflow 双调度成立**。

---

## P0 最终裁决表（15 → 修订后优先级）

| # | 主题 | 原判定 | GLM | **最终裁决** | 源码依据 |
|---|------|--------|-----|--------------|----------|
| 1 | HTTP 裸跑工具 | Critical | 确认 | **Critical 保留** | `runtime.py` `handle_tool` 直调 `execute` / MCP，无审批 |
| 2 | 策略放行破坏命令 | Critical | 确认 | **Critical 保留** | TOML allow 短路；`\|` 不进 chaining；`cat\|sh`→SAFE |
| 3 | 审批指纹盲区 | Critical | 确认 | **Critical 保留** | `approval.py` 剥全部 `-` flags；`rm`≡`rm -rf` |
| 4 | Skill 路径逃逸 | Critical | 确认 | **Critical 保留** | `skills.py` `target_dir / name` 无 resolve/relative_to |
| 5 | MCP SSE 跨域 endpoint | Critical | 确认 | **Critical 保留** | `transport.py` 接受绝对 URL，POST 带 headers |
| 6 | Rewind 误删文件 | Critical | 确认 | **Critical 保留** | `_run_git` 任意失败→`None`；checkpoint 把 `None` 当不存在→`unlink` |
| 7 | Cancel 当成功 | Critical | 窄窗成立 | **High（收窄）** | handoff 中 `cancel_event`→`return False` 后直接 `return result`（`cancelled` 仍 False）。**仅「流式已完成 + handoff 等待中」** |
| 8 | Compact 脏 token | Critical | 部分 | **High（降级）** | `last_real_input_tokens` 在 cycle/compact 后不刷新属实；`MIN_SUMMARIZE_MESSAGES` 有防护，非必然二次 rewrite |
| 9 | AGENTS.md 静默替换 | Critical | 确认 | **Critical 保留** | 超大 raise→warning→auto-gen；`warnings` 未被 prompt 消费 |
| 10 | Patch 插错行 | Critical | 部分 | **High（改写）** | **纯新增 + 合法 start_idx：fuzz=0 即命中，不偏移（已实测）**；有 context 且 exact 失败时，同 fuzz 带内 **low→high 取最早匹配** 仍成立 |
| 11 | 未信任 persona 有 shell | Critical | 确认 | **Critical 保留（第一优先）** | `FOCUS_READ_BASE` 含 write/shell/spawn；`types.py` 注释自证 misnamed |
| 12 | Workflow 双调度 | Critical | ❌否决 | **Critical 保留 — 驳回 GLM** | 见下文专节；已复现 B 被 start 两次 |
| 13 | Task stub 假完成 | Critical | 部分 | **High（降级）** | 确标 `COMPLETED`，但 summary 含 `[stub]`，非完全静默 |
| 14 | Compact 抢 turn | Critical | 确认 | **Critical 保留** | `compact_thread` 两段锁、第二段不 re-check `active_turn` |
| 15 | Webhook 卡死流式 | Critical | 确认 | **Critical 保留** | `emit` 同步 await；webhook 10s×3 |

**P0 修订后计数：** Critical 保留 **10** · 降为 High **4**（#7/#8/#10/#13）· 否决 **0**（#12 驳回 GLM）

---

## 专节：为什么驳回 GLM 对 P0#12 的否决

### GLM 说法

> `_drain_ready` 是单协程 await 串行，`ready_ids` 无重复，无双调度。

### 源码事实

1. `_drain_ready` **并非串行单节点**：`scheduler.py:1107-1109` 对 batch 做 `asyncio.create_task` + `gather`，默认 `policy.concurrency = 4`（`models.py`）。
2. Dynamic 节点在执行中会 **嵌套** `await _drain_ready(exclude={step.id})`（约 `1005` / `1042`），此时 **同 batch 的兄弟节点可能仍在跑**。
3. `dag.ready_ids`（`dag.py:45-73`）只排除 `completed|failed|skipped`，**没有 in-flight 集合**。正在执行的 B 仍会出现在 ready 里。

### 最小复现（逻辑等价）

外层 gather 同时 start A(dynamic)+B；A 内嵌套 drain 时 B 尚未 completed → B 再次被 start。本地脚本结果：`B starts count: 2`。

### 裁决

**Bug 成立，维持 Critical。** GLM 误把「外层 while 循环」理解成「全局不会并发」，忽略了 gather 并发 + 嵌套 drain。

---

## GLM「不成立」7 条 — 逐条反驳/采纳

| GLM 条目 | GLM 结论 | **最终** | 说明 |
|----------|----------|----------|------|
| Elevation deny 返回 sandbox_denied | 不成立 | **采纳：原表述打偏** | deny 分支 `tooling.py:830-842` 已返回 `"Sandbox elevation denied"`。原报告真正想说的是 **elevation 已批准后** `retry is None` 时 `return result`（`:850`）仍带回旧 `sandbox_denied`——降为 **Medium**，勿与 elevation deny 混淆 |
| MCP read-only allowlist | 不成立 | **采纳：非 bug** | 有意保守；原报告自己也写了「未发现 bypass」。移出缺陷列表，留作设计说明 |
| M13 Cancel 不解除 wait | 不成立 | **部分采纳** | `cancel()` 会把 status 设为 cancelled（terminal），`wait` ≤50ms 返回——**对 cancel() 路径 GLM 对**。残留：`wait()` 本身不观察 `parent_cancel`/`cancel_token`，父 cancel 仅 set Event、尚未 `cancel(agent)` 时，waiter 可拖到 timeout——降为 **Medium** |
| M15 Workflow 双调度 | 不成立 | **驳回 GLM** | 见上专节 |
| M16 Pre-dirty reconcile 不归因 | 不成立 | **采纳：设计取舍** | 跳 pre_dirty 防误归因；后续变更应靠工具/shell 入账。移出 bug，可作文档/产品说明 |
| M19 Fake-wrapper 跨 chunk 漏 | 不成立 | **驳回 GLM** | GLM 辩护的是「完整 start/end 跨 chunk」（`in_tool_call` 确实持久化）。原报告说的是 **marker 自身被切开**（如 `'<tool'`+`'_call>…'`）。实测：切开后 **整段泄漏**。维持 **Medium** |
| M1 Cancel 当成功（简版） | 窄窗 | **采纳收窄** | 与 P0#7 合并：成立但前提是 handoff 窗口 |

---

## 其它关键复核（影响严重度）

### P0#10 Patch

| 场景 | 结果 |
|------|------|
| 纯新增、`old_lines=[]`、合法 `start_idx` | **fuzz=0 命中，不偏移**（实测 insert 在期望行） |
| 有 context、exact 失败、同 fuzz 带内多处可匹配 | **low→high 取最早**，可错位点（实测） |
| 默认 `MAX_FUZZ=50` | 属实 |

→ Critical 标题「纯新增插错 50 行」**过度绝对**；保留 High：「模糊匹配同带取最早 + 默认 fuzz 过大」。

### P0#7 Cancel / handoff

```
_handle_subagent_turn_handoff:
  cancel_event → return False
_run_conversation:
  if handoff: continue
  else: return result   # 未检查 cancel，result.cancelled 仍为 False
上层:
  if result.cancelled: …  # 不进
  turn_ok = outcome==SUCCESS → 持久化
```

成立；窗口窄 → **High**。

### P0#8 Compact token

`should_compact(..., real_input_tokens=last_real_input_tokens)`；cycle/compact 成功路径未见清零/重估。有 `MIN_SUMMARIZE_MESSAGES` 门槛 → **High** 非必然 Critical。

### Fake-wrapper

```text
filter('<tool') + filter('_call>SECRET</tool_call>ok')
→ '<tool_call>SECRET</tool_call>ok'  # 未剥离
```

GLM 否决不成立。

---

## 修订后的立即修复优先级（可执行）

### 第一梯队（确认 Critical，立刻修）

1. **未信任 persona 有 shell**（P0#11）— 一行级：未信任改用纯读工具集  
2. **Rewind 误删**（P0#6）— `_run_git` 区分缺路径 vs 故障；故障→`_Unresolvable`  
3. **策略放行**（P0#2）— allow 后仍跑 heuristics；检测 `\|`  
4. **审批指纹**（P0#3）— 保留破坏性 flags  
5. **Skill 路径逃逸**（P0#4）— sanitize + `relative_to`  
6. **HTTP 裸跑 + MCP SSE 外泄**（P0#1 / #5）  
7. **Compact 抢 turn**（P0#14）  
8. **Webhook 卡流式**（P0#15）  
9. **AGENTS.md 静默替换**（P0#9）  
10. **Workflow 双调度**（P0#12）— 加 `in_flight`；嵌套 drain 排除 in-flight  

### 第二梯队（High，尽快）

- P0#7 Cancel/handoff 窄窗  
- P0#8 Compact 脏 token  
- P0#10 Patch 最早匹配（非「纯新增偏移」叙事）  
- P0#13 Task stub → 勿标生产 COMPLETED（或硬失败）  
- M19 双 StreamDone / provider 切换泄漏 pool  
- M17 cancel 持久化 / seq checkpoint  
- M13 send_input/interrupt 无效、mutation sink 生命周期  
- M10 enabled/并发 ensure_client 等（原 High 仍多数成立）  

### 第三梯队（降级 / 剔出 bug 列表）

- MCP read-only allowlist → 设计说明  
- Pre-dirty reconcile → 设计取舍  
- Elevation deny 错类型 → 改为「elevate 后 retry None」Medium  
- 原报告第 5 节产品问题 → 先拍板再改  

---

## 对两边的元评价

| 来源 | 评价 |
|------|------|
| Cursor 原报告 | 证据意识强、覆盖面够；个别 Critical 绝对化（Patch 纯新增、Cancel 常态化、Task stub「完全静默」）；P0#12 判断正确 |
| GLM 复审 | 对窄窗/标记/防护门槛的收紧有价值；**错误否决 P0#12**；错误否决 Fake-wrapper 切开 marker；把 elevation 的另一条路径当成原 finding |

**合成可信度（修订后）：** 原报告缺陷条目在「剔除设计项 + 收窄前提」后，**可执行 Critical ≈ 10 条，High 仍为修复主体**。不要按 GLM 去掉 P0#12。

---

## 附录：复现命令（Workflow 双调度逻辑）

```python
# 逻辑等价：ready_ids 无 in_flight + gather 并发 + 嵌套 drain
# 期望：B starts count == 2
```

见复审过程中的本地脚本（A dynamic 嵌套 drain 时 B 仍 ready）。

Patch / Fake-wrapper 实测：

```bash
PYTHONPATH=src .venv/bin/python -c "..."  # 见会话记录
```
