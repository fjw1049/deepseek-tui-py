# 03 · Hook 生命周期与执行机制审核

基线：2026-09-27 当前工作区，含已有未提交改动。本篇完整阅读 `integrations/hooks.py`，追踪配置、插件适配、主引擎、子代理、TUI、Server 与 Shell 接入；不代表这些关联体系已完成全面审核。只新增审核文案和实验脚本，没有修改业务代码。

## 核心结论

Hook 已具备可用的事件模型、条件筛选、执行器、决策聚合和多种观测接收端。主要问题是**执行生命周期和结果消费没有统一契约**：同一 Hook 配到主工具、子工具、启动事件或后台执行时，能否触发、能否阻断、输出是否被使用都有差异。

优先修复子进程清理、守卫链错误处理和工具入口覆盖；随后补齐结果契约。观测路径确实存在可减少的串行等待，但不能因此把所有 Hook 一律并行或 fire-and-forget。

证据标记：**复现**为附带脚本直接验证；**静态**为代码调用链证据；**取舍**为需要确定产品语义的行为。P1 优先修复，P2 后续修复。未进行真实外网请求、模型调用或系统目录写入。

## 两条路径必须区分

| 路径 | 当前入口与用途 | 正确性要求 |
|---|---|---|
| 观测 Hook | EngineHandle → HookDispatcher → stdout / JSONL / Webhook / ShellHookSink | 不应长期拖慢模型消费；明确顺序、队列上限、丢弃与关闭策略 |
| 生命周期 Hook | Engine/TUI/Shell → HookExecutor → HookResult → 各调用者自行聚合 | 需要决策的事件必须等待完成；拒绝、询问、错误和附加上下文有明确消费者 |

两条路径共享 `_run_shell`，所以进程清理问题影响两者。`shell_hooks` 还同时用于观测构建与迁移为生命周期条目，但二者事件名称体系不同；应在迁移时说明支持哪些旧事件，不宜默默把任意名称复制到另一系统。

## 已确认问题与建议

### H01 · P1：取消不回收进程，超时只杀外层 Shell

**复现。** [hooks.py:286](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:286)

`_run_shell` 只捕获 TimeoutError，没有处理 CancelledError。取消复现中，对模拟子进程的 kill、wait 调用均为 0。超时分支只执行 `proc.kill()`，没有控制进程组：在临时目录运行一个约 250ms 后写标记的 Python 子进程，外层 Shell 的超时设为 50ms，标记仍然生成。实验中的进程均自然结束，没有留下长期任务。

此外，子进程继承 stdout/stderr 管道时，等待 Shell 回收也可能被管道生命周期拖延，因此 timeout 不能直接等同于“所有相关活动在此时停止”。

建议：让 runner 明确拥有子进程生命周期，取消与超时都走终止、升级强制结束、回收流程；POSIX 用独立进程组，其他平台提供等价适配。关闭阶段本身也要有上限，保留原始取消异常。不要仅在 except 中补一个 `kill()` 就认为整个进程树问题解决。

### H02 · P1：前一个 Hook 出错可跳过后续拒绝 Hook，最终放行

**复现。** [hooks.py:739](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:739)、[tooling.py:634](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:634)

配置两个 tool_call_before Hook：第一项 `exit 1` 且 `continue_on_error=False`，第二项 `exit 2`。执行器在第一项后 break，返回结果聚合为 blocked=False；第二项没有执行。主工具包装层只关心 blocked/ask，因而这个失败路径不形成工具拒绝。

非 2 退出码不阻断本身是代码明确支持的协议行为；问题是它与“停止后续 Hook”组合，会跳过后面的独立守卫。建议区分“普通通知失败”“守卫未完成”“守卫明确拒绝”。可选方案是让普通错误不跳过其他守卫，或者将要求完成的守卫错误转为显式失败关闭。不要把 `continue_on_error=False` 同时隐含成两种意思。

### H03 · P1：子代理工具没有运行前后 Hook，Shell 环境 Hook 也未继承

**部分复现、部分静态。** [loop.py:124](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:124)、[loop.py:463](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:463)、[shell.py:1185](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:1185)

子代理 `_execute_subagent_tool` 有审批流程，但不经过主引擎的工具 Hook 包装。传入带 HookExecutor 的 runtime 后，真实子工具入口执行 mock 工具一次，Hook 调用为 0。`subagent_stop` 有单独接入，并不意味着每个子工具也有 Pre/Post Hook。

子 ToolContext.metadata 也未放入 `hook_executor`，而 `_shell_env_from_hooks` 只从该键读取。因此父会话的 Shell 环境准备不自然继承。Server 直接工具接口同样有独立审批/执行入口，静态追踪未见主工具前后 Hook 包装。

