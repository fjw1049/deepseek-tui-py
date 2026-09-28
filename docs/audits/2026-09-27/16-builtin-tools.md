# 第十六篇：内置工具的文件边界、资源预算与状态契约

日期：2026-09-28。接续 [第十五篇修复](15-implemented-fixes.md)，覆盖本篇清单中的 **16 个 Python 模块、5,884 行**，按“文件与搜索 → Shell 与网络 → 计划与交互 → 编码及公共辅助函数”的调用关系审核。registry、Engine 调度、权限、Task、插件发现已在前篇审过，本篇只追踪与这些工具的交界，不重复宣称完整审核。

更新：N01—N11 的最小修复已实施，见 [修复记录](16-implemented-fixes.md) 和 [修复验证](16-fixes-validation.json)。下文保留修复前的发现、位置及证据，不代表当前代码仍有全部原缺陷。

原审核轮没有修改这 16 个模块的生产代码。A＝本地探针复现；B＝实现及调用链确认；C＝方案或尚未复现的扩展风险。探针只访问临时文件和模拟输入，不访问网络、真实凭据或用户工作文件。已有相关测试 **109 项通过**，新增探针仍复现 **9 组边界问题**；测试通过不能替代对契约边界的检查。

总体判断：ToolSpec、ToolContext 与 ToolResult 已提供够用的扩展入口，无需再增加“通用工具框架”。主要缺口是路径检查只覆盖入口、内容和版本戳不属于同一次读取、返回长度被当成采集预算，以及工具状态绕开既有生命周期所有者。先补这些边界，比拆大文件或统一类继承更有价值。

## N01 · P1：搜索跟随文件符号链接，绕过读取范围和敏感文件过滤（A）

位置：[search.py:400](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/search.py:400)、[search.py:468](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/search.py:468)。

`GrepFilesTool.execute` 只通过 ToolContext 校验搜索根。`os.walk` 默认不递归目录符号链接，但会列出文件符号链接；之后敏感文件判断针对别名，`read_text` 则跟随真实目标。临时工作区中 `public.txt → 工作区外文件` 和 `alias.txt → .env` 均被 grep 读出。相反，read_file 对最终解析路径执行检查。这不是假设性的命名问题，也不应误写为 os.walk 会递归所有目录链接。

建议先让遍历候选文件通过同一个授权边界：明确最终路径必须在工作区或获准额外读根，并对真实目标检查敏感文件。拒绝所有文件符号链接是更小的补丁，但会损失仓库内合法链接的通用性。传入“候选路径授权函数”比让底层搜索依赖整个 Engine 更合适。检查与 open 之间仍有替换窗口；若威胁模型包括恶意并发替换，再讨论基于文件描述符的打开及核验，不能把 resolve 检查称为消除所有竞态。

验收：目录链接、文件链接、工作区内目标、额外读根、敏感别名、悬空链接；拒绝项计入跳过统计，不能把内容带进 metadata。

## N02 · P1：读取内容与记录版本戳之间存在空隙，旧内容可以配上新指纹（A/B）

位置：[file.py:150](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/file.py:150)、[file.py:233](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/file.py:233)，相邻契约 [registry.py:176](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/registry.py:176)。

read_file 在线程里读取，返回后才调用 `note_file_content` 重新 stat。探针在实际读取函数返回前写入较长的新内容：工具返回旧文本，记录的却是新文件 mtime/size。随后 write_file 的 stale 检查返回 false，新内容被旧认知下的替换覆盖。mtime/size 本身也不是内容哈希；这里先修更直接的版本配对错误。

建议读取结果携带同次打开文件的前后 stat；发生变化则拒绝记录为有效快照或有界重试。写入前再核对期望版本，失败保留原文件。进程内按路径锁能串行化本程序写者，但不能防止外部编辑器；原子 rename 防半写，也不等于比较后替换的原子事务。要明确保证级别，避免承诺绝对无竞争。

