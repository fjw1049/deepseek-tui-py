# 第十篇 · MCP 连接、工具发现与调用生命周期审核

> 本文保留修复前的历史基线。M01–M08 已实施局部修复，见 [第十篇实施记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/10-implemented-fixes.md)；其余建议与局部修复边界见实施记录。

日期：2026-09-27，接续 [客户端修复](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-implemented-fixes.md)。覆盖 mcp/ 的 9 个 Python 文件与 tools/mcp.py，共 10 个模块。沿“配置 → 连接 → 握手 → 发现 → 路由 → 请求 → 关闭/重载”审查，关联 Engine 权限入口只追踪调用边界。

**主要建议：保留 transport/client/manager 分层，优先把连接所有权、配置生效和请求截止时间做成可靠契约。** 当前代码已处理许多单次失败，却仍存在并发建立多份连接、禁用后旧路由可用、取消清理不完整等跨阶段问题。继续增加局部 try/except 不能代替生命周期管理。

本篇只审核，没有修改 MCP 生产代码。全部复现使用临时配置、假客户端、真实内存 StreamReader 或 httpx.MockTransport；没有读取用户 MCP 凭据，没有连接用户配置的服务，也没有用真实外部工具制造副作用。

## 1. 逐模块审核

| 模块 | 值得保留的设计 | 通用性、优雅性、扩展性及改进建议 |
|---|---|---|
| `mcp/__init__.py` | 小型公共导出，模块职责说明清楚 | 保持轻量；无需增加全局连接注册器 |
| `config.py` | 配置与运行状态分离，支持多种文档布局、工具过滤、lazy/on_focus | `_server_from_raw` 用 bool/float 强转，字符串 false 会变真，负数/非有限超时没有领域验证；未知 transport 静默回退。建议明确拒绝错误值，但保留旧布局兼容 |
| `store.py` | 原子 JSON 写、保留现有布局、配置和状态快照集中 | 读改写缺少并发保护，见 M08。配置快照和实际连接状态应继续区分，不能把有目录缓存等同于在线 |
| `actions.py` | CLI/TUI 复用配置命令结果，业务包装薄 | 依赖 store 的一致性。`http`/`sse` 添加都只保存 URL，未持久化明确 transport；当前无 hint 的 URL 选 SSE，命令命名容易让用户误解。建议明确输入/保存语义并加往返测试 |
| `transport.py` | stdio、SSE、Streamable HTTP 各自实现；SSE endpoint 同源检查与禁重定向；子进程环境过滤、持续读 stderr | 三种传输的时限、关闭和帧大小契约不一致，见 M03—M05。保留已有同源与凭据保护，不为了“兼容”放宽 |
| `client.py` | JSON-RPC request ID/pending 映射，reader 死亡会通知等待者，握手失败清理 | 取消和发送阶段未闭合，见 M03；分页见 M06。握手版本、result 顶层类型、服务器请求/通知处理仍需明确支持范围 |
| `manager.py` | 并行发现、required 启动检查、渐进目录、focus、真实 raw name 映射 | 连接/发现/预热/缓存状态集中在约 1158 行中；M01/M02/M07 的状态交叉最值得先修。修稳后可按连接生命周期与目录快照拆分，不宜现在只按行数拆文件 |
| `execute.py` | 将文字/图片/资源转为 ToolResult；图片解码有大小检查；参数错误带 schema 提示 | 入站块验证不完整：text 非字符串、resource=null 可让转换器抛类型异常；structuredContent 与可读 content 的保留策略不明确。建议先定义结果归一化契约，避免每个工具消费者补判断 |
| `schema_hints.py` | 纯函数、输出上限、有限字段保留，不依赖服务连接 | 关键字启发式可能误判；截断后的 JSON 片段只适合作为提示，不应当作可解析 schema。现有文字已提醒“不完整”，值得保留；大嵌套对象仍先完整序列化再截断 |
| `tools/mcp.py` | resource 桥接入口小，参数验证和权限声明集中 | list_resources 通过 manager 枚举所有配置，必须服从 disabled 状态（M01）。read_resource 的 URI 来源约束目前主要靠说明，后续若有产品限制应在代码中定义，不能把提示文字当授权校验 |

