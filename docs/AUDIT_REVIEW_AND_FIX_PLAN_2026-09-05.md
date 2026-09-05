# 历史审核复核与修复方案

日期：2026-09-05。复核基线：当前工作区，HEAD `90d639cc663ef8c09d063649695a5624e5eca70e`。

本轮只审核并制定方案，不修改业务代码。输入为 `audit-report.md`、`SECURITY_FIX_PLAN_2026-08-14.md`、`SECURITY_FIX_BEHAVIOR_CHANGES_2026-08-16.md`。以下行号均指复核时的当前代码，不沿用旧报告行号。

## 1. 结论与修复顺序

**旧报告不能直接作为当前待修清单。它混合了真实缺陷、已经修复的缺陷、产品行为，以及只看局部代码得到的过强结论。** 当前最值得优先投入的是：

1. **项目配置的信任边界尚未闭合。** 已有安全键过滤，但遗漏 LSP 执行配置；cwd 配置文件通过指向目录外的软链接，可以被重新判成可信配置。需先修这条，不能把“已加黑名单”当成彻底解决。
2. **后台任务的权限和工作目录没有全链路绑定当前会话。** 显式 workspace 已校验；省略 workspace 却回落到共享管理器目录。resume 保留旧权限并绕过创建分支约束。执行器还会重新加载全局配置。
3. **Shell 分级和审批指纹仍有真实缺陷。** 单个 `&`、进程替换、只读命令的写入选项没有可靠处理；指纹把大小写和引号内空格折叠，导致不同命令共享授权。
4. **MCP SSE endpoint 跨域问题仍未修。** 可以将带用户 headers 的 POST 指向别的 origin，包括 `//other-host/path`。
5. **审批与取消的生命周期需要修。** 普通审批无超时；相同 tool_call_id 覆盖 pending future；后台取消只设置事件，阻塞中的工具/审批不一定及时退出。飞书“超时后结束审批”的发布说明不符合代码。
6. **子代理 send_input 的功能缺陷仍存在。** 只在循环前取队列；运行中输入不消费，interrupt 参数被丢弃。

先完成这些闭环，再做配对保留、重试一致性、事件重放和持久化效率。**不建议先拆几千行 manager，也不建议把 shlex 当成完整 Shell 语法树。**

严重性按实际前提评估：本项目是带本地工具能力的单用户应用。用户明确选择完整访问、明确授信的本地扩展，和恶意仓库在未授权时抬权，不能归为同一类。

## 2. 证据与验证边界

- 阅读三份输入中的全部具体条目，并追踪当前对应实现及主要调用方。
- 两组定向现有测试：**184 passed / 1 skipped**，以及 **68 passed**，合计 **252 passed / 1 skipped**。覆盖配置隔离、环境清洗、命令分级、敏感文件、请求参数过滤、HTTP 认证/审批、任务审批桥、恢复、引擎隔离、消息配对、Shell 写入保护和流中重采样。
- 第一组唯一跳过项为 fetch_url 的 AnySearch 实网用例（该用例在缺凭据或网络不可用时跳过）；不把跳过当成通过，也不据此宣称所有平台实际子进程行为均验证通过。
- 在临时目录用假密钥、假 URL、内存对象及函数级故障注入进行额外验证。危险命令只送入分析函数，未执行；MCP 跨域验证未发送网络请求。
- 没有用真实模型接口、真实密钥、飞书/邮件投递或公网漏洞利用来验证。Linux 和终端控制序列的端到端影响没有实机确认。
- “已修”仅指旧条目描述的具体缺陷已被当前实现阻断，不表示整个模块不存在其他缺陷。
- 原报告“19 条高危”实际列了 **20 条**；“38 条中危”正文拆开列出的具体项为 **30 条**；“约 25 条低危”没有完整明细。下文覆盖能对应到具体描述的条目，不把未给出的条目虚构出来。

### 最小验证结果

| 验证 | 当前实际结果 | 说明 |
|---|---|---|
| cwd `deepseek-tui.toml` 软链接指向同一临时根目录下、repo 外的 TOML | `_is_project_level=False`，最终 `approval_policy=auto` | **信任源被路径解析改变**；需目录外目标存在且含相关设置，并非任意普通 clone 必然中招 |
| 项目配置含 `lsp.enabled=true`、自定义 `lsp.servers.python` | 过滤后完整保留 | LSP 随后按该 argv 启进程；触发是诊断/LSP 启动，不是仅加载配置就执行 |
| `echo ok & touch /tmp/example`、`cat <(touch /tmp/example)` | 两条都判 SAFE | 仅分析字符串，未执行 |
| `sort -o /tmp/example input`、`git diff --output=/tmp/example` | 两条都判 SAFE | 白名单命令不等于所有选项都只读 |
| `env ls`、`/bin/ls`、`"ls"`、`A=1 ls` | 都判需要审批 | 旧 C1 的这些例子是保守误判，不能拿来证明越权放行 |
| `mv src/a.py /tmp/` / `cp src/a.py /tmp/` | 前者拒绝，后者允许 | mv 删除源的问题已修；cp 读取源不等于删除源 |
| 紧贴重定向、`os.remove`、`dd of=`、`scratch/../src/a.py` | source-write guard 允许 | 护栏不完整；其他审批层仍可能要求批准，不能省略这个前提 |
| `sys.stdout.write("ok")` | source-write guard 拒绝 | 已确认误杀 |
| `git branch -d demo` 与 `git branch -D demo` | 审批指纹相同 | 非强制删分支与强制删除共享记住授权；仅比较指纹，未执行 Git |
| `printf "A  B"` 与 `printf "a b"` | 审批指纹相同 | 引号内空格及大小写被折叠 |
| task_create 省略 workspace，当前 session 目录与 manager 默认目录不同 | task 落在 manager 目录 | 已确认目录继承错误 |
| 非 auto 会话 resume 一个旧 auto 任务 | 原 auto=True、原 workspace 都保留 | 已确认恢复入口未重新约束权限；工具自身仍有一次审批 |
| 对历史 tool_use 单独 pin | call 保留、result 被摘要集合选中 | 保留算法未做配对闭包；客户端会剔除孤立调用，不能再断言必然 API 400 |
| 直接消费 LLMClient 流，首轮 delta 后 ReadError | 两次请求、重复 delta | 底层重试仍存在；当前 TurnLoop 在错误处 break 并清空重采样，主路径已有保护 |
| SSE endpoint 设置为 `//other.example/post` | 接受为 `https://other.example/post` | 同 origin 约束缺失 |
| 同一个审批 ID register 两次后 resolve | 第一 future 未结束，第二 future 得到批准 | ID 碰撞确实存在；不是“看到 ID 就能越过 bearer 认证” |
| 两个 agent 的 metadata 成本各上报一次 | fallback ledger 仅写 1 条 | helper 算法有问题；当前源码无这些 metadata 字段的生产方，不能宣称主计费必然少计 |
| 在文件 stale 检查后、写入前注入另一写者 | 工具返回成功、另一写者内容被覆盖 | 验证检查窗口存在；未模拟全部 OS 并发竞态 |
| 既有 0644 用户配置写入假 API key | 写后仍为 0644 | 旧后端虽然删除，凭据配置权限仍有残留 |
| tool_result 放在 USER 消息内，经 OpenAI 消息投影 | 整组不合法调用被丢弃，结果为空 | 旧“此例必然 API 400”不成立；静默丢上下文仍需处理 |