另外，WriteFile 将旧内容读取时的所有 OSError/ToolError 都当成“文件消失”，可能丢失正确 before-image；应只对确实不存在的情况降级。`_write_text` 使用裸 to_thread，取消等待不等于停止落盘，应在工具调度的资源所有权边界验证取消后的最终结果。本篇未把后两项描述成已完成完整 Engine 复现。

验收：读取中修改、读取后修改、原文件删除、权限错误、并发写入、取消写入；同时核对实际文件和 mutation/checkpoint 的 before-image。

## N03 · P2：页数和结果条数限制没有约束读取、枚举与正则总工作量（A/B）

位置：[file.py:489](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/file.py:489)、[search.py:468](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/search.py:468)、[search.py:550](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/search.py:550)、[path_suggestions.py:77](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/path_suggestions.py:77)。

read_file 取第一页一行，仍扫描后续全文以获得 total_lines；探针读取 **2,097,163 字节**。只读一个 64 KiB 块的最小原型得到相同首行，读取 **65,536 字节**，但不再提供精确总行数。这是约 32 倍的读取量差异，不是已测得 32 倍运行速度。

单行没有换行时 `buf += chunk` 累积到扫描上限附近，行宽截断要到解码和返回之后才执行。grep 的 head_limit 只限制返回行，仍读取每个候选文件、建立 splitlines/match_idx，并对每一行分别执行带 50 ms 超时的 regex；这个超时不是全任务总期限。file_search 先收集所有匹配再截输出。路径建议的 100 ms 检查也发生在 `list(parent.iterdir())` 之后。

建议优先使用“有更多结果但总数未知”的分页语义，在页面结束后只额外探测少量内容；对超长行独立计数并截断缓冲。搜索若必须保留精确总数，应明确让计数模式承担全扫描，内容模式按总文件数/字节/期限提前结束并返回 truncated 原因。路径建议逐项迭代且设置条数上限。暂不为此引入索引服务；只有测得重复大仓库查询成为主要成本后才值得做。

## N04 · P2：Shell 输出先无限采集，完成后截断无法保护进程内存（A/B）

位置：[shell.py:812](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:812)、[shell.py:858](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:858)、[shell.py:1009](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:1009)。

普通进程使用 communicate 聚合全部 stdout/stderr；PTY 的 `_reader_loop` 持续扩张 bytearray，读取 output 又复制为 bytes。完成通知截断和后续工具结果 spill 都发生在采集之后。模拟 256 次、每次 4 KiB 的真实 reader 循环，内存缓冲保留完整 **1 MiB**；这是机制验证，不是内存压力或 OOM 实测。

推荐持续排空管道并写入受控临时文件，内存只保留有界头尾及读取游标，同时返回截断/落盘信息。简单停止读取会把子进程堵死，不是可接受的上限实现。只用环形缓冲较简单，但失去完整输出；“有界内存 + 落盘”更符合已有大输出读取机制。还需明确磁盘上限、清理所有权及取消后的状态。

已有环境脱敏、沙箱统一构造、进程组取消、前台超时转后台和持续排空应保留。PTY reader 的取消/异常退出与 fd/waitpid 收尾值得补故障测试；本篇没有据静态检查声称已复现孤儿进程。

## N05 · P2：工具名兼容性解码破坏可逆性（A）

位置：[encoding.py:60](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/encoding.py:60)、[encoding.py:110](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/encoding.py:110)；消费者 [client/streaming.py:136](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/streaming.py:136)。

`from_api_tool_name(to_api_tool_name("toolx00002E"))` 得到 `tool.`。第二轮裸十六进制兼容解码，把原本合法的名称片段视为模型漏写分隔符。这会让合法注册名在响应里变为别的名字，影响第三方工具扩展。

建议首先精确匹配本轮发出的 wire-name → 注册名映射；确实未知时才尝试兼容修复，并且只接受能唯一指向已注册工具的候选。直接删除宽松解码最小，但会牺牲已支持的模型容错。不要通过增加更多猜测规则“修复”名称冲突。验收遍历 ASCII 名称、转义字符、原生 x+hex 片段、非 ASCII 和冲突候选。