整体架构具备通用基础：新增 transport 不需要重写工具执行，真实原名映射避免靠字符串猜回名称。问题集中在“谁拥有任务、谁有权发布结果、哪个配置版本可以调用”，而非缺少更多接口或设计模式。

## 2. 重点发现与方案比较

### M01 · P1：服务器禁用后旧映射仍能调用，资源枚举也会连接禁用项

位置：[call_tool/_ensure_client](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:1065)、[重载](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:637)、[_collect](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:1100)。

发现阶段过滤 enabled，但执行入口 `_ensure_client` 没有检查它。stop_all 清 live map，却保留 cached map；reload 后旧名称仍可由 cached map 解析，再创建 disabled 配置对应的客户端。无 server 参数的资源枚举直接遍历全部配置，也没有 enabled 过滤。

**真实 manager + 假客户端复现：**先发现工具，把临时配置设为 enabled=false，再调用真实 reload；旧 qualified 工具仍返回结果，list_resources 仍返回该服务器一个资源。没有执行外部命令或远程调用。这说明配置禁用未成为执行约束，不等于已证明绕过系统其余审批层。

推荐：在连接和调用边界检查当前配置；禁用/删除/工具过滤变化时让相关目录和映射立即失效。旧目录可以用于展示，但不能直接充当可调用授权。另一方案是每次调用完整重发现，简单却增加延迟，而且发现与执行之间仍可能发生配置变化；应优先采用配置版本绑定。

验收：禁用后旧模型名称、资源 list/read、工具 allow/deny 变化、服务器删除与重命名；并发 reload 和调用时定义旧请求可否完成、新请求必须遵守哪一版配置。

### M02 · P1：连接缺少同服务器并发合并，关闭也没有覆盖全部发现任务

位置：[_ensure_client](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:1080)、[discover_tools](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:852)、[stop_all](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:609)。

`_ensure_client` 在 await start 之后才写入 `_clients`。两个调用同时进入时，都能创建客户端，后写覆盖前写。探针用事件屏障使两个 start 同时等待：最终返回 **两个不同对象**，manager.stop_all 之后仍有 **一个替身处于 running 状态**。对真实 stdio 这意味着潜在未托管子进程，探针没有真的启动两个子进程来宣称 OS 级泄漏测量。

发现流程虽然有共享 task，但 stop_all 没有取消 `_discover_inflight`；外部调用者取消也因 shield 不会停止该任务。受控发现协程通过真实 discover_tools/stop_all 流程，在 stop 返回后仍能提交缓存。这里验证的是管理器未拥有完整任务生命周期，缓存发布由替身模拟，生产 `_discover_tools_fresh` 同样在异步阶段后写入缓存。

方案比较：

1. 一个全局锁：容易实现，但慢服务器会阻塞其他独立连接。
2. **推荐：每服务器共享连接任务或锁，配合管理器关闭状态/配置代次。** 所有背景任务登记、关闭时取消并等待；过时代次不得发布连接和目录。新连接成功前若已关闭，应立即销毁。
3. 引入完整 actor 框架：所有权可清楚，但当前体量没有必要先引入新运行框架。

验收：同服并发只创建一次、不同服务器仍并行、取消一个等待者不误杀其他等待者、stop 等待所有托管任务、reload 后旧任务不能覆盖新缓存、失败连接能重试且不会泄漏。

### M03 · P1：RPC 超时不覆盖 send，取消和部分发送异常会遗留 pending

位置：[_send_request](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/client.py:313)、[transport send](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py:476)。

pending 先登记，接着 await transport.send，最后才 `wait_for(fut, timeout)`。因此 execute/read_timeout 不约束发送阶段；在 HTTP transport 中 send 又包含等待整个响应体。探针设置 1ms 超时，让 send 阻塞 20ms，请求仍未结束，释放后还能返回成功。

