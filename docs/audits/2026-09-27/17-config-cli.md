# 第十七篇：配置、CLI 与基础设施

日期：2026-09-28。覆盖最后一组 **14 个 Python 模块、4,032 行**，按“入口 → 配置发现/合并 → provider 路由 → CLI 生命周期 → 路径迁移和公共函数”审查。接续 [第十六篇修复](16-implemented-fixes.md)。本文保留原审核时的基线。**更新：本篇 Q01—Q12 的最小修复已实施，见 [修复与收尾记录](17-implemented-fixes.md)、[验证结果](17-fixes-validation.json)。** 原审核阶段未修改这些模块。

总体判断：ConfigLoader、Pydantic 配置模型、provider 默认表和集中路径函数是合理的基础，不需要另建配置框架。当前主要问题是来源与作用域没有贯穿整个加载流程，CLI 接口承诺与实际执行不一致，以及短命令绕开已有资源/会话所有权。

证据：A＝本地探针复现；B＝源代码及调用链确认；C＝未复现的设计建议。已有配置/provider/plugin CLI 测试 **69 项通过**；隔离临时目录、伪凭据和 mock 复现 **12 组观察**，见 [探针](config_cli_probe.py)、[结果](config-cli-probe-results.json)、[验证记录](17-validation.json)。没有连接模型、SMTP 或真实外部服务，没有使用真实密钥。通过已有测试不能证明这些边界正确。

## Q01 · P1：项目来源边界不完整，禁用开关也漏掉入口（A/B）

位置：[loader.py:208](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:208)、[loader.py:271](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:271)。

`workspace` 传给 project_config_path/dotenv_path，但根配置发现和可信分类仍用 cwd。进程位于项目 A、加载工作区 B 时，探针实际采用 A 的根配置。`no_project_config=True` 只跳过 `.deepseek/config.toml`，仍发现 `deepseek-tui.toml`，也先读取项目 dotenv。禁用项目配置没有禁用所有隐式项目输入。

显式配置路径位于另一工作区时，`_is_project_level` 也可能因不在 cwd 下而将它当成可信来源（B）；不能简单以绝对路径等价于用户级可信文件。

建议统一“加载工作区、来源类型、是否显式指定”三个输入，让发现和过滤共用它们。先保持现有文件优先级，只修作用域；明确显式 `--config` 在禁用项目配置时的语义。验收双工作区、两种根文件、隐藏目录、dotenv、显式路径、符号链接及 user home 位于 cwd 的情况。不要仅多加一个 if，留下第二套发现路径。

## Q02 · P1：项目可改变凭据的目的地，字段过滤未覆盖路由（A/B）

位置：[loader.py:170](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:170)、[models.py:386](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/models.py:386)、[inbox.py:105](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/inbox.py:105)。

项目覆盖被剥离 api_key/base_url 等字段，但仍能改 provider。探针中，用户配置的顶层 key 在项目把 provider 从 deepseek 改为 openai 后仍成为 effective_provider_config 的 key。后续客户端按新 provider 的地址和当前解析出的 key 构建连接；实际网络请求未执行。这是“凭据与目的地绑定”的缺口，不能只检查项目有没有直接提供密钥。

`automation.email` 的 smtp_host、to_addr 等也通过项目过滤。读取链把 app config 与单独的邮件配置合并；若用户凭据来自 app config 且未被独立邮件配置覆盖，项目路由可能与可信用户名/密码混用。SMTP 发送实现会登录配置中的 host（B），探针只证明过滤放行（A），不声称已完成凭据泄漏试验。

最小方案是把 delivery 路由/凭据相关配置整体排除出项目覆盖，并在 provider 切换时禁止无来源绑定的顶层 key 自动跨 provider 沿用。现有 config/routing.py 的 config_for_model 在切换 provider 时已经清空顶层 key/base_url，优先复用这个语义，避免 loader 另立一套规则。长期可把凭据引用绑定 provider/endpoint，保留模型、UI 等合理项目偏好。不要直接禁止所有项目配置，也不要仅列出 secret 字段而遗漏其使用目的地。验收假客户端收到的 host/key 组合、邮件独立配置覆盖、profile 内同类覆盖；全程用伪密钥。

## Q03 · P2：profile 选择时机和部分覆盖语义不一致（A）