## 3. audit-report.md：全部高危条目复核

“仍在”表示缺陷代码仍存在；“部分”表示旧链已被部分阻断或真实影响需要改写；“不成立”仅针对原描述的结论。

| ID | 判定 | 当前证据、前提与建议 |
|---|---|---|
| A1 Shell 继承所有环境 | **原点已修，整体隔离不足** | [src/deepseek_tui/tools/shell.py:1331](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:1331) 和 PTY 路径调用 build_child_env。[src/deepseek_tui/policy/env_filter.py:23](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/env_filter.py:23) 是名称后缀黑名单；DATABASE_URL、裸 PASSWORD、代理/agent socket 等不构成可靠隔离。保留现有修复，后续以必要变量+可信显式注入替代“所有不匹配名字都继承”。参见方案 R1/R4。 |
| A2 MCP stdio 继承所有环境 | **原点已修** | [src/deepseek_tui/mcp/transport.py:138](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py:138) 已清洗，显式 env 重新加入。显式配置注入是功能，不是自动泄露；需保证配置来源可信。MCP 本身未被此函数 OS 沙箱化，不应宣传成不可信代码隔离。 |
| A3 printenv/set/find 白名单 | **已修** | [src/deepseek_tui/policy/command_safety.py:87](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/command_safety.py:87) 已移除三者；当前连普通 find 也需要审批。不要再重复移除。其他 SAFE 命令选项仍有缺口，见 C2。 |
| A4 旧凭据链+项目 api_key | **主要已修，权限残留** | `src/deepseek_tui/state/secrets.py` 已统一 env→provider config→活动 provider 顶层 key。项目 api_key 被过滤。已有 config 0644 写 key 后仍保持 0644，见 R4。“删旧后端”无需再做。 |
| B1 自动项目配置加载 | **部分，高优先级** | [src/deepseek_tui/config/loader.py:137](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:137) 已过滤安全键，但 `:275` 使用 resolve 后位置判信任，目录外软链接可逃逸；LSP 字段遗漏。修配置来源分类及执行字段过滤，不删除普通项目配置。R1。 |
| B2 项目 hooks 启动 RCE | **原 hooks 配置入口已修** | [src/deepseek_tui/config/loader.py:99](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:99) 阻止项目 hooks；用户 hooks 保留 shell 是合理功能。不能继续描述为普通仓库声明 hook 就能执行。新的 LSP/软链接入口归 B1。 |
| B3 项目改 approval/sandbox/base_url | **普通 TOML/.env 已修，边界未闭合** | loader 已过滤顶层、providers、profiles、加载位置指针；`.env` 不再修改全局环境。软链接仍可让过滤完全不运行；`features.exec_policy` 也未列入项目敏感项，可关闭可选执行策略。R1。 |
| C1 split 首词可绕过 | **表述不准确，解析问题仍在** | [src/deepseek_tui/policy/command_safety.py:219](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/command_safety.py:219) 仍 split。但原举例全部进入 unknown→审批，属于误判而非放行。别只改 basename 或 strip quotes 后直接白名单，会扩大风险。R3。 |
| C2 管道/重定向遗漏 | **部分，仍需修** | 管道已逐段取最坏结果，原 `cat a \| dd ...` 不再 SAFE。单个 &、进程替换和 SAFE 命令写选项仍可误判；`<` 本身不是执行漏洞，要区分输入重定向与进程替换。R3。 |
| C3 mv/cp 不检查源 | **mv 原点已修；cp 不应同等处理** | [src/deepseek_tui/workspace/shell_write_guard.py:546](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_write_guard.py:546) 已检查 mv 源。cp 不删除源，无须仅因源是代码文件就禁用；读敏感文件另走读策略。source guard 的其他绕过见中危 M04/M05。 |
| D1 压缩 pin 孤立 tool_call→400 | **部分，影响应降级重述** | [src/deepseek_tui/engine/capacity.py:335](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py:335) 未闭包 pin，确实可分裂。[src/deepseek_tui/client/normalize.py:20](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/normalize.py:20) 和两个协议出口已清理孤立块，典型 400 被防住；仍损失历史工具语义。做保留集闭包，保留出口兜底。R7。 |
| D2 gather 一个异常丢整批 | **当前普通异常场景不成立** | [src/deepseek_tui/engine/orchestrator/tooling.py:522](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:522) 每个 wrapper 已捕获 Exception 并返回错误结果。不是一行 return_exceptions 修复；CancelledError 应继续传播取消，不能当普通失败吞掉。现有结构保留。 |
| D3 多 thread 共引擎覆盖 sink | **原共享前提已修** | [src/deepseek_tui/engine/orchestrator/core.py:1183](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1183) 复制每引擎 ToolContext 并独立 subagent manager；[src/deepseek_tui/server/threads/manager.py:4166](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:4166) 每线程创建 Engine。仍应补“同一线程跨 turn 的迟到子代理 mutation”回归，但本轮未证明新错记，不能据此强行拆 manager。 |
| E1 任意 registry URL SSRF；空 webhook secret | **两项应拆开：registry 部分、webhook 已修** | [src/deepseek_tui/integrations/skills.py:1035](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/skills.py:1035) 已限定 GitHub 域名，普通内网 URL 被拒；`:1040` 自动跟随重定向且允许 http，缺最终/逐跳校验。是否能利用需受允许域的可用重定向入口配合，未实网验证。[src/deepseek_tui/server/routes.py:278](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/routes.py:278) 空 secret 已返回 401。R5。 |
| E2 HTTP 外部 MCP 跳审批 | **已修** | [src/deepseek_tui/server/runtime.py:470](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/runtime.py:470) 与引擎共用 approval_request_for_mcp，无审批通道时拒绝；内置工具也有对应 gate。auto 模式按用户权限执行不是这个漏洞。 |
| E3 非 loopback + insecure | **CLI 入口已修** | [src/deepseek_tui/cli/app.py:312](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:312) 拒绝组合。默认 bearer 路径也已接入；嵌入式调用者主动 insecure 是另一信任场景，不能说所有启动方式都由 CLI 保证。 |
| F1 流中重发导致重复 | **主路径已有缓解，底层仍有问题** | [src/deepseek_tui/client/base.py:159](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/base.py:159) 仍 yield error 后重试；但唯一源码消费方 [src/deepseek_tui/engine/turn.py:492](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/turn.py:492) 在该点 break、丢弃 partial 并重采样，典型持久化重复已防住。已展示 delta 可能留在屏幕，重试也有费用。统一重试责任、增加 attempt/reset 事件。R8。 |
| F2 Anthropic 429/5xx 不重试 | **仍在，一致性/可用性问题** | [src/deepseek_tui/client/anthropic.py:80](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/anthropic.py:80) 直接抛 HTTPStatusError，base 不处理该类型。高层泛型恢复不等价于明确的状态码重试。做共享 pre-stream 策略，不重试认证和参数错误。R8。 |
| F3 send_input 不消费/interrupt 丢弃 | **仍在** | [src/deepseek_tui/tools/subagent/loop.py:471](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:471) 仅循环前排空；主循环 `:641` 不读取；[src/deepseek_tui/tools/subagent/manager.py:267](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:267) 只 enqueue。应把“取消当前采样并继续”和“永久停止代理”区分开，不能简单 set 总 cancel_token 后结束代理。R6。 |
| F4 detached 默认 auto_approve | **部分，不能笼统指主路径** | [src/deepseek_tui/tools/subagent/manager.py:571](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:571) 无父 handler 默认仍 True；正常 Engine 创建会传父 handler 和实际 flag，子代理优先查 live flag。将无父桥默认设拒绝/只读；明确自动化才显式授权。与 task 权限链一起修。R2。 |