建议定义覆盖契约：若 Hook 被用作全局工具守卫，应在主/子/直接工具入口共用执行边界；如果只面向主会话，配置及 UI 必须明确范围。子代理需要自己的 session/tool 身份，不能靠把父 metadata 全量复制进去解决。

### H04 · P1：兼容工具别名在 Hook 检查后才规范化

**复现。** [tooling.py:623](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:623)、[dispatch.py:225](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/dispatch.py:225)

包装层先规范化名称检查工具可用性，但构建 HookContext 时又使用原始名称和参数。随后实际工具分发使用规范化结果。复现调用旧名 `task_shell_start`，可用工具为 exec_shell，Hook 却看到 task_shell_start。

因此 condition 指定 exec_shell 或类别 shell 的守卫不能覆盖这条兼容入口。旧名当前没有通过 schema 主动宣传，但执行层明确保留了兼容支持，不能以“模型通常不调用”作为完整性保证。

建议 Hook 针对**将执行的规范化请求**决策，同时单独保留 original_name/original_input 供审计展示；若未来支持 updatedInput，变更后应再次校验和审批。本篇未发现已有工具参数重写实现，不能把输出字段能被解析误认为支持重写。

### H05 · P2：工具退出码条件没有被真实调用链填充

**复现。** [lifecycle.py:25](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/lifecycle.py:25)、[tooling.py:683](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:683)、[hooks.py:902](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:902)

HookContext 和条件引擎支持 tool_exit_code，但生命周期上下文构建接口没有这个参数，工具执行后只回填 result/content 和 success。包装层收到 metadata.returncode=7 的模拟 Shell 结果后，后置 Hook 的 tool_exit_code 仍是 None。

结果是配置 `exit_code=7` 的 Hook 不触发，DEEPSEEK_TOOL_EXIT_CODE 也不出现。建议从已结束 Shell 的结构化结果填充，其他工具保持 None；后台 Shell 的“启动成功”不能冒充最终退出码，需要独立完成事件。

### H06 · P2：已解析的输出大量没有消费者，会话事件依赖界面

**静态调用链。** [hooks.py:553](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:553)、[tui/app.py:292](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:292)、[core.py:1900](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1900)

| 输出/事件 | 当前消费情况 |
|---|---|
| message_submit 的 block / additional_context | 主引擎消费，内部 turn 有显式跳过逻辑 |
| tool_call_before 的 deny / ask | 主工具包装消费；allow 不绕过常规审批，这一点值得保留 |
| tool_call_before 的 additional_context | 聚合后没有注入到模型上下文 |
| tool_call_after 的 block reason / additional_context | 追加到工具结果；不会撤回已经完成的工具副作用 |
| systemMessage | 解析并聚合，但没有找到生产调用者消费 system_messages |
| session_start 的 stdout/additional_context | TUI 调用后忽略返回值，启动知识不能据此进入对话 |
| session_start / session_end / on_error | 生命周期调用点主要在 TUI；Engine/Server 的观测事件不等于调用这些生命周期脚本 |
| turn_end / subagent_stop | 处理阻断并让模型继续；主引擎有 Hook 重试上限，子代理受总步数限制 |

建议建立一张可执行的事件契约表：哪些字段适用、由谁消费、触发几次、失败如何处理。会话启动/结束放到公共会话生命周期，界面只呈现消息；启动上下文按明确 scope 注入且避免恢复会话重复注入。无效字段应提示不支持，不能“解析成功但静默丢弃”。

### H07 · P2：兼容方言只转换名称，没有转换文件工具参数

**复现。** [hooks.py:438](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:438)、[plugin_compat.py:27](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugin_compat.py:27)

本地文档明确举例社区脚本读取 `.tool_input.file_path` 可直接工作；实际把 write_file/path 转成 claude 方言后，只得到工具名 Write，tool_input 仍是 `{path, content}`，没有 file_path。现有测试重点验证了 Bash/command，不能代表所有工具兼容。

建议把兼容层作为版本化输入/输出适配器，逐工具建立最小契约测试；尚不支持的字段明确列出。这里是本地承诺与本地输出的差异，本篇没有对照外部最新协议，也不宣称完整协议兼容性审计。

### H08 · P2：输入环境与输出缓冲没有整体大小上限

**复现。** [hooks.py:299](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:299)、[hooks.py:480](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:480)、[hooks.py:824](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:824)

tool_result 有截断，但 tool_args 同时放入环境和 stdin，未限制；20 万字符内容产生 200,015 字符环境值。较大文件写入可能触及 OS 参数/环境大小限制，本篇未测定平台阈值，不能声称本机已触发 E2BIG。