位置：[loader.py:229](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:229)、[loader.py:354](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/loader.py:354)。

环境覆盖发生在 profile 合并之后。设置 `DEEPSEEK_TUI_PROFILE=fast` 得到 profile 字段 fast，但模型仍是 base。另一方面，profile 的嵌套对象先经过默认值填充，再 `model_dump(exclude_none=True)`：只设置 `ui.show_thinking=False` 的 profile 会把基础配置 locale=en 覆盖成默认 zh。

建议先解析 profile 选择器，再合并其显式字段（嵌套 exclude_unset），最后统一验证配置。来源追踪可以只记录冲突字段及来源，不必建立复杂规则引擎。验收 CLI/env/file 三种选择入口、空 profile、嵌套部分覆盖、managed config 最终优先级。

## Q04 · P2：模型预算表是进程全局可变状态，多个配置相互覆盖（A/B）

位置：[providers.py:120](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/providers.py:120)。

每次 ConfigLoader.load 都 clear/update 全局 context window 表，只用小写 model 名作 key。探针先注册 A 的 custom-fixture=8192，再加载 B 的同名模型=65536，原模型查询随之变为 65536。顺序加载已能复现，不需要靠线程竞态；多 Engine 服务中影响的是仍在运行的预算消费者。

此外，静态已知模型被排除出自定义窗口覆盖，与注释的覆盖优先承诺不一致（B）。本篇不判断静态表中的数字是否符合最新厂商规格。

最小补丁可以显式把配置预算传给 Engine；更完整的接口应按 provider、endpoint、model 解析不可变能力快照，由 Engine 持有。仅给全局字典加锁不能解决语义串扰。验收两个配置交错加载/查询、同名不同端点、已知模型显式低限额。先做正确性隔离，暂无理由为几十个字典项做性能缓存。

## Q05 · P1/P2：CLI 接受的参数没有落实到有效配置（A/B）

位置：[app.py:73](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:73)、[app.py:471](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:471)、[app.py:733](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:733)。

根 callback 声明 api_key、base_url、approval_policy、sandbox_mode、output_mode，却只把 config/profile/provider/model 传给 loader。探针证明 key 和 approval 参数未进入最终 Config；其他三个的未使用由源码确认。安全模式参数看似生效却未应用，应优先修复。

遇到子命令时根 callback 直接返回，使子命令前的全局配置参数被忽略。config set/unset 接受 profile 却写根字段；sandbox check 的 ask 只打印，实际仅调用命令启发式分析，不是完整执行策略模拟（B）。

建议建立一个小的、显式 CLI overrides 对象，通过 Typer context 传递，再进入 ConfigLoader 的 CLI 层；必须在 managed config 和 requirements 之前合并，不能在验证后直接赋值绕过管理策略。对暂未支持的参数明确报错。验收默认入口与 exec/serve、参数放在子命令前后、profile 定向写入、受管理策略约束的覆盖。

## Q06 · P1/P2：one-shot 的失败状态和资源归属不完整（A/B）

位置：[app.py:145](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:145)。

client 创建后，Engine.create 在 try/finally 之外。模拟初始化失败时 client.close 调用为 0（A）。ErrorEvent 打印后 break，函数正常返回；TurnCompleteEvent 未检查 success。调用者也没有转换成失败退出，脚本可能把一次失败运行当作成功（A/B）。

消费循环只等待事件，不监督 engine_task 异常；若引擎在发出终止事件前退出，消费者可能一直等待。finally 中 await 已失败 task 抛出非 CancelledError，也会跳过 engine.shutdown（B）。相似地，mcp connect 的 start_all/展示/stop_all 缺少 finally，异常路径可能跳过关闭。

建议用一个明确的 headless runner 持有客户端、引擎和事件消费任务，获得资源就登记清理，返回结构化结果给 CLI 决定 exit code。最小阶段先补 try/finally 和并发监督即可，不需要重写 TUI 生命周期。验收创建失败、运行异常无事件、ErrorEvent、失败完成事件、取消、关闭失败时后续资源仍被关闭；全部使用可控 fake，无需在线模型。

## Q07 · P2：配置诊断默认输出原始密钥（A/B）

位置：[app.py:518](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:518)、[app.py:540](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:540)。