schema sanitizer 的原地变换已有明确契约；扩展方若返回缓存 schema，序列化入口最好先复制，避免 provider 适配污染原定义。这是 C 级扩展建议，未作为本次已复现故障。

## N06 · P2：一条非法 gitignore 范围即可让整个搜索失败（A）

位置：[gitignore.py:40](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/gitignore.py:40)、[gitignore.py:134](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/utils/gitignore.py:134)。

模块说明承诺坏规则跳过，但 `.gitignore` 中 `[z-a]` 转成正则时直接抛出 `re.error: bad character range`，add_dir 没有逐条捕获，搜索随之失败。应在单条规则边界处理无效表达式，记录跳过并保留其余规则；也为用户 glob 给出明确 ToolError。

支持完整 Git ignore 语义可选择成熟匹配器；继续维护当前子集也可以，但应说明转义、否定、目录剪枝等限制，并用本地 Git 行为作对照，不能声称完全等价。仅为了这一条异常引入大依赖不划算。

## N07 · P2：用户问题只验证真假值，未落实类型和 ID 唯一性（A/B）

位置：[user_input.py:38](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/user_input.py:38)，入口 [tooling.py:787](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:787)。

header/id/question 以及 option label/description 只检查非空；整数或非空 dict 都能通过。两个相同 ID 的问题也被接受。Engine 对此工具提前拦截，不能假定后面的普通 registry schema 校验会补救。错误类型会进入 UI/答案关联层，重复 ID 失去唯一映射。

建议就在专用解析入口严格校验 str、非空白和 ID 唯一，复制经过验证的 options。保持该工具由 Engine 拦截的设计，不必为了一个输入结构引入通用表单框架。验收错误类型、全空格、重复 ID、缺字段和合法多问题往返；错误应作为 ToolError 返回，不应启动 modal。

## N08 · P2：网页去重合并了不同资源，提取 fallback 的错误边界也不一致（A/B）

位置：[web.py:522](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/web.py:522)、[web.py:119](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/web.py:119)、[web.py:695](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/web.py:695)。

normalize_url 对整个 URL 转小写，移除 scheme/query，再去 www 和末尾斜线。探针中 `/Page?id=1`、`/Page?id=2`、`/page?id=1` 三个不同 URL 只剩一个。主机名规范化可以保留，但路径大小写和业务 query 默认应保留；仅对明确跟踪参数做窄范围移除也要有依据。

FetchUrl 对提取器只捕获 ToolError，而 `_anysearch_extract` 的 `resp.json()` 可以直接抛 ValueError；格式错误的成功响应会绕过直连 fallback。WebSearch 则已捕获 provider Exception 并继续，不应把这两条链混为同一个问题。max_chars/max_results 使用 `optional_int(...) or default`，零和负数语义也不清晰，建议入口有界校验，避免负数进入切片。

直连 GET 已有 2 MiB 流读取上限并逐跳检查重定向，这是应保留的设计；搜索/提取的 POST JSON 仍整包加载，建议共享有界响应读取。DNS 检查与实际连接分离还有地址变化窗口，是否需要连接时地址约束要按部署威胁模型决定；本篇未进行 DNS 重绑定或在线 SSRF 试验。

## N09 · P1：通过正文子串识别计划提醒，会删除真正的用户消息（A）

位置：[plan_mode.py:314](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/plan_mode.py:314)、[plan_mode.py:319](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/plan_mode.py:319)。

`is_approved_plan_reminder` 只寻找 `The approved plan file is at`，不看 MessageOrigin。带 runtime_thread_id 且未批准计划时，sync 会过滤所有命中消息。探针构造一条真实用户问题“解释这个短语”，同步后历史为空；批准状态下，同样的文字还可能阻止真正提醒注入。