## 4. audit-report.md：全部具体中危条目复核

为原报告未编号条目依出现顺序编 M01–M30；重复项明确交叉引用。

| ID | 原问题 | 判定、证据与最小修复 |
|---|---|---|
| M01 | read_file 无字节上限 | **已修。** [src/deepseek_tui/tools/file.py:94](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/file.py:94) 使用分页读取，`:428` 起分块读并限制预算；无需再做整套大文件读取重构。 |
| M02 | stale 检查到原子写之间竞态 | **仍在。** [src/deepseek_tui/tools/file.py:189](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/file.py:189) 到 `:203` 有 await 窗口。原子 rename 只防半文件，不防丢另一写者更新。按文件路径串行化内部写、提交前版本检查、明确无法保证外部进程严格 CAS。R9。 |
| M03 | 写侧不挡敏感文件 | **原点已修。** write/edit 调用 is_sensitive_write_path，包含凭据及 hooks。Shell 不共享这个保证，勿混称所有写入口都安全。 |
| M04 | 解释器删除、git restore、dd；stdout 误杀 | **部分仍在。** [src/deepseek_tui/workspace/shell_write_guard.py:96](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_write_guard.py:96) 漏 os.remove 等、误杀 stdout 已验证。managed worktree 另有 Git 检查，不能再说 git restore 所有场景都放行。别靠补所有 API 名字构建安全隔离。R3/R4。 |
| M05 | 重定向紧贴/引号路径 | **仍在。** [src/deepseek_tui/workspace/shell_write_guard.py:80](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_write_guard.py:80) 要求左侧分隔，`echo hi>src/a.py` 漏过；引号内空格解析也不可靠。与命令分级共用保守解析。R3。 |
| M06 | 多行/替换拦截依赖策略文件 | **仍在，但应改写保证。** [src/deepseek_tui/tools/shell.py:945](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:945) 无 policy 直接返回，[src/deepseek_tui/policy/exec_policy.py:427](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/exec_policy.py:427) 明确允许不存在文件。引擎工具审批仍在，非“无人批准即可执行一切”。内建语法风险检查始终生效，可选文件只增量约束。R3。 |
| M07 | 子代理成本少计/重计 | **fallback helper 有缺陷；主路径影响未证实。** [src/deepseek_tui/engine/orchestrator/core.py:1456](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1456) 用任何 subagent/tool 账目做全局去重，两个 metadata 上报只记一条。当前 src 未找到 child_input_tokens 等字段生产方，不能把 helper 实验冒充真实收费复现。用 request/run 身份计量、累计值做增量，不仅按 agent_id 去重。R10。 |
| M08 | 压缩偏晚，没输出预留 | **旧判断不再全面成立。** [src/deepseek_tui/engine/turn.py:287](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/turn.py:287) 请求前已有输出预留和全 payload 预算检查；context_pressure 也包含静态前缀和实测校正。75% rewrite 是策略阈值，不等同安全上限。保留预算边界用例，不仅因 capacity 函数没参数就报 bug。 |
| M09 | 中文不触发 plan 快速通道 | **仍在，低优先级。** [src/deepseek_tui/engine/dispatch.py:100](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/dispatch.py:100) 只有英语关键字。中文仍能正常使用 plan 模式；缺的是确定性 fast-path。优先显式模式/意图参数，确需启发式则补中文及否定请求测试。 |
| M10 | Engine.create await handler 卡死 | **有条件，未证明内置实现会卡。** [src/deepseek_tui/engine/orchestrator/core.py:1332](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1332) 会 await auto_approve_enabled；这不是 request_approval，标准 handler 通常立即读状态。自定义 callback 可以挂起。定义此接口为本地快照或加构造超时；不列致命。 |
| M11 | 审批 future 无超时 | **仍在。** [src/deepseek_tui/server/approval.py:172](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/approval.py:172) 直接 await fut，普通审批缺过期清理；elevation 已有另一处 600 秒等待，不能混淆。R6。 |
| M12 | ID 在事件流可被伪造批准 | **原认证推论不成立，但碰撞真实。** bearer 保护 API；已获得同一用户 token 的客户端本来就有权限。真正问题是 [src/deepseek_tui/server/approval.py:46](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/approval.py:46) 相同 ID 覆盖 future。服务器生成唯一 approval_id 并绑定 thread/turn/tool，不能只换随机字符串而不改事件关联。R6。 |
| M13 | rewind 不清事件日志 | **日志与当前状态确实未统一。** [src/deepseek_tui/server/threads/manager.py:3175](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3175) 删实体，`:3211` 发 rewound；[src/deepseek_tui/server/threads/store.py:375](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py:375) 仍重放旧事件。不能直接删除审计历史，否则破坏 seq/重连；增加历史 revision/tombstone 或 snapshot/reset 协议。未做 UI 完整重连复现。R9。 |
| M14 | 冷线程无法中断 | **原描述不足以认定 bug。** [src/deepseek_tui/server/threads/manager.py:3823](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3823) 拒绝未加载线程；正常活动 turn 对应已加载 engine，重启另有恢复。需要“磁盘 running、内存无执行者”的具体场景才谈修复，不能为中断冷线程启动一个新 engine。 |
| M15 | rewind 全局锁内磁盘 I/O | **仍在。** [src/deepseek_tui/server/threads/manager.py:3127](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3127) 同时持 _active_lock 做 restore 和实体持久化。保留同线程操作锁，缩短全局锁到占位/提交；不能只把 I/O 挪出去引入 start_turn 竞态。R9。 |
| M16 | pending_user_inputs 跨 turn 泄漏 | **metadata 残留存在；旧问题再次生效未证实。** [src/deepseek_tui/server/threads/manager.py:5892](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:5892) 加 metadata，主要在成功 submit 才 pop；列表依实际 handle future 过滤。结束/取消/卸载时统一清理，测试陈旧回答不能影响新 turn。R6。 |
| M17 | 队列无上限+全量落盘 | **仍在，进度路径已有优化。** [src/deepseek_tui/tools/task/manager.py:168](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py:168) 无队列上限，`:679` 结构变更全量写；单任务进度已局部写。只改受影响任务及队列，批量入队合并、设置容量/拒绝策略。R10。 |
| M18 | resume 重放副作用 | **风险真实，原位置/机制不准确。** store 主要序列化；[src/deepseek_tui/engine/dispatch.py:793](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/dispatch.py:793) 从完整 round checkpoint 继续，不直接逐条重放。副作用成功、round 未持久化即崩溃时，模型可能重复执行。先标记 uncertain、要求核实再继续；支持外部 idempotency key 的工具再接入，不能承诺通用 exactly-once。R9。 |
| M19 | RUNNING 取消不能杀阻塞进程 | **仍有缺口。** manager 只 set token，task executor [src/deepseek_tui/engine/dispatch.py:852](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/dispatch.py:852) 只转发 cancel_event；run_single_turn 没有 engine.run 的 CancelRequestOp 处理循环。Shell 收到硬取消时已有 killpg，但当前桥不保证送到。竞争等待 cancel 与 turn_task，取消后 await 清理；测试实际父子进程消失。R6。 |
| M20 | 父 completion 通知静默丢失 | **仍在，但有 mailbox/状态补偿渠道。** [src/deepseek_tui/tools/subagent/manager.py:392](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:392) except pass。加结构化日志、按 completion ID 幂等的有限重投；不能把“回调异常”直接等同整份结果丢失。R10。 |
| M21 | 终态驱逐不删磁盘 | **行为存在，是保留策略缺失。** [src/deepseek_tui/tools/task/manager.py:668](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py:668) 只逐出内存。持久任务本来需要历史，不能随内存驱逐就删磁盘。单独设保留期/容量与显式清理，保留可 resume/未投递记录。R10。 |
| M22 | 旧 secrets 文件/参数泄露 | **旧实现已删除。** 不应再次排“删旧后端”；现存 config 文件权限残留见 A4/R4。 |
| M23 | 429 不读 Retry-After | **仍在。** [src/deepseek_tui/client/deepseek.py:196](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/deepseek.py:196) 固定 1/2/4 秒退避，不解析 header。统一有上限、可取消的退避，并处理秒数/HTTP 日期、抖动。R8。 |
| M24 | 非 TOOL result 静默丢弃→400 | **400 结论在给定例子不成立，静默丢失仍在。** [src/deepseek_tui/client/chat_messages.py:66](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/chat_messages.py:66) 按 role 投影，最终 orphan strip 会删除相应 call。共享 normalize 只比较 ID 集，不校验 role、顺序、重复。入口结构校验+协议出口完整校验。R7。 |
| M25 | SSE endpoint 跨域泄凭据 | **仍在。** 与方案 C4、R5 同一问题，不重复计数。 |
| M26 | 所有 MCP transport 必须 HTTPS/防 SSRF | **需按信任来源裁定。** 明确配置的本机/内网 MCP 是合法功能，不应像模型 fetch_url 一样全部禁掉。用户授信目的地可放行；远程凭据默认 HTTPS，跨 origin 重新授权；仓库/模型不能随意提供新端点。R5。 |
| M27 | npm 不验 integrity | **仍在。** [src/deepseek_tui/plugins/fetch.py:181](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/fetch.py:181) 校验 https 和 host、取包后算 digest，但未与 registry 的 dist.integrity 比对。下载 digest 不是验证下载内容符合发布元数据。提取前做 SRI 校验并限制重定向/响应体。R5。 |
| M28 | trusted=true 自动补 grant | **仍在，限 user/claude scope。** [src/deepseek_tui/integrations/plugins.py:1212](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py:1212) 非 project 且无 grant 自动授予当前 digest。项目范围已防，但“不存在旁路”的原好评不实。移成明确一次性迁移，普通加载缺 grant 不补；撤销 grant 不应下次又生成。R4。 |
| M29 | insecure 公网监听 | **与 E3 重复，CLI 已修。** 不重复排期。 |
| M30 | sanitize 只去哨兵 | **事实成立，终端漏洞尚未证明。** [src/deepseek_tui/tui/sanitize.py:16](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/sanitize.py:16) 的 API 就叫 strip_subagent_sentinels，文件名不足以证明承诺。需测试真实 Rich/Textual 输出是否可到达 OSC/CSI；在最终展示边界过滤，保留换行/制表和正常格式，不先污染模型原文。R10。 |

