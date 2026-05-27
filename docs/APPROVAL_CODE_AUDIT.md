# 审批相关函数命名与职责审计

> 回答：「为什么有这么多看起来重复的函数名？」——多数是 **分层 + Tool/MCP 双路径镜像**，不是 copy-paste 错误。

---

## 1. 三层职责（应有，不是重复）

| 层 | 模块 | 何时跑 | 核心问题 |
|----|------|--------|----------|
| **门控** | `tools/approval_gate.py` | 工具执行前 | 要不要拦？弹窗还是 `never` 直接拒？ |
| **展示** | `tools/approval_present.py` | 已决定弹窗后 | 给用户看什么（title/impacts/preview）？ |
| **运行时** | `approval_bridge` / `ApprovalHandler` / Workbench | 等人点按钮 | 怎么挂起、SSE、pending 恢复 |

Rust 对照：`turn_loop` 门控 → `ApprovalRequest::new` 展示 → `ui.rs` 弹窗。

---

## 2. 易混命名（不是重复实现）

### 2.1 门控入口

| 函数 | 说明 |
|------|------|
| `ExecPolicyEngine.evaluate()` | 遗留 API；**门控已委托** `approval_request_for_capabilities()`，仅保留 `PolicyRule` 与会话缓存 |
| `approval_request_for_tool()` / `approval_request_for_mcp()` | Engine 实际路径 |

### 2.2 两套「分类」——输入不同

| 函数 | 输入 | 输出 |
|------|------|------|
| `_classify_category(caps)` | `list[ToolCapability]` | `ToolCategory` 枚举 |
| `classify_tool_category(name)` | 工具名 | `file_write` 等字符串（UI/SSE） |

### 2.3 两套「风险」——语义不同

| 函数 | 输出 | 用途 |
|------|------|------|
| `_assess_risk(caps)` | `low` / `medium` / `high` | 协议 `risk_level`、SSE 兼容 |
| `classify_presentation_risk(...)` | `benign` / `destructive` | UI 二次确认、徽章 |

### 2.4 `build_*` 前缀

| 函数 | 作用 |
|------|------|
| `build_approval_request` | 门控阶段最小 `ApprovalRequest` |
| `approval_request_for_tool` | 门控入口（内部调用 `build_approval_request`） |
| `enrich_approval_request` | 在已有 Request 上填展示字段 |
| `build_impacts` / `build_primary_preview` | 展示文案片段 |

### 2.5 `engine._summarize_call_args`

审批展示由 `enrich_approval_request` + `build_primary_preview` 负责；此函数仅 `tests/test_summarize_call_args.py` 使用。

---

## 3. Tool vs MCP 镜像（intentional）

| Registry 工具 | MCP |
|---------------|-----|
| `needs_tool_approval_prompt(tool, policy)` | `needs_mcp_approval_prompt(name, policy)` |
| `should_block_tool_on_never(tool, policy)` | `should_block_mcp_on_never(name, policy)` |
| `plan_requires_approval(tool, policy)` | `plan_requires_mcp_approval(name, policy)` |
| `approval_request_for_tool(tool, policy)` | `approval_request_for_mcp(name, policy)` |

内部共用 `_gate_action()`；`plan_*` 与 `needs_*` 在 `never` 策略下语义不同（并行 vs 弹窗）。

---

## 4. 运行时层

| 名字 | 层 |
|------|-----|
| `ApprovalHandler.request_approval` | 协议接口 |
| `HttpApprovalHandler` / `TUIApprovalHandler` | 实现 |
| `_handle_approval_flow` | Engine 编排 |
| `approval_request_to_sse_payload` | SSE 序列化 |
| `approvalPayloadFromRecord` / `emitApprovalFromSsePayload` | Workbench |

SSE/pending 中 `title` 与 `description`（及 pending 的 `summary`）为 **向后兼容双写**，非逻辑重复。

---

## 5. 推荐调用链

```
_execute_single_tool
  → approval_request_for_tool / approval_request_for_mcp
  → _handle_approval_flow
       → enrich_approval_request
       → ApprovalRequiredEvent
       → approval_request_to_sse_payload
       → HttpApprovalHandler / TUIApprovalDialog
```

勿用 `exec_policy.evaluate()` 做门控。

---

## 6. 可选后续（P2+）

- 重命名：`_classify_category` → `_category_from_capabilities`；`classify_tool_category` → `presentation_category_for_tool`
- `record_decision` 按 `approval_key` 而非仅 `tool_name` 记忆