应只删除或去重本系统生成、带明确来源和提醒类型的消息。现有 MessageOrigin 与 reminder 结构已可作为基础，不要增加更多英文识别模板。兼容旧历史时也必须限制来源，而不是猜测所有用户文本。

另外，计划响应解析用“包含 accept/yolo/接受”等宽松片段判断，无法可靠理解否定；更稳妥的是优先严格匹配稳定 option value，兼容层只接受已知完整标签，未知文本保持未决定。该项为 B/C，未演示完整 UI 权限升级路径。plan_file_has_content 读取整个文件且只捕获 OSError，非法 UTF-8 与超大计划还需入口限制。

## N10 · P2：计划工具依赖 TUI，文件发布也缺少原子性（B/C）

位置：[knowledge.py:124](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/knowledge.py:124)、[knowledge.py:354](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/knowledge.py:354)。

PlanUpdateTool 为了纯计划解析，导入 `tui.sidebar`；CLI/server 工具执行由此反向依赖 Textual 展示层。随后直接同步 write_text，再更新内存 plan store，写入中断可能留下截断文件。建议把解析和计划快照放到一个小的领域模块，由工具和侧栏共用；复用已有原子写入，再发布内存状态。无需抽象通用 Repository 或把所有 metadata 改成一套新模型。

note 文案称“session notes”，默认实际写用户级 notes 文件，应明确作用域或真正按会话区分。SkillLoad 的正文格式化与 metadata 分别扫描 companion 文件，同一次加载扫描两遍；只收集一次、显式条数/字节预算足够。显式 skill_path 仍要保持工作区/已授权根的边界；这里不要求任意路径自动提权。

验收计划落盘失败旧版本仍可读、工具与 UI 解析一致、无 Textual 的纯解析测试、技能目录内容变化时正文和 metadata 一致。

## N11 · P2：Checklist 持久化在无归属任务中进行（B）

位置：[todo.py:222](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/todo.py:222)，消费者 [task/manager.py:455](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py:455)。

工具修改内存后，`loop.create_task(manager.record_tool_metadata(...))` 不保留任务或观察异常，工具成功结果也不等待持久化完成。manager 的锁只能保护单次更新，不能让无人管理的 coroutine 自动属于 Engine/Task 的退出边界；退出时丢更新或写盘失败不被工具感知是未关闭的风险。相同模式也存在于 task/helpers，后续应统一所有者，本篇不扩展修改其生产代码。

推荐让异步执行入口 await 持久化，传播明确失败；若需要低延迟，再使用 TaskManager 所有的队列、序号与 shutdown drain。仅加 done callback 可以观察错误，不能保证落盘。现有 status 归一化、单个 in_progress 约束、相同列表幂等处理和只读不发送 task_updates 都应保留。这里没有伪造“已测得随机丢失”的数据，下一轮应以延迟写入和异常注入作回归。

## 逐模块结论