## 5. SECURITY_FIX_PLAN：21 项逐条对照

此处 A/B/C 编号属于安全方案，**不与上一份报告的同名编号混用**。

| 原 ID | 当前裁定 | 对原建议的修正 |
|---|---|---|
| A1 工作区配置提权 | **部分修复，仍应最高优先级** | 不再全盘重做；修信任来源软链接、LSP、features.exec_policy 等遗漏。no_project_config 当前也未完整跳过 cwd 候选和 .env，应明确开关语义并补测试。见 R1。 |
| A2 auto 与沙箱解耦 | **当前是明确的产品行为，不作为默认必修 bug** | [src/deepseek_tui/tools/runtime.py:313](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py:313)、Workbench 中英文说明与设置归一化都把 auto 定义为完整访问。可以设计“自动批准但限制工作区”的新组合；必须同步设置、旧配置迁移与各执行器，不能只改一处 trust 推导。项目不能替用户选择该档位仍是必须修。 |
| A3 task_create 提权 | **原 schema/显式目录修了，整条链未修完** | `_resolve_workspace(None)` 回落到 manager、resume 不重新校验、执行时重载配置，均应纳入。禁止仅凭工具声明“继承当前会话”就宣布完成。R2。 |
| A4 项目 hooks | **普通配置入口已修** | 保留可信用户 hooks 的 shell 执行；补配置来源绕过，不重写 hook 方言。插件自动补 grant 单独处理。 |
| A5 extra_body/headers 劫持 | **列出的保护已实现** | 两种客户端都调用 sanitize，保留 model/messages/tools/tool_choice/stream/system；headers 大小写不敏感地挡 Authorization/x-api-key/Cookie。用户端扩展参数的合法性保留厂商兼容测试即可，不继续扩大为禁止所有扩展。 |
| A6 写敏感路径 | **原文件工具入口已修** | 保留当前规则。是否允许用户明确修改 .env 是额外产品能力，不能通过放开所有敏感写来实现。config 权限及 Shell 读取另列。 |
| B1 Linux 无 OS 沙箱 | **仍在** | warning 已跨平台打印，但仍 fallback unsandboxed；doctor 没展示实际 sandbox 可用性。正则路径检查不能等价替代 OS 沙箱。受限模式发现无隔离，默认拒绝受限 Shell，或让用户明确选择一次/会话非沙箱运行并准确展示。无需本轮自研 Linux 沙箱。R4。 |
| B2 Seatbelt 全盘读 | **仍在，是范围过宽** | 默认网络与全盘读组合有泄露风险；命令文本敏感 basename 拦截只能辅助，不能当最终保障。设计必要系统/工具链读根和敏感目录 deny，先实测常用工具兼容。出网权限独立处理，审批过一次命令不等于授予所有后续联网。R4。 |
| B3 入站 secret/test-send | **鉴权和目标限制已修，生命周期未完成** | 空 secret 401、测试目标取配置都成立；“默认只读”只表示审批不自动放行，不代表限定只读工具集；无人处理审批会挂起。R6。 |
| C1 指纹丢 flag | **原缺 flag 已修，新碰撞仍在** | 现保留 flag，但统一 lower/split 仍碰撞。最简单安全方案是 hash 原始命令，宁可多问，不做有损归一化；纳入 cwd/执行上下文。R3。 |
| C2 cron 固定指纹 | **原点已修，覆盖还不完整** | [src/deepseek_tui/tools/approval.py:291](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/approval.py:291) 已包含 name/schedule/prompt/delivery。当前工具还能指定 cwds、timezone、run_now 等，建议对所有会改变执行效果的规范化参数做稳定摘要，不能只加任务名。R3。 |
| C3 fetch_url 私网 | **字面地址和逐跳已修，DNS 残留真实** | 当前先解析判断、连接再解析，存在 DNS rebinding 窗口，DNS 失败也返回未阻断。连接层固定已验证 IP，保留 Host/SNI 与证书校验；代理路径同样定义策略。无需声称已有可复现远程利用。R5。 |
| C4 SSE endpoint | **未修** | 同时覆盖绝对 URL、相对 URL 和 `//host`；比较 scheme/规范化 host/有效 port，禁止用户信息。拒绝跨域而不转发 headers。R5。 |
| C5 MCP 环境 | **原点已修** | 发布说明基本属实，但后缀清洗不是完整秘密隔离。LSP 进程仍继承环境，需一并补。R4。 |
| C6 cron 投递目标 | **已修列出的模型入口** | [src/deepseek_tui/tools/automation.py:176](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:176) 默认收件人解析与陌生目标拒绝已经实现。内部 API 的可信调用与模型工具不同，不要直接混用禁止任意目标的规则。 |
| C7 摘要伪造同意 | **已缓解，不能靠提示保证权限** | [src/deepseek_tui/engine/context_pressure.py:35](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context_pressure.py:35) 已说明摘要不是证据，消息 provenance 和原文请求也已有实现。归档 [src/deepseek_tui/engine/cycle.py:235](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py:235) 仍存消息，不做通用敏感内容过滤。审批事实只能来自服务端授权记录，摘要不能生成或恢复 grant；归档分级保存/脱敏。R7/R10。 |
| C8 _has_api_key 不一致 | **已修** | [src/deepseek_tui/tools/runtime.py:372](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py:372) 走 SecretsManager.resolve_api_key，缺凭据会 warning。不要再写第二份 provider/env 查找表。 |
| C9 untrusted 更松 | **行为有意且 UI 已说明** | Workbench “仅敏感操作审批”，明确常规写自动通过。内部枚举名易误导，但现在直接改变行为会破坏产品约定。保持 UI 说明，若改名用兼容别名和迁移，不列提权漏洞。 |
| C10 命令首词/Starlark 未接线 | **前半仍有缺口；后半已过时** | 当前 find 已非 SAFE，命令选项解析仍需 R3。当前执行策略为 TOML 的 TomlBackedPolicy，未见旧 PolicyParser 实现；核对仍在宣传的旧文档，不能为了旧报告重新引入 Starlark。 |
| C11 旧凭据后端 | **已删除，另有 config 权限残留** | 对用户配置写 key 应确保新内容发布前即 0600，不沿用既有 0644。单独安全写函数，别让所有原子写文件都强制 0600。R4。 |
| C12 每次工具携带完整历史 | **仍在，但非等价于对外泄露** | [src/deepseek_tui/engine/orchestrator/tooling.py:630](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:630) 每次完整 dump 到共享 metadata；MCP 请求实际传 arguments，并未自动将 metadata 传给外部 server。本质是额外成本、共享状态和最小数据访问问题。仅实际 fork_context 时惰性生成一次不可变快照，限定生命周期。R10。 |

