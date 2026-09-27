# 第十篇实施记录：MCP 连接、发现与调用生命周期

日期：2026-09-27。对应 [历史审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/10-mcp.md) 的 M01–M08。本次在原有脏工作区上做局部修复，没有提交或回退其他改动。

## 实施结果

| 审核项 | 已实施 | 验证 |
|---|---|---|
| M01 配置与旧路由脱节 | 调用、连接、发现、资源枚举前检测配置；有效配置重载先更换 generation 并清空旧路由/目录；禁用、移除及当前工具过滤均在调用边界校验 | 禁用/移除/过滤/删除配置文件后旧工具不可调用，禁用资源不可访问；旧发现完成后不能发布 |
| M02 重复连接与后台任务失控 | 每服务共享连接任务；等待者 shield 共享任务；manager 跟踪预热/发现/重试；stop 取消并排空任务；旧 generation 不能安装 client 或发布目录 | 同服务两个调用只启动一次，取消其中一个不影响另一个；不同服务同时进入启动；关闭/重载期间取消仍完成旧 client 清理 |
| M03 发送阶段与取消清理 | 一个请求 deadline 覆盖 send 与等待；pending 在 finally 移除；通知发送也受时限约束；HTTP/transport/OSError 归一为 McpError | 发送阻塞超时、发送/等待阶段取消、HTTP 失败均清空 pending |
| M04 HTTP 等 EOF | 使用 httpx stream，按事件增量解析；收到本次请求的 result/error 即关闭响应并返回；支持 LF/CRLF/CR 及跨 chunk 分隔 | 模拟无限尾部流无需 EOF 即返回；验证 response 关闭；1 字节分块；超大 frame 拒绝 |
| M05 stdio 长行 | stdout 设置明确 64 MiB 消息上限；stderr 分块持续读取、保留有限尾部；进程 kill 后等待回收 | 真实本地 Python 子进程输出 70 KB JSON，同时写 100 KB stderr 长行，读取完成且尾部保留 |
| M06 分页 | tools/resources 共用分页收集；校验 page/cursor；拒绝重复游标；整体 deadline；100 页、10000 项上限 | 多页完整返回；坏页及重复游标失败，不把局部结果当完整目录 |
| M07 名称碰撞 | 冲突 qualified name 从路由及目录排除，记录歧义；发现、focus、重试合并采用同一注册规则 | 同服务名称清洗碰撞及 focus 路径验证；不再由后发现者覆盖 |
| M08 配置写丢失 | RLock 覆盖 store 公共增删改的整个 read-modify-write；保留原子 JSON 替换 | 同进程 16 个并发写入均保留 |

## 选择与边界

保留 McpManager 现有公共接口，没有在此轮建立新的通用生命周期框架。共享连接使用“每服务一个 task”，比只加全局锁更能保持不同服务并行；使用 generation 校验来拒绝旧结果，避免重载时由发现任务反向取消其祖先任务。关闭本身的清理单独 shield 并等待，所以一次调用方取消不会把旧资源留在半清理状态；不承诺在反复强制取消或进程被终止时仍完成清理。

请求超时与取消不代表远端工具已停止，更不自动重放可能有副作用的 tools/call。Streamable HTTP 此轮只覆盖 POST 响应流，不实现独立 GET 推送流、服务端 sampling 请求或会话 DELETE。legacy SSE 的协议能力未扩展。

64 MiB 是传输消息上限，非模型上下文预算；分页限额是保护策略，超过限额会明确失败，不静默截断。HTTP 入站队列上限 128，超限失败；这里尚未设计复杂的背压调度。

名称碰撞采用拒绝歧义，保持已有无冲突名称稳定；歧义记录直到配置重载才清除。**这只保证单个 manager 内部；跨基础配置/插件 provider 的组合层碰撞见第十一篇 P09，尚未修复。**

RLock 仅保护同进程通过 store 公共读改写 API 的操作；不解决多进程或外部编辑器同时写入，也不让调用方先读、稍后直接 save_document 的两个独立动作自动成为事务。配置检测仍依赖 mtime；人为保留相同 mtime、无效 JSON 暂时写入等情形没有改为新的文件监视协议，解析失败仍保留最后有效配置。

## 验证记录

新增 [29 项回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_mcp_audit_fixes.py)，并将 [旧 reload 测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/parity/phase_d/test_mcp_hooks_p1.py:59) 从“必须调用 stop_all”改为验证旧 client 关闭、池清空和新配置生效。这样可以验证行为而不固定内部调用关系。

最终相关集：**517 passed**，其中 MCP 文件集合含原有 77 项与新增 29 项。另两项 P0 parity 失败测试分别独立运行，均 **1 passed**。静态检查 `ruff --select F`、MCP compileall 和本次文件 `git diff --check` 通过。未运行全项目测试或真实 MCP 网络服务。

首次扩展运行：525 passed / 3 failed。一个失败来自本轮改变的内部 stop_all 调用断言，已更新并通过；另两个失败发生在 AppRuntime 创建时，原因是同组前序测试未关闭运行时、争用同一 Task 存储锁。检查该组测试可见缺少 shutdown；单独运行两项均通过。本次没有为使测试全绿而修改无关 Task 存储或 P0 测试组。

第九篇记录的旧上下文预算测试失败未纳入此相关集，未在本轮修复；这里没有宣称全量回归通过。

[机器可读验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/10-validation.json)。修复前的 mcp_probe.py 与结果保留为历史取证；它使用旧并发假设，不用作当前行为回归，应运行新的 pytest 测试。

## 后续审核

已完成 [第十一篇：插件、Skill 与 LSP](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/11-plugins-skills-lsp.md)，覆盖 19 个模块。该篇仅审核，包含 11 组问题、离线探针、逐模块建议与方案比较。

第十篇中未列为 M01–M08 的配置强类型校验、actions 的 HTTP transport hint 保存、execute 的异常内容块归一化等建议仍待后续实施；本轮不把整篇所有建议都标为已修复。