config list/show 直接序列化模型，探针中的伪 key 出现在输出。config get 可读嵌套敏感字段；config set 仅对顶层 api_key 遮盖，嵌套 provider key 的回显没有同等处理（B）。用户把诊断输出贴入 issue 时容易意外带上凭据。

建议默认统一脱敏，显式查看单项 secret 才要求明确选项；不需要为每次诊断增加确认弹窗。仅把 api_key 改为 SecretStr 不足以覆盖 extra_headers、邮件密码等路径，需要小范围统一序列化策略。验收顶层/嵌套字段、JSON 输出、写入回显，输出只保留存在性信息，不记录测试原始密钥。

## Q08 · P2：CLI 线程修改未复用运行中线程的所有权边界（B）

位置：[app.py:642](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:642)、[app.py:685](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/cli/app.py:685)。

archive/unarchive/set-name 创建 store，读取 helper 又创建另一个 store；读出整个 ThreadRecord 后保存，没有获取 TUI/Server 已使用的线程租约。单次存储锁不能把跨两次调用的 read-modify-write 变成事务。并发运行可能回写旧记录或覆盖彼此 metadata；本篇尚未做跨进程覆盖复现。

建议复用一个存储对象，通过已有 ThreadLease 或共享窄字段更新入口执行操作，明确活跃线程能否改名/归档。给整个 CLI 新建一套线程管理器反而会复制生命周期。验收两个进程修改同一线程、运行时同步与改名交错、租约拒绝时退出码和错误文案。

plugin enable/remove/trust 等包装入口也应统一 outcome→exit-code；当前有些仅打印失败，install/update 却会抛失败退出，install-all 失败计数亦未形成失败状态。这是 CLI 契约一致性建议，不重复审插件内部实现。

## Q09 · P2：目录迁移缺少跨进程协调（B）

位置：[layout.py:21](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/layout.py:21)、[layout.py:203](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/layout.py:203)、[layout.py:236](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/layout.py:236)。

迁移按 exists→move 和冲突目录编号运行，没有 home 级租约。CLI 与 Server 均可触发；并发迁移会竞争源路径、隔离目标，settings 的原子写也没有覆盖读取到合并之间的整个区间。风险由调用链确认，未声称已复现数据损失。

保留现有“冲突隔离、保留自定义 manifest、重复调用处理新增旧路径”的好设计。最小方案是复用现有文件租约覆盖一次迁移，在持锁范围内读/改/写设置；无需立刻引入迁移数据库。验收真实两个子进程、失败中断后重试、源目标同时存在、迁移与 settings 更新并发。

## Q10 · P2：原子写的 fchmod 异常路径泄漏文件描述符（A）

位置：[utils/__init__.py:61](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/utils/__init__.py:61)。

mkstemp 获得 fd 后先 fchmod，之后才进入 os.fdopen 上下文。若 fchmod 失败，except 删除临时路径但没有关闭原 fd。探针验证 fstat 仍成功，随后主动关闭，原目标内容没有损坏。这里是资源泄漏，不是已经复现的半文件覆盖。

建议尽早把 fd 放入上下文所有权，或用明确的“是否转交”标志在 finally 关闭。验收 fchmod/fdopen/write/fsync/replace 各失败点的 fd、临时文件和原内容。目录 fsync 与掉电持久性是另一个保证级别，不应把 rename 等价为任意崩溃都持久。

## Q11 · P2/P3：公共函数的长度契约与 I/O 工作量不一致（A/B）

位置：[utils/__init__.py:160](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/utils/__init__.py:160)、[utils/__init__.py:367](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/utils/__init__.py:367)。

summarize_text 总是先减去省略号长度，`abcd, limit=5` 得到 `ab...`，明明原文就能装下；小于 3 的预算还可能被省略号突破（A/B）。应先判断是否真需截断，并定义非正预算行为。

tail_log 先读完整日志再取最后几行，返回行数不是读取预算（B）。建议有界从文件尾分块读取，设置最大字节数并保留 UTF-8 边界，先用读取量测试，不宣称当前已存在多少毫秒的瓶颈。

logging 的 ContextVar+finally 绑定值得保留；setup_logging 改进程 root level，重新配置未恢复不再指定的 per-logger level，是嵌入、多配置共存时需明确的进程级契约（B/C）。不必因 utils 文件偏长而拆成许多单函数模块。