## 6. BEHAVIOR_CHANGES：发布说明真实性

| 文档承诺 | 当前情况 |
|---|---|
| Shell/MCP 过滤列出的密钥变量 | **基本准确。** 代码还补了 `_KEY`、`APIKEY`；应说明只是名字规则，不保证所有密钥都不可访问，LSP 尚未接同一过滤。 |
| printenv/set 移出、find 危险动作升档、管道按最坏段 | **基本准确但不完整。** 现在普通 find 也不免批；管道分割不是完整 Shell 解析，SAFE 命令的危险选项仍漏。 |
| 飞书 inbound 默认只读，等审批超时即可 | **需要改文档并修实现。** auto_approve=False 属实，但保留可写工具并等待审批不等于只读。300 秒是等待结果的轮询截止，不会取消审批/turn；不能承诺“挂起到超时就结束”。 |
| 项目配置不能覆盖安全键 | **普通文件成立，完整保证不成立。** 软链接可绕过滤，LSP/可选策略开关遗漏。 |
| task_create 继承当前档位和当前工作区 | **显式新建路径大体成立，省略目录和恢复路径不成立。** 执行器重载全局配置也需校准。 |
| fetch_url 私网与重定向检查 | **成立但有已注明 DNS 窗口。** 不应该把已注明局限删掉。 |
| 文件写工具拒绝敏感路径 | **成立。** 不代表 Shell、外部工具的文件访问也受相同限制。 |
| serve --insecure 只回环；legacy bearer | **已实现对应入口。** 可程序化主动关闭认证，声明应限定默认/CLI 行为。 |
| session 指纹保留 flag 和 cron 内容 | **原改动存在，但不足以保证身份唯一。** 大小写/空白碰撞和 cron 参数遗漏仍需修。 |
| 主路径 auto 仍全信任、DNS 已知残留 | **准确。** 不应把这两项当本轮才发现的新 bug；auto 已在当前 UI 文案说明。 |