`communicate()` 无上限地收集 stdout/stderr。一个输出 1MiB 文本的短命 Hook，返回 stdout 和 additional_context 均保留完整内容；如果在 message_submit 使用，将继续流入模型上下文。这里证明无截断，不是测得内存恰好翻倍，两字段可能引用同一字符串对象。

建议 stdin 承载完整结构化输入，环境只保留短标识/兼容摘要；输出流读取设置字节上限，超限给出明确错误。决策 JSON 不宜直接截断后按普通文本继续处理；模型附加上下文另设预算。限制应能说明原因，避免无声丢数据。

### H09 · P2：后台 Hook 缺少所有权、关闭与结果报告

**静态。** [hooks.py:850](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:850)

`create_task` 后没有保留任务集合，立即返回 success=True；输出送 DEVNULL，不解析决定；正常退出但 returncode 非零也不记录失败，只有抛异常才记录。执行器没有 drain/close 方法。会话关闭不能有序等待或取消这批任务，且取消会继承 H01 的进程问题。

建议返回“已调度”而不是“已成功”，保留任务集合并在 done callback 中观察异常/退出码；提供有限并发和会话关闭。background 仅允许观测事件，或明确声明其 block/ask/context 无效，防止用户把守卫配置为后台却误以为仍有约束。

### H10 · P2：观测接收端串行阻塞生产者，关闭责任不一致

**性能最小实验＋静态。** [hooks.py:366](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py:366)、[handle.py:149](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/handle.py:149)

EngineHandle 先入事件队列，再 await Hook；当前事件可能已被界面读到，但生产者要等所有 sink 才继续。每个响应 delta 都可经过这条路径。Webhook 超时和重试、Shell 启动延迟会累积到模型流消费上。10 秒 HTTP timeout 还是传输阶段限制，不应把重试预算简化成严格的总时限保证。

AppRuntime.shutdown 有遍历 sink.close 的实现，是正确的局部做法；Engine.shutdown_session 与 HookDispatcher 没有统一的对应所有权协议，所以不能说所有入口都泄漏，也不能保证所有入口都关闭客户端。

建议先并发独立接收端、保留每端顺序，再按需要引入有界队列。不能每个 token 都无上限 create_task。定义 queue-full 时背压/采样/丢弃策略，并给关键事件与 delta 不同策略；关闭要 drain 或明确放弃。

## 配置与信任：需要明确的取舍

1. **enabled 的范围不一致（复现）**：`HooksConfig(enabled=False, stdout=True, webhook_urls=[...])` 仍构建 StdoutHookSink/WebhookHookSink；执行器则不执行生命周期 Hook。若 enabled 只控制生命周期，应改名或说明；若它是总开关，构建器也应检查。实验仅构建对象，没有向 URL 发送请求。
2. **default_timeout_secs 实际覆盖所有单项（复现）**：全局 60 秒、单项 1 秒，实际选择 60。若这是强制值应重命名；若是默认值，应让显式单项优先，并在配置中区分未设置和默认 30。timeout 正数、有限值也应验证。
3. **条件拼写错误按匹配处理（复现）**：未知 type 最终返回 True，`tool_nam` 会成为所有工具执行；all/any 还忽略非字典项。事件、方言和递归条件缺少加载时校验。建议拒绝无效配置并给出位置，不要让错误自动扩展执行范围。
4. **完整环境继承（复现）**：Hook `_base_env` 复制 os.environ，合成 API_KEY 可见。它不同于 Shell/MCP 的敏感变量过滤。项目配置已禁止自行安装 hooks，插件执行也有信任机制，因此不能据此宣称任意仓库能窃取凭据。应明确“可信宿主扩展”与“受限模型工具”的区别，按需增加环境声明或过滤；不能在未考虑插件兼容性的情况下全局删变量。
5. **工作目录**：执行使用 executor/config 的目录，而 stdin.cwd 来自 HookContext.workspace。多工作区或显式 working_dir 时两者可以不同。建议分别命名 project_dir/execution_cwd，避免脚本读取 stdin 后假定相对路径已在同一目录。

## 按职责逐段评价

本体系核心集中在一个约千行文件，物理上一个模块，逻辑上至少有以下边界。