## Q12 · P3：配置合法性和能力描述需要更明确的局部契约（B/C）

位置：[models.py:41](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/models.py:41)、[models.py:186](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/models.py:186)、[routing.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/routing.py)。

部分 timeout、context_window、并发数和日志保留字段缺少模型级范围约束；错误值能被加载，消费者再各自处理。补约束时须先区分 0 表示禁用还是非法，不能统一加 gt=0。顶层忽略未知字段、UI 禁止未知字段的策略也应解释清楚，避免拼写错误静默变默认值。

routing 的配置复制与显式模型路由保持简单即可；CLI model resolve 对未知模型回落静态默认，与运行时支持自定义模型的语义存在差异。image_capabilities 已把显式视觉配置与端点/模型判断集中，建议保留；以后可与 Q04 的能力快照共用解析输入，但无需现在设计万能 provider 插件协议。

## 逐模块建议

| 模块 | 判断与建议 |
|---|---|
| `__init__.py`（3 行） | 简单包入口，无需扩张。 |
| `__main__.py`（9 行） | 直接委托 CLI，层次合理；退出状态由 Q06 统一落实。 |
| `cli/__init__.py`（3 行） | 导出简单，保留。 |
| `cli/app.py`（1686 行） | 命令包装已调用现有服务，优先 Q05—Q08 的契约修复；之后可按子命令分文件，不要先机械拆分掩盖错误。 |
| `config/__init__.py`（11 行） | 统一导出合理，暂不变更公开接口。 |
| `config/image_capabilities.py`（54 行） | 集中视觉判断，保留显式覆盖；能力数据版本与端点身份仍要长期维护。 |
| `config/layout.py`（361 行） | 冲突隔离有价值，补 Q09 的迁移所有权。 |
| `config/loader.py`（376 行） | 清晰的多层加载雏形；Q01—Q03、Q05 比引入新框架更紧要。 |
| `config/models.py`（424 行） | 类型聚合合理；补凭据来源绑定、部分 profile 语义、必要值域约束。 |
| `config/paths.py`（307 行） | 集中路径和 home 覆盖改善测试性；调用者仍须校验不可信 ID。dotenv 返回映射而非直接污染进程环境的设计应保留。 |
| `config/providers.py`（312 行） | 静态默认表易理解；去除 Q04 全局预算副作用，再谈能力统一。 |
| `config/routing.py`（31 行） | 足够小且职责集中，避免无依据泛化；与 CLI 自定义模型行为对齐。 |
| `prompts/__init__.py`（2 行） | 资源包标记，无独立逻辑缺陷；提示词内容已归第六篇。 |
| `utils/__init__.py`（453 行） | 原子写、日志追踪有复用价值；先修 Q10/Q11，按实际消费者决定拆分。 |

## 推荐实施顺序与方案比较

| 次序 | 最小可验证方案 | 更大方案及暂缓理由 |
|---|---|---|
| 1 | 配置来源/工作区统一；项目 delivery 过滤；凭据与 provider 切换绑定 | 完整配置 provenance 图有帮助，但不是关闭已复现问题的前提。 |
| 2 | CLI overrides 进入 loader；profile 显式字段合并；诊断脱敏 | 重写所有 CLI 命令成本大，无法自动修复遗漏参数。 |
| 3 | headless runner 资源所有权、失败退出；线程元数据更新复用租约 | CLI 再持有独立 Server manager 会引入额外生命周期。 |
| 4 | Engine 持有配置能力快照；迁移锁；atomic writer 失败收尾 | 全局表加锁仅避免数据竞争，仍有配置串扰；迁移数据库暂不必要。 |
| 5 | 长度函数、日志尾读和配置局部约束 | 先验证 I/O 量与语义，再考虑吞吐优化。 |

本篇未做竞争方案的速度排行：已复现问题以行为正确性和作用域隔离为主，给错误全局字典加锁再比较耗时没有决策价值。先用最小反例确定验收，修复时再按真实争议补并行/故障测试。

至此，17 个计划体系的首轮核心审核文案齐备；后续修复亦已交付并按用户要求结束本轮。这不表示所有建议已实施或全仓库已验收。当前目录覆盖、历史遗留和下一步见 [进度台账](progress.md)。
