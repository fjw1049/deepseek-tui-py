# 第四轮复审后的修复 · 2026-11-11

本轮按用户确认的范围处理 R4-1～R4-5，R4-6 仅补兼容性测试。没有改变此前保留的预算、产品权限或接口退役决策，也没有改写 Claude 的 `final-audit-2026-11-11.md`。

## 实际修改

| 项目 | 修复与边界 |
|---|---|
| R4-1 note 读取审批 | `NoteTool.approval_requirement_for_input` 按实际操作返回要求，read 为 AUTO，追加保留原策略。覆盖 agent/ask/plan 共用 agent registry 的情况；不仅修独立只读 registry。实际笔记可读、拒绝后的追加不落盘。 |
| R4-2 网络计数丢失 | 每次调用的审批回调移到 ToolContext 的独立可选字段，context 副本继续共享原 metadata，因此超时累计不丢失，也不把该次调用的回调留给其他调用。保留旧 metadata 回调入口的读取兼容。**标准运行时依然没有启用 NetworkPolicyDecider**；README、前次修复报告和复核报告已更正 D12 的适用范围。 |
| R4-3 旧待确认记录清理 | 自动清理明确跳过 sending/uncertain，不依赖当前渠道是否启用。超过 100 条也保留未解决的发送事实；人工确认后恢复普通清理规则。没有修改历史列表结构或增加新的归档 UI。 |
| R4-4 MCP 提前告警 | 只有对应服务成功发现工具后，才诊断名单中的缺失名字。发现失败、尚未发现、未验证的磁盘缓存暂不下结论；成功得到空目录则可以判断。支持普通服务、on_focus 服务和插件组合 manager。配置变更清除旧验证状态，后台发现重试成功更新状态。仍精确匹配，不自动修正或扩大授权。 |
| R4-5 file_search 部分结果 | 遍历预算耗尽后，工具返回已经找到的文件/目录，附 Search incomplete 和 incomplete/truncated 元数据，count_is_exact=false。正常完成、输出数量截断、参数错误及目录授权保留原语义；私有扫描函数旧调用者不传 partial-results 容器时仍抛出原异常。 |
| R4-6 连续用户消息 | 不添加伪造的 assistant 回复。新增测试验证取消前的请求与下一次请求都保留：Anthropic 构造器合并同角色消息，Chat Completions 和 Responses 构造器保留两个 user 项。这里只验证本地协议构造，没有把它宣称为所有供应商的线上验收。 |

## 复现与验证

使用项目 `.venv` 的真实依赖，没有占位库，没有付费模型调用，也没有向真实外部收件人发送消息。

- 修复前新增用例得到 **12 failed / 2 passed**，覆盖 note 审批、关闭渠道后的记录丢失、文件搜索预算和 MCP 提前告警。
- HTTP 用例随后区分了 registry 外层总超时与 fetch 内部读超时：通过测试覆盖的 fetch 默认超时驱动真实 socket 超时，避免外层先取消导致测错分支。最终连续两次请求累计为 2，第二次出现换来源提示，审批仅请求一次。
- 修复后的新增测试 **18 passed**：临时笔记文件、每组 101 条真实磁盘运行记录、真实 localhost HTTP、真实 stdio MCP，以及三类协议构造器。
- 相关审批、MCP、自动化、搜索和网络升级回归 **147 passed**。
- 新增测试 Ruff 与本轮修改文件的未定义/未使用符号检查通过；最终差异空白检查见下方。

| 最终验证 | 结果 |
|---|---|
| Python 全量（排除 live/live_mcp 标记） | **4,312 passed / 175 skipped / 36 deselected，零 warnings，205.20 秒**。包含本地真实 IO e2e。 |
| 前端全量 | **319 files / 2,091 tests passed，25.94 秒**。仍有已有 Node localstorage 路径提示，没有抑制警告。 |
| 新增用例 Ruff / 本轮生产文件 F 类检查 | 通过。 |
| `git diff --check` | 通过。 |

日志：`/tmp/r4-before.log`（修复前）、`/tmp/r4-targeted.log`（147 项）、`/tmp/r4-final-targeted.log`（18 项）、`/tmp/r4-python-full.log`、`/tmp/r4-ui-full.log`。没有更改前端源码，本轮未重新构建安装包或重复宣称原生 CUA/第三方渠道验收通过。

可复跑：

```sh
.venv/bin/python -m pytest -q tests/test_round4_review_fixes.py
.venv/bin/python -m pytest -q -m 'not live and not live_mcp'
cd packages/workbench
npm test
```

真实 HTTP 测试只对自己的 loopback 接收端放开 fetch 的地址检查；生产地址策略未改。MCP 的发现失败/空目录边界采用可控响应，实际 on_focus 发现另有真实进程测试。

## 仍保留的边界

- 可选网络策略未接入正式应用配置，本轮未增加启用开关。
- unresolved 记录可能令总数超过 100，这是保留待确认事实的有意行为；人工确认后才恢复清理。
- 尚未发现的 MCP 工具无法立即验证名单。对无法定位服务的完整工具名，保守等待已启用服务发现完成，不猜测工具归属。
- 本次没有新增前端功能、批量清理历史凭据或执行跨平台、CUA 应用、真实外部消息渠道验收。
- shell 预期退出码、轮询成本、soft-resume 预算等双方同意暂缓的事项继续保留。