| 部分 | 当前值得保留 | 建议 |
|---|---|---|
| 事件 dataclass 与 event_to_dict | 数据结构简单，没有全局注册副作用 | 事件名用明确类型；新增事件时补序列化穷举测试即可，无需事件总线框架 |
| Stdout/JSONL/Webhook/Shell sink | 接口小；JSONL 写入移到线程；Webhook 客户端可复用 | 补 close 和背压契约；stdout 对交互 UI 的影响由入口明确选择；不默认把所有事件并发乱序发送 |
| `_run_shell` | 共用 runner 避免重复子进程代码 | 最优先加生命周期与 I/O 上限；作为基础设施独立测试 |
| HookContext | 输入组装集中，便于方言适配 | 分离协议转换、执行目录、环境导出；减少重复大 payload |
| HookResult/HookDecision | deny/ask/附加上下文独立字段，聚合逻辑短 | 不要扩大为无类型 dict；增加适用事件和失败状态，保证调用者完整消费 |
| HookExecutor | 条件、配置、执行分开为小方法；串行顺序容易理解 | 清晰区分 guard 与 observer，持有后台任务；停止依赖 name 字符串推断插件归属，优先显式 owner |
| 条件与 legacy/config builder | 兼容旧配置成本较低 | 加加载时校验及清晰迁移提示；默认与覆盖语义分开 |
| 引擎与界面适配 | message_submit 已集中到 Engine；Stop 有无限阻断防护 | 继续收拢公共生命周期；UI 只负责展示，避免不同入口漏事件 |

若需要拆文件，建议先分为“事件/观测”“生命周期协议/执行器”“进程 runner”三个职责，而不是按历史 `From xxx.py` 注释恢复大量小文件。拆文件本身不会修好入口缺失，优先用契约测试固定行为。

## 方案比较与最小实验

| 方案 | 优点 | 代价与限制 | 推荐顺序 |
|---|---|---|---|
| A 局部修复、保留串行生命周期 | 清理进程、规范化输入、补入口与输出消费者，改动可分批验收 | 各调用方仍可能遗漏字段，需要契约测试 | 先做 |
| B 公共 Hook 边界＋有界观测分发 | 主/子工具共用决策；观测接收端慢时不无限扩散任务 | 需要显式 scope、队列关闭和错误策略 | A 后逐步提取 |
| C 独立扩展宿主进程 | 可集中隔离、监控、跨语言扩展 | IPC、安装、权限、跨平台复杂度高 | 暂无必要立即采用 |

[hooks_compare.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/hooks_compare.py)：20 个事件、3 个独立接收端，每次人为等待 10ms。所有方案均检查 60 次投递完整、每个接收端顺序正确。队列候选为每端最多 4 项，实验结束 drain；未修改生产代码。

| 方案 | 生产者提交完成 | 全部投递完成 |
|---|---:|---:|
| 当前逐端串行 | 657.2ms | 657.2ms |
| 同一事件的接收端并行 | 220.8ms | 220.8ms |
| 每端有界队列 | 163.5ms | 217.1ms |

这是单次合成延迟实验，不是生产性能预测。队列没有凭空增加接收端吞吐，它只是使生产者提前走有限步数；队列满仍产生背压。并行候选只适合独立观测端；依赖前序副作用的生命周期脚本不能直接照搬。

## 验证范围与复现方式

[hooks_probe.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/hooks_probe.py) 验证了超时后代存活、取消未清理、错误跳过拒绝、disabled 构建差异、旧工具名、退出码缺失、子代理不触发、文件参数方言差异、条件拼写、默认超时优先级、环境继承及输出大小。

```bash
PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/hooks_probe.py
PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/hooks_compare.py
```

脚本断言当前行为，包括缺陷，不是期望正确行为的回归测试。真实子进程仅执行短命的临时目录标记和 1MiB 文本输出；工具执行替换为 mock，密钥为合成字符串，未打印或读取真实密钥值。后续修复应把对应断言转成期望契约并移入正式测试。

现有相关测试 **67 passed**：`test_hooks_engine_integration.py`、`test_hooks_e2e_real.py`、`test_plugin_conformance.py`、`engine/test_turn_end_gates.py`、`parity/phase_d/test_mcp_hooks_p0.py`、`parity/phase_d/test_mcp_hooks_p1.py`。测试使用隔离的 DEEPSEEK_HOME 与插件目录。未跑整库测试，未验证 Windows 进程树控制，未测试真实远程 Webhook 或外部最新协议。

## 建议实施顺序

1. 修 H01/H02：取消与超时回收、守卫错误不跳过拒绝；测试必须包含子进程和多 Hook 链，而不只测单脚本 exit code。
2. 修 H03/H04/H05：统一工具前后边界、规范化输入、正确结果元数据；同一工具通过主/子/兼容入口获得一致守卫覆盖。
3. 修 H06/H07：逐事件定义输出消费者，补文件工具方言契约；只承诺已支持的兼容范围。
4. 修 H08/H09：输入输出上限和后台任务所有权；会话关闭后没有残余任务/进程。
5. 优化 H10 并澄清配置语义：先采用低复杂度方案，测得真实瓶颈后再增加队列策略。

下一篇：持久化 Task 与恢复，重点检查状态机、存储一致性、取消与重启、执行授权继承和恢复边界。