| 模块（行数） | 通用性、优雅与可扩展性判断 | 建议 |
|---|---|---|
| `tools/__init__.py`（1） | 空入口没有注册副作用，适合继续通过显式 runtime 组装。 | 保持，不增加 import 时自动发现。 |
| `encoding.py`（262） | provider 名称/Schema 适配集中合理；猜测性解码侵入身份契约。 | N05；严格映射优先，宽松兼容受注册表约束。 |
| `file.py`（597） | Read/Write/Edit 的职责和 mutation 接口明确，精确编辑优于静默模糊替换。 | N02/N03；内容版本配对、有界页读取、取消落盘契约优先，不先拆类。 |
| `search.py`（559） | grep 内容、计数、文件名模式共用遍历，扩展点够用。 | N01/N03；候选文件授权和总工作预算，输出截断与精确计数分开定义。 |
| `shell.py`（1482） | 沙箱、环境、前后台共用已有基础；生命周期和输出聚合集中在一个大模块。 | N04；先提取有明确关闭责任的输出采集器，再考虑普通 pipe/PTY 的小型共同接口。 |
| `web.py`（792） | provider fallback、结果模型、网络 policy 与重定向检查可复用。 | N08；保守 URL 身份、有界响应、归一化 backend 错误。需要第三种 provider 时再抽接口。 |
| `knowledge.py`（387） | note/plan/skill_load 是三个不同业务，不必强行共享基类。 | N10；移动纯计划解析，原子发布，明确 notes 作用域；companion 单次收集。 |
| `plan_mode.py`（405） | 稳定选项 value、线程计划路径、由 Engine 拦截切换是好边界。 | N09；来源识别代替正文猜测，未知答复不得启发式升级模式。TUI 本轮已设置线程 ID，原注释的工作区路径说明需后续同步。 |
| `todo.py`（540） | 小数据结构、幂等写、部分更新与可读结果较清晰。 | N11；持久化所有权收回异步入口，保留现有状态规范化。 |
| `user_input.py`（167） | 专用验证器可独立测试，拦截式交互避免 ToolSpec 自行操作 UI。 | N07；严格解析并复制输入，保持 UI 无关。 |
| `utils/__init__.py`（32） | 仅导出工具辅助函数，区别于全局 utils，边界明确。 | 不迁入 Engine 生命周期或 UI 功能。 |
| `utils/edit_diagnostics.py`（163） | 诊断提示不直接改文件，兼容排版差异而保持精确编辑，值得保留。 | 最近行匹配最多重复 splitlines 三次；大文件时复用分行结果。优化优先级低于 N03，未测耗时。 |
| `utils/gitignore.py`（202） | 小型 matcher 易测试，缓存编译合理，但自定义语义维护成本会增长。 | N06；逐条容错，声明支持子集，再根据兼容需求选依赖。 |
| `utils/path_suggestions.py`（124） | 建议不自动重试，避免猜错路径后操作，设计合理。 | N03；枚举前后都有预算，逐项处理；错误提示保持 fail-open。 |
| `utils/sensitive.py`（60） | 小型纯规则可复用，是凭据文件兜底，不是完整文件授权。 | N01；由调用者对最终路径执行，保留读写策略差别，不能依靠别名检测。 |
| `utils/validation.py`（111） | 严格整数排除 bool，require/optional/pick 职责有区分。 | 复用 optional_bool/non_negative_int，减少工具自行 truthy 转换；无需再造通用参数 DSL。 |

## 最小方案对比与建议顺序

| 问题 | 方案一 | 方案二 | 本轮证据与倾向 |
|---|---|---|---|
| 搜索链接 | 全部跳过 symlink | 按最终目标授权 | 已复现两类越界；优先保留合法内部链接的目标授权，恶意替换另做文件描述符级方案。 |
| 一行分页 | 保留精确总行数，全扫描 | 有界页 + has_more | 实测读取量 2,097,163 对 65,536 字节，同首行；倾向有界页，但不能保留原总行数承诺。 |
| Shell 输出 | 只留环形头尾 | 有界内存 + 文件 | 实测 reader 无界保留；倾向后者，符合现有 spill 读取方式，需补磁盘预算。 |
| Checklist 落盘 | 执行入口 await | 有所有者的队列 | 尚未做延迟基准；优先 await，小规模元数据通常不值得增加队列协议。 |

推荐修复顺序：先 N01/N02/N09 的范围和内容完整性；再 N04/N07/N05 的资源及输入/身份契约；随后 N03/N06/N08；最后 N10/N11 的职责收敛。每组先将本篇缺陷探针转成期望行为回归，再改生产实现，不能保留“缺陷复现成功”等同于“修复通过”的断言。

证据：[探针源码](builtin_tools_probe.py)、[探针结果](builtin-tools-probe-results.json)、[验证记录](16-validation.json)。读取量对比是单 fixture 的操作计数，未作跨平台性能或在线模型测试。本篇也没有重新审核完整 registry、安全策略和第三方 SDK。

下一篇：**配置、CLI 与基础设施**。