删除 pending 只覆盖 McpTransportError 和等待超时，外部 CancelledError、httpx 异常等路径没有统一 finally。对一个已发出的请求取消，pending 长度仍为 **1**；若对端迟迟无响应，它会留到后续断线/关闭。

推荐统一 deadline 覆盖发送与等待，finally 负责清除本次 ID 并取消未完成 Future，传输异常统一转为 McpError。取消是否向服务端发送通知需单独定义；本地取消并不能撤销外部工具已发生的副作用，不能自动重放写操作来“恢复”。

分开 send_timeout/read_timeout 也是方案，但配置和组合语义更复杂；先让现有 execute_timeout 真正约束整次 RPC。验收要覆盖 send 阻塞、发送中取消、等待中取消、迟到响应、断线与多请求并发。

### M04 · P1：Streamable HTTP 的 SSE 分支先收完整响应体，再交付结果

位置：[StreamableHttpTransport.send](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py:476)。

实现使用 `AsyncClient.post()`，读取完整 response 后再遍历 `response.text` 的 SSE 帧。即使第一帧已经包含请求的 JSON-RPC result，也要等 HTTP body EOF 才入队。探针使用真实 httpx client + 可控 AsyncByteStream：首个完整 result 帧已发出但暂不关闭 body 时，接收队列仍为空；关闭 body 后才拿到结果。

这既影响长连接兼容性，也让大响应先整体驻留内存；不是泛指所有 HTTP 请求都会失败。现有有限 JSON/SSE 响应测试仍能通过。

推荐用 httpx 流式响应、逐事件解析并尽早交付，HTTP 响应 reader 的归属和取消必须一起设计。一个更小的方案是明确仅支持有限响应并设严格体积/时限，但它会保留“等待 EOF”的功能限制，不应继续以一般流式支持描述。

验收：结果后连接保持打开、多个帧/多行 data、网络中断、取消清理、单帧和队列容量。不要只将 post 换成 stream 而留下未托管 reader。

### M05 · P2：stdio 默认行限制与较大工具结果/图片支持不匹配

位置：[StdioTransport.start](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py:142)、[recv](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py:237)、[stderr drain](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/transport.py:180)。

create_subprocess_exec 没有显式配置 StreamReader limit，stdout/stderr 都使用 readline。用同默认配置的真实内存 StreamReader 输入约 70KB 合法单行 JSON，调用 transport.recv 得到 **ValueError**；它会在更上层使 client 被标记死亡，而不是完成较大工具结果读取。execute 层支持图片并不意味着 transport 能把对应 base64 帧读进来。

stderr 若输出无换行超长内容，readline 同样可失败；当前 catch 之后退出 drain，后续子进程持续写日志可能填满管道。这一后续阻塞属于静态推断，本轮没有做真实进程死锁实验。

推荐设置明确的有界消息大小，并给超限错误清楚诊断；stderr 用分块持续排空，只保留有限尾部。直接提高全局 limit 改动小，但无法处理无换行日志和任意大帧；完全取消上限会引入内存风险。

### M06 · P2：工具/资源发现只读取第一页

位置：[list_tools](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/client.py:220)、[list_resources](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/client.py:245)。

两处均执行一次 list RPC，没有处理返回的 nextCursor。探针给 tools/list 返回 first 和 nextCursor=page-2，真实 list_tools 只调用一次，返回名称列表只有 first。资源方法具有同样代码结构，本轮未另作资源分页复现。

推荐共享一个小型分页迭代辅助函数，由各 list 方法负责结果模型转换；终止于无 cursor，并对重复 cursor、异常页和取消设边界。也可以在工具层把 cursor 交给调用者，但现有 discover_tools 的“完整目录”契约就必须改变，不能悄悄只展示第一页。

验收：两页、空第一页但仍有 cursor、重复 cursor、分页中失败和取消；不能把部分目录缓存为完整成功而不记录状态。

### M07 · P2：名称正规化碰撞后采用后者覆盖，路由取决于发现顺序

位置：[qualify_tool_name](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/client.py:30)、[发现合并](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/manager.py:948)。