## 7. 可执行的修复批次

以下是方案，不是已实施的变更。优先级：P0=先堵未授权的配置执行入口；P1=权限/正确性闭环；P2=稳定性和性能。每个批次先补能触发真实调用链的回归，再做最小代码修改。

### R1 / P0：项目配置来源与执行配置隔离

**改动边界**：config/loader.py、相关 config models 校验、必要的 LSP/runtime 入口；不重构整个配置系统。

- 从“如何发现此配置”决定信任：cwd 候选、workspace overlay 永远属于项目来源。resolve 只用于检查实际访问路径，不能让来源从 untrusted 升为 trusted。用户显式指定配置的信任规则单独定义，不能隐式混在 cwd 路径判断里。
- 项目禁止提供 LSP server argv；允许项目选择语言/诊断偏好时，也只能引用用户事先注册的可信 server。项目不得关闭 `features.exec_policy`。复核所有可执行字段/加载指针，避免把每个新字段默认当安全字段。
- `no_project_config` 真正跳过所有自动项目来源，包括 cwd 候选、workspace TOML、workspace .env。显式命令行配置按文档规则处理。
- 保留已完成的 provider/hook/profile 安全键过滤，避免重复改功能。

**验收**：普通/相对路径/软链接 cwd 配置均不能改变 approval/sandbox/provider 凭据端点；项目 LSP argv 不会进入 subprocess；用户级 LSP 仍可运行；项目关闭 exec_policy 被拒/忽略并有 warning；no_project_config 下恶意项目所有自动来源均无效。

### R2 / P1：后台任务创建、执行、恢复共享同一权限快照

**改动边界**：tools/task/tools.py、task models/manager、engine/dispatch.py；与主线程策略归一化共用规则。

- 新建任务无 workspace 参数时，显式写入 `context.working_directory.resolve()`；不能把 None 留给共享 manager。
- 保存来源 thread、执行目录、allow_shell、approval_policy、sandbox_mode、明确的 trust/自动批准选择。能力不能高于会话，模型 schema 不暴露提权字段。
- 执行器当前 `ConfigLoader().load()` 可用来取用户模型/连接参数，但必须由保存的执行权限快照覆盖；同时更新 ToolContext、registry 和 execution_sandbox_policy。只设 `context.trust_mode=False` 不会必然撤回已经生成的全访问沙箱策略。
- resume 与 create 使用同一约束：先校验嵌套限制、目录、所属权限上下文及当前允许的权限。旧任务若要恢复更高权限，返回明确的权限差异审批；不能把一次“恢复任务”的笼统批准当所有新权限批准。
- 没有父审批桥的普通 subagent/task 默认拒绝受控操作；显式用户配置的自动化通过内部 API 授权，不靠类默认 True。

**验收**：两个不同 workspace 共用 manager 时，省略目录也各回各目录；外部/软链接目录拒绝；非 auto 会话恢复旧 auto/full-access 任务不能静默继承高权限；全局 auto 与当前保守会话冲突时按当前会话；无审批桥及时返回错误；显式自动化仍正常运行。

### R3 / P1：审批身份与 Shell 保守分级

**先做最小可靠修复，再谈解析器升级。**

- Shell 记住授权的 key 使用原始 command 的摘要，并纳入 cwd、实际 shell/必要执行档位；不要 lower、折叠引号内空格或只保留首词。牺牲少量复用换取不误授权。
- cron 指纹包含所有实际影响执行的规范化字段，例如 prompt、schedule/run_at、timezone、cwds、delivery、run_now；默认值在算 key 前补齐。
- 对不能证明安全的复合语法统一要求审批。覆盖 `&`、进程替换、命令替换、各类重定向、异常引号；每段/每个 argv 的安全规则要考虑选项，不能只看 cat/git/sort 等名字。
- 只读 argv 解析与 Shell 文本是两个层次。短期可把不支持的语法统一升档；长期只有确有必要才引入成熟语法解析，不自己发明“shlex token 树”。
- source-write guard 修明确的紧贴/引号/路径归一化漏洞；mv 源检查保留，cp 不误禁。解释器/构建器能够执行任意代码，应以审批+实际沙箱约束，不能靠枚举 `os.remove` 等 API 宣称完整拦截。
- 不存在用户 execpolicy 文件时也运行内建风险分类；用户策略只负责明确的附加规则，任何“覆盖默认规则”都应有清晰授权语义。

**验收**：`-d/-D`、大小写路径、引号内空格不共享授权；各语法绕过进入审批/拒绝；`sort -o`、`git diff --output` 不判只读；紧贴重定向与 scratch 路径穿越不能绕 source guard；普通 stdout 输出不误当文件写；真正只读命令的合理用法仍可用。

### R4 / P1：环境、文件读取、OS 沙箱、插件授信

这几个点同属信任边界，但建议拆成独立小提交。

- 凭据写入使用专用安全写流程：临时文件 0600、写完整后原子替换，既有宽权限配置也收紧；不改变普通源文件写入的权限继承规则。
- LSP 纳入子进程环境清洗；必要系统变量+可信显式注入逐步替代名字黑名单。Shell startup 文件、代理变量、SSH agent 通道是额外能力，要在兼容验证中明确处理。
- 插件普通加载不“自愈授信”。旧版迁移需可识别的一次性流程或用户明确确认；grant 撤销不能因 trusted 字段残留自动复活。项目 plugin 继续强制 digest grant。
- runtime/doctor/UI 展示的是实际 sandbox backend 和有效权限，不能只展示请求的 workspace-write 字符串。受限模式无可用 sandbox 时，默认拒绝或显式选择非隔离运行，不默默降级。
- macOS 收窄读取权限时，先列出实际运行必需的系统、解释器、工具链/包缓存读根，再限制用户敏感目录和凭据文件；对工作区内敏感文件也需定义 OS 层规则。文本检查只作为提前给出解释，不能作为安全证明。

**验收**：已有 0644 config 写 key 后变 0600；假密钥默认不出现在 shell/MCP/LSP 环境，可信显式注入仍可用；撤销 grant 后加载不会重新授权；实际 Seatbelt 下读不到测试密钥且常用构建/测试可运行；Linux unavailable 清晰可见且不静默放行。

**产品边界**：本批不擅自改变 auto=完整访问，也不一刀切关闭所有联网。可另加“自动批准+workspace-write”的独立产品配置，但要成套迁移。

### R5 / P1：按来源区分网络目的地

- MCP SSE 对 join 后 URL 强制同 origin，拒 userinfo；scheme/host/默认端口规范化后比较。拒绝后不发送 headers，及时报发现端点失败。
- 模型 `fetch_url` 的公网抓取与用户授信的本地 MCP 分开。前者拒内网，后者允许明确配置的本地服务；不要复制同一黑名单把合法 MCP 全部禁掉。
- registry 使用 https 白名单，禁自动跟随或逐跳重新校验域名/目的地。下载前设大小上限，流式读而非整包读完才比较长度。
- npm 提取前校验 `dist.integrity`（可信元数据中的 SRI）并处理缺失/不支持算法策略。执行 grant digest 仍保留，两者解决不同问题。
- fetch_url 在实际连接层绑定通过验证的 IP，Host/SNI 和证书校验不变；同时覆盖 IPv6、IPv4 映射地址、多 A/AAAA、重定向和代理。用 DNS/transport fake 测换 IP，不访问真实内网元数据。

**验收**：绝对跨域、`//host`、降级 http、改端口均拒；同 origin 相对路径允许；registry 白名单站重定向到非白名单被拒；坏 SRI 包不解压；DNS 第二次变成私网也不能连接；用户明确配置的 localhost MCP 正常。

### R6 / P1：审批、取消、子代理输入的生命周期

- 服务器生成 approval_id，映射 thread_id/turn_id/tool_call_id/执行主体；拒绝重复 register。UI、事件、HTTP resolve 一起迁移，旧 tool_call_id 仅做关联，不是全局索引。
- 审批等待有明确截止时间；超时默认拒绝，finally 移除 pending/remember/meta。取消、卸载、turn 结束共用清理流程。配置值可以后定，先用有界默认；不能只在前端隐藏卡片。
- 后台执行器同时等待 turn 完成和 cancel；取消时对 turn_task 硬取消并 await，利用现有 Shell killpg 清理；保证等待审批时也能中断。
- 无人审批的 inbound 若产品承诺只读，应只给只读工具集或使用立即拒绝 handler。若允许交互审批，则提供可达 UI 通道和超时；轮询结束不等于 turn 结束。
- 子代理每个安全边界消费输入并保存。interrupt 使用“当前 round 中断”机制，清理 partial 后继续执行最新输入；永久停止继续使用总取消信号。不能按旧建议简单设置总 cancel_token 后把新输入一起丢掉。

**验收**：两个线程同模型 tool_call_id 不冲突；过期批准无效；pending 记录在所有结束路径归零；取消真实 sleep 子进程及其孙进程后均消失；审批中取消及时结束；send_input 在下一请求出现且只出现一次；interrupt 中止旧请求、继续处理新指令、不留下孤立 tool_use。

### R7 / P1–P2：历史配对与摘要权限来源

- 压缩选择保留集后，对同一工具轮做 tool_use/result 配对闭包；必要时按完整 round 保留，重新计算预算。若闭包太大，应明确摘要整轮，不能只偷偷删掉半轮。
- 正规化检查 role、顺序、唯一 ID 和完整结果集合；非法导入历史给出明确修复/诊断。客户端出口继续保留兜底，避免把内部偶发坏数据直接发给 provider。
- 摘要仅是模型笔记，不能恢复审批事实；授权保存在与模型内容隔离的服务端记录。保留已有 provenance 与真实用户请求保护。