server/tool 都转小写，并将多种符号替为下划线。`do-thing` 和 `do_thing` 得到同名。真实发现流程对两个 descriptor 只产生 **一个目录项**，映射指向后者 do_thing。现有 warning 和去重避免了重复 schema，但没有解决语义碰撞；同一个模型名仍可能因配置/发现顺序变化代表另一工具。

方案：检测碰撞时拒绝该组并提供诊断；或采用包含原始二元组摘要的稳定名称，保留明确 map。推荐先失败关闭消除错误路由，再评估名称迁移和旧历史兼容。单纯把截断后的名字加 hash 不够，因为当前短名在正规化阶段已经丢失区别。

验收：大小写、标点、Unicode、长名称、服务器名碰撞，以及逐步发现/focus 合并/后台重试的同一规则。不能只修 fresh discovery 的一条合并分支。

### M08 · P2：配置原子写不等于读改写事务，并发添加会丢更新

位置：[add_server_config](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/store.py:99)、[save_document](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/mcp/store.py:68)。

两个线程先读取相同配置，再各自添加一个服务器，最后分别 atomic replace。受控屏障让两次读取同时完成，最终配置只有 **一个服务器**。文件仍是完整 JSON，但一次成功返回的添加丢失了。

推荐先用进程内锁覆盖读改写，适用于同一 App 内多个入口；若 CLI 和 GUI 同时编辑也是支持场景，再采用跨进程锁或版本比较重试。写入前只比较一次 mtime 仍有竞争窗口。锁文件也必须有可靠释放/异常路径，不能为了一个小配置文件先引入数据库。

验收：并发添加不同项、添加与禁用、删除与更新、保存失败保留原件；明确不同进程和外部手工编辑是否受协调。

## 3. 架构与性能的下一步

推荐先实现连接所有权和配置代次，再拆 manager。一个合适的边界是“负责建立/关闭单服连接的组件”与“负责发现并发布目录快照的组件”；前者不直接改 catalog，后者不能绕过 enabled/filter 去建立连接。当前 factory/transport 已足够独立，不需要换成完全不同的框架才能完成上述修复。

保留服务器间并行发现；同服务器并发合并有助于避免重复握手和进程。资源 `_collect` 目前按服务器串行，很多慢服务会累加时延；应先修单次截止时间，再考虑有并发上限的 gather，并保留部分失败信息。无上限地把所有请求并行化只会放大连接和排队成本。

缓存目前对调用者仅复制外层 list，嵌套 schema 仍共享；作为后续小型改进可采用只读快照或边界拷贝。同时，工具变更通知在 client 中被忽略、config reload 以 mtime 快速判断、背景发现有自己的时限下限，都需与“何时目录可以过期”统一说明。这些是静态扩展性建议，不计入已复现的八项问题。

## 4. 验证、优先级与覆盖边界

[离线探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/mcp_probe.py) · [结果 JSON](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/mcp-probe-results.json)

运行：`PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/mcp_probe.py`。连接竞争和配置写入使用受控屏障；RPC send 使用事件控制；HTTP SSE 使用真实 httpx 流读取加 MockTransport；stdio 使用默认内存 StreamReader。测试数据不包含用户真实配置和令牌。

现有 MCP 相关测试 **77 passed**，包括工具名称映射、focus、状态、资源缺失降级、预加载、SSE 同源、HTTP mock，以及本地 Python stdio fixture 的集成测试。通过现有用例与发现上述边界缺陷并不矛盾；探针用于补充并发/分页/大帧等缺失情形，不是认可缺陷行为的回归测试。

建议顺序：**M01 禁用与路由失效 → M02 连接/关闭所有权 → M03 截止时间与取消 → M04 HTTP 流式读取 → M05 大帧 → M06 分页 → M07 稳定名称 → M08 配置事务**。M02/M03/M04 相互依赖，宜一组设计、分步验证；其余可独立实施。

本篇完成上述 10 模块的核心审核，没有核验最新 MCP 规范的全部版本差异，也不宣称所有商业 MCP 服务已验证兼容。插件权限声明、Skill 与 LSP 的独立审核留到下一篇：**插件、Skill 加载与 LSP 生命周期**。