**验收**：pin 单个历史 assistant 时其结果保留；pin 单个 result 时 call 保留；多工具调用结果齐全；错误 role/重复 ID/结果先于调用不被错误判“完整”；两个协议投影一致；伪造“用户已批准”摘要不改变工具审批。

### R8 / P2：重试职责与前端 partial 替换

- 客户端只做发出首个有效内容前的网络/429/可恢复 5xx 重试；有内容后 StreamError 并结束，不在同一 iterator 继续发送第二次结果。
- TurnLoop 负责是否丢弃 partial 后重采样，统一总尝试预算，避免底层和上层退避相乘。
- DeepSeek/Anthropic 共用 Retry-After 和退避处理，认证/请求格式错误直接失败；等待可取消。
- 给 UI 明确 attempt/reset 信号，使旧 partial 可以被替换；计费记录每个可观测请求，不假设失败请求没有费用。

**验收**：首段出错后最终消息和工具只来自新 attempt；UI 不拼接两次 partial；429/5xx 两种客户端一致；401/400 不重试；连续失败不会出现两层重试放大；取消不继续 sleep/request。

### R9 / P2（数据覆盖路径可提前）：写入一致性、恢复与事件重放

- 文件 stale：同路径内部写串行化，事务中检查版本/准备新内容/提交；提交前发现变化则拒绝并要求重读。处理 symlink 路径替换，capture/ledger 必须对应实际提交版本。明确与不遵守锁的外部写者间仍非通用原子 CAS。
- durable resume：先增加副作用调用开始/完成/未知结果状态。崩溃后对 uncertain 操作先核查，不自动再执行。具备幂等键的外部接口使用幂等键，无接口支持时请求确认；不能靠一句“不要重复”保证。
- rewind：保留审计流，添加历史 revision 或 reset snapshot 协议；旧 cursor 重连拿到一致的新状态。不要只删日志、复用旧 seq。
- rewind 锁：线程/项目操作锁保障一致性；全局活动锁只用于状态验证、占位、提交，磁盘处理放在线程/异步 I/O 中，失败回滚占位。

**验收**：竞争修改不静默覆盖；新文件在并发创建时不误记；副作用成功但 checkpoint 前崩溃显示“结果待核实”；rewind 后旧 cursor 重连无悬空实体；大回退不阻塞另一个线程开始 turn；同线程 start 与 rewind 互斥。

### R10 / P2：有界资源与可观测性

- task 持久化只写修改记录+队列；入队容量有上限，批量操作合并写；不要为解决 O(n²) 就立即换数据库。
- 历史保留按磁盘容量/时间明确配置；内存驱逐与历史删除分离，避免丢 resume 和未投递结果。
- 成本以 request/run ID 去重、按增量合并；先确认 metadata fallback 是否还需要，不为没有生产方的旧字段重建复杂账本。
- completion 回调错误记录并有限重试；父端依 completion ID 幂等消费，mailbox/持久化状态作为补偿读取。
- fork_context 才获取对话快照，不每个普通工具都完整 dump；MCP 参数不夹带父对话。
- 中文 fast-path 单独小改；终端安全先做真实渲染测试，再确定展示层过滤；归档敏感内容按工具类型/字段标记脱敏，而非任意删原文。

**验收**：入队 N 个任务写入量近线性；终态历史超过阈值有可预期清理且不丢可恢复工作；多 agent/mixed tool 重复上报不多计不漏计；丢一次通知仍能恢复；普通工具不持有整段历史；恶意控制序列不改变终端标题/剪贴板等状态。

## 8. 推荐交付节奏与不建议照搬的旧建议

建议小批提交顺序：**R1 → R2 → R3 → R5/R6 → R4 → R7/R8 → R9/R10**。R4 中凭据权限和 LSP 环境可与 R1 同批；完整 OS 读取白名单需要兼容验收，独立交付。文件竞争导致实际数据覆盖若是常见场景，R9 的文件写入部分提前。

每批交付内容：复现用例、最小改动、受影响入口的回归、准确的行为变化说明。完成后再更新旧文档的状态，避免出现“发布说明宣称已修，但执行入口还没接线”。

不建议直接照搬：

- “gather 加 return_exceptions=True 一行根治”：当前已有逐个异常处理，改错会吞取消。
- “换 shlex 就根治 Shell”：shlex 不是执行语义分析器，错误归一化可能把原本升档的命令降成 SAFE。
- “给 interrupt 设置总 cancel_token”：可能直接终止代理，不能完成“打断并继续新输入”的需求。
- “拆 manager 三个类就根治竞争”：代码组织不等于隔离与锁正确，先用具体多调用者回归约束所有权。
- “随内存驱逐删除任务文件”：破坏持久任务的历史和恢复承诺。
- “所有 MCP 都禁内网”：会破坏明确配置的本机 MCP，应按来源分开。
- “有 ID 就能伪造审批”：忽略 bearer 认证；真正应修唯一性、作用域和生命周期。
- “auto 一定应等于少弹窗”：当前 UI 已明示完整访问，需产品迁移，不能当无感安全补丁。

本轮新增的只有这份复核方案。未修改运行时代码、原三份文档或用户正在编辑的 AGENTS.md / CLAUDE.md，也未处理工作区原有的文档删除。


## 9. 已运行测试的范围（便于复查）

第一组文件：test_project_config_security、test_env_filter、test_command_safety、test_client_extra_sanitization、test_sensitive_files、test_serve_insecure_guard、test_task_approval_bridge、test_tool_pairing_projection、test_subagent_approval_escalate、test_fetch_url；contract 下的 test_automation_ingress、test_engine_trust_mode、test_http_approval_handler；workspace 下的 test_shell_write_guard_matrix；engine 下的 test_midstream_resample。结果 184 passed、1 skipped。

第二组文件：test_p0_audit_fixes、test_durable_resume、test_usage_ledger；engine/test_per_engine_context；contract/test_rewind_thread、test_auth、test_approvals。结果 68 passed。

测试使用项目现有 .venv，DEEPSEEK_HOME 指向临时目录。上述测试通过说明这些既有验收点成立；本轮最小验证揭示的边界缺口尚未修复，不能由既有测试绿色推导“全部安全”。复查环境清洗时另重复运行了该文件 13 项，未重复计入 252。
