# 第十一篇：插件、Skill 与 LSP

日期：2026-09-27。基线：当前工作区，接续第十篇 MCP 修复。**本篇仅审核与离线取证，以下问题尚未修复。**

## 结论与范围

插件已经具备内容寻址存储、适配器、授权记录、会话视图和延迟激活的雏形，方向合理。主要问题是这些层还没有共享同一份经过验证的身份与贡献模型：检查器、旧加载器、授权系统各自解释路径与内容，造成检查结果、实际加载和授权判断不一致。优先修复身份和生命周期边界，再缩小旧加载器职责；现在整体重写风险较大。

本篇覆盖索引列出的 19 个 Python 模块，沿“来源 → 检查 → 安装 → 摘要/授权 → 会话激活 → Skill/LSP 使用”追踪核心路径。逐文件意见见末尾台账。CLI/HTTP/TUI 的全部输入验证、操作系统级隔离、真实远程服务兼容性不属于本篇完成范围；不能据此宣称所有入口均可利用，或整个项目已经审核完成。

证据分为 **A：离线探针复现**、**B：代码路径确认，未作端到端或压力复现**、**C：设计建议**。探针全部使用临时目录、模拟 transport 和本地构造的数据，不安装真实插件，不执行插件命令，不访问网络。

[可重跑探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/plugins_probe.py) · [实际结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/plugins-probe-results.json)

```sh
PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/plugins_probe.py
```

## P01 · P1：摘要输入没有文件边界，不同文件树可以产生同一摘要（A）

位置：[source.py:40](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/source.py:40)。`LocalArtifact._digest` 直接串联相对路径与文件内容，没有记录长度、分隔符或条目类型。文件 `a` 内容 `bc` 与文件 `ab` 内容 `c` 都把相同的 `abc` 输入 SHA-256。探针确认两个不同目录的摘要相等；这不是 SHA-256 本身发生碰撞。

摘要同时用作源存储键与授权键，因此这个编码歧义破坏“相同摘要表示相同文件树”的前提。相同的公共 manifest 加上上述不同条目仍能产生相同摘要；不能仅依赖插件名来弥补。

建议采用带版本、条目类型、路径字节长度、内容长度的规范编码，再逐块散列内容。另一方案是每文件内容先散列，再对规范化清单散列，便于增量校验但多一层格式。首轮优先前者。不能直接让旧摘要授权自动迁移到新格式：旧键的绑定本来就不唯一，应显式重新确认授权。

验收：上述两棵树摘要必须不同；遍历顺序不影响结果；对文件名中的换行、Unicode、文件边界组合均不混淆；旧格式存储和 grant 的迁移有明确策略。

## P02 · P1：运行时把路径中的摘要当作可信身份（A）

位置：[plugins.py:1128](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py:1128)、[identity.py:83](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/identity.py:83)、[store.py:36](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/store.py:36)。`_store_path_digest` 只要看到符号链接目标路径含 `sha256/<值>` 就取出该值，没有要求目标位于应用自己的源存储，更没有验证实际内容。项目信任查询另会优先接受项目 provenance 中声明的摘要。

探针先在隔离 home 写入测试授权，再让项目插件链接到任意临时目录下的 `sources/sha256/<已有摘要>`。实际内容摘要不同，但项目信任查询返回真，运行时摘要仍匹配旧授权，并收集到 Hook。此处仅验证加载/授权链，没有运行 Hook；触发需要同插件 ID 的已有 home 授权。

真正的存储也不是文件系统意义上的不可变目录：探针修改已发布文件后，再次发布原源，`publish_source_tree` 在 `dest.is_dir()` 分支直接复用损坏条目，返回的摘要与实际内容不符。

建议最小修复同时做两件事：存储路径必须属于规范化后的应用存储根；在授权/复用边界校验实际内容摘要。只检查目录名或者设置只读权限不够。之后可用经过校验的进程内快照降低重复散列成本，但缓存失效规则必须独立于不可信 provenance。对已有可变文件和并发修改仍需明确校验到执行之间的边界。

验收：任意外部 `sha256` 目录不能继承授权；被修改的真实存储条目不能被静默复用；grant 绑定的摘要必须来自校验结果，而非项目 lockfile 的声明。

## P03 · P1：Hook 和 MCP 授权没有分别执行（A）

位置：[plugins.py:1167](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py:1167)。当前逻辑只在 `hooks.execute` 和 `mcp.connect` **两者都没有**时跳过插件；任意一种存在都会继续执行 `_collect_hooks` 和 `_collect_mcp`。

探针只授权 `hooks.execute`，却得到 1 个 Hook 和 1 个 MCP server。细分 capability 的 API 已存在，因此这不是单纯命名问题。

建议在每类贡献收集前分别判断能力；将“是否信任这个内容版本”和“可使用哪类能力”保留为两个不同判断。替代方案是合并成单一执行授权，但会失去当前 API 已承诺的细粒度控制，不推荐。`process.spawn` 与 hooks/MCP 的关系也应明确定义：适配器把它列为权限声明，运行时却主要检查后两者，不能让 UI 文案暗示额外限制已经强制实施。

验收：分别仅授权 Hook、仅授权 MCP、两者都授权、都不授权的四格测试；其中任何一个分支的授权都不能扩大另一分支。

## P04 · P1：撤销最后一份授权后，下一次加载会补回（A）

位置：[plugins.py:1208](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py:1208)、[host.py:361](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/host.py:361)。`RevokePlugin` 删除 grant，不同步清除旧 trusted 状态；`collect_light_contributions` 对非 project、trusted 且没有 grant 文件的插件调用 `grant_trust`，将其解释为旧版本迁移。

探针撤销 `fixture` 的所有授权后再次收集贡献，授权文件重新出现。普通撤销与“从未迁移”没有可区分的状态。已经存在的会话缓存还涉及撤销何时生效的问题，需要明确是即时还是下次会话。

建议移除运行时自动补授权，把兼容迁移放到显式版本迁移中，并记录完成状态或撤销标记。仅在 revoke 时设置 trusted=false 是较小补丁，但不足以处理旧会话中捕获的 trusted 对象。首轮至少保证再次加载绝不会重新发放已撤销授权。

验收：grant → revoke → 新加载、旧会话刷新、进程重启均保持拒绝；迁移流程不能覆盖撤销意图。

## P05 · P1：Skill 更新先删后装；本地来源还不能往返解析（A）

位置：[skills.py:966](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/skills.py:966)。GitHub Skill 更新先 `rmtree(skill_path)`，才开始重新安装。探针使用已有 Skill 和模拟下载失败，结果为 `failed`，旧安装已不存在。

同一探针通过公开 install 正常安装本地 Skill，再调用 update，返回 `Cannot parse stored spec`：安装记录写 `local:<路径>`，`InstallSource.parse` 只识别裸目录路径。插件安装的旧加载器已经修过这个往返问题，Skill 路径仍保留旧实现。

建议先在唯一 staging 目录安装并验证，再替换 live；替换失败恢复旧版本。源记录使用有版本的结构或规范化绝对路径，并兼容已有 `local:` 记录。不要为了复用而把整个插件宿主嵌入 Skill 安装器；可以复用一个边界明确的目录发布步骤。更新后直接沿用 `.trusted` 的行为也需明确内容版本语义，本篇尚未证明它绕过独立执行器。

验收：下载失败、缺少 SKILL.md、替换失败均保留旧版；本地安装后从不同 cwd 更新成功；并发更新不能共享并删除同一个 staging。

## P06 · P1：Skill 名称直接参与写入与删除路径（A/B）

位置：[skills.py:619](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/skills.py:619)、[skills.py:950](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/skills.py:950)。`name_override` 和 uninstall/update/trust 的 name 都直接拼到目标目录，没有统一的单段名称校验与根目录约束。

A 级探针仅在临时目录调用 install，`name_override='../outside'` 成功写出 skills 根目录。删除/更新入口的同类路径由代码确认（B），未对任何真实目录做删除测试。这里只证明库 API 缺少边界，外部 CLI/HTTP 是否另有过滤需在其篇章追踪。

建议集中使用安全的名称解析，拒绝绝对路径、父目录、分隔符，并验证解析后的目标仍在指定根下；管理已有符号链接时明确“操作链接”还是“跟随目标”。复用插件 ID 验证前先检查历史 Skill 名称兼容性，避免顺手改变显示名称规则。

验收：install/update/uninstall/trust 四个 API 都覆盖非法名称和符号链接；拒绝时不在根外创建、修改或删除文件。

## P07 · P1：LSP 启动与请求缺乏完整生命周期边界（A/B）

位置：[lsp.py:285](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/lsp.py:285)、[lsp.py:490](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/lsp.py:490)。同一语言并发 `_get_or_spawn_client` 没有共享启动任务；探针两个调用创建 2 个 client，manager 最后只持有 1 个。模拟 client 不启动进程，但真实实现采用同一路径，另一进程缺少 owner 清理的风险由代码确认。

请求注册 `_pending` 后没有 `finally` 移除；探针取消请求后仍留 1 项。初始化等待没有 deadline，transport 发送也不受 `poll_after_edit_ms` 约束；该参数只限制发送完成后的诊断等待。服务器启动却不回答 initialize 会阻塞编辑后的诊断流程（B）。失败启动不主动关闭已创建 client，损坏 reader 的 close 也可能跳过 transport 关闭。

建议保留现有轻量实现，增加每语言共享启动任务、完整请求期限、finally 清理、失败回收与 stop 的任务排空。独立语言继续并发，不要用全局锁串行化所有语言。不要把整个 McpManager 继承过来；两者共享生命周期原则即可。

验收：同语言并发只创建一次、不同语言可同时启动、初始化不响应有界退出、取消无 pending 残留、关闭后不出现晚到 client；连接断开后能按明确策略重新建立。

## P08 · P2：LSP 文档身份和诊断版本不可靠（A/B）

位置：[lsp.py:338](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/lsp.py:338)。收到 URI 时仅去掉 `file://`，发送时直接拼字符串。含空格的文件以合法百分号编码 URI 发布诊断后，探针取回 0 条。非 ASCII、Windows 路径和 URI authority 也需要统一处理，未在这些平台运行测试。

同一函数忽略 publishDiagnostics.version。探针本地文档已是版本 3，发布版本 1 仍覆盖缓存并设置事件；并发编辑共用一个 Event，可能把旧版诊断当作新版完成。无版本服务器的可靠关联应单独设计，不能声称仅比较版本就支持全部服务器。

建议统一 Path ↔ URI 转换；按文档串行发送版本，丢弃明确落后的发布，并将等待目标与版本绑定。对于不带版本的服务器，保留有界 best-effort 语义并明确限制。无须为此改写整个 LSP 协议栈。

验收：空格/中文路径能往返；乱序 v1/v2 发布不会覆盖 v2；同文档并发编辑和无版本诊断各有明确测试。

## P09 · P1：组合 MCP 管理器仍可发布同名工具并静默选第一个（A）

位置：[runtime.py:36](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/runtime.py:36)、[runtime.py:115](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/runtime.py:115)。第十篇已让单个 McpManager 内部的名称碰撞失败关闭；但 CompositeMcpManager 直接拼接目录，调用时按第一个匹配 server 的 manager 路由。

探针两个独立 provider 都发布 `mcp_shared_run`，合成目录保留 2 条，执行固定选择 provider 0，provider 1 从未被调用。基础配置与插件配置的名称并非强制全局唯一，因此单层修复不能解决组合层冲突。

建议组合时建立经过冲突校验的 `(qualified_name → provider, raw_name)` 路由，与发布目录使用同一来源。最小策略是拒绝冲突并显示所有来源；引入稳定 provider 命名空间更灵活，但会影响已有工具名和上下文缓存，应另做迁移。优先拒绝歧义。

验收：基础配置/插件之间、两个插件之间同名都不被隐式覆盖；展示的 schema 与实际调用的 provider 恒一致；配置移除后旧路由失效。

## P10 · P2：npm 下载上限在读取完响应后才生效（B）

位置：[fetch.py:159](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/fetch.py:159)。元数据和 tarball 使用 `client.get`，取 `archive.content` 后才检查 `max_bytes`，所以不是内存读取上限。元数据自身也没有体积上限。相比之下同模块 GitHub `_download_archive` 已使用流式累计限制，可以复用这一原则。

另外 npm client 的 `follow_redirects=True` 使初始 tarball 主机白名单不能约束后续跳转；Skill 下载也只检查初始候选 URL。此处由代码确认，未向外部主机发请求。解包的 `getmembers()` 则先构造全量成员列表才做数量检查，限制不能完整覆盖解析阶段的内存成本。

建议给元数据和压缩体分别设流式上限；在每次重定向验证目的地，或按来源禁用重定向；按成员迭代并限制成员数与解压后总量。无须三套下载器同时重写，先补 npm，再抽取真正共有的限额逻辑。

验收：模拟无限响应在限额附近停止消费，重定向到非允许主机被拒绝；大量空文件也受成员数上限约束。未做真实内存峰值基准，不能给出吞吐或内存改善百分比。

## P11 · P2：检查器认可的贡献与运行时实际加载不一致（A）

位置：[adapters/common.py:58](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/common.py:58)、[plugins.py:994](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py:994)。适配器递归扫描命令目录，旧运行时只扫描当前层 `*.md`。探针提供显式 commands 目录及一条嵌套命令，inspect 得到 1 条，runtime 得到 0 条。

这比文件过长更能说明架构问题：`DerivedPlugin` 尚不是运行时的唯一贡献来源。名称规则也各有解释，未来每支持一个生态都会增加两套维护成本。

建议先让检查与执行共享贡献路径解析规则，并补上述一致性测试；后续逐类让 runtime 消费验证后的 ContributionSpec。直接把 3200 多行旧文件机械拆成多个文件只能改善阅读，不能消除语义漂移。一次性用 DerivedPlugin 替换所有现有加载逻辑改动面太大，不作为首轮建议。

验收：同一 fixture 的 inspect、索引和 activate 对命令、Skill、Agent、Rule 给出一致的资源集合，unsupported/degraded 状态也不能只存在于检查报告中。

## 逐模块审核文案

下表的“保留”表示本轮核心路径未发现必须立即改变的设计，不表示穷尽所有输入或证明无缺陷。P 编号对应上文确定问题；其余为 C 级建议。

| 模块 | 通用性、边界与维护建议 |
|---|---|
| [integrations/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/__init__.py) | 仅包说明，职责小；保留，不在此加入发现或启动副作用。 |
| [integrations/lsp.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/lsp.py) | 语言注册、传输、请求、诊断与 manager 聚集一处；先修 P07/P08，再按生命周期边界拆分。传输抽象可保留，不必引入插件容器。 |
| [integrations/plugin_compat.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugin_compat.py) | 生态名称映射集中是优点。matcher 仅支持简单 alternation，不是通用正则；应明确受支持语法，不要静默承诺外部生态的全部匹配语义。 |
| [integrations/plugins.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/plugins.py) | 仍承担发现、索引、授权、贡献收集、安装/更新与 marketplace，宿主大量反向调用私有函数。P02/P03/P04/P11 是可观察的边界漂移；优先统一语义，再迁移职责。已具备的 staged update 和失败恢复应保留。 |
| [integrations/skills.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/skills.py) | 来源优先级、无歧义 suffix 查询和提示词预算有价值；P05/P06 必修。发现、渲染、安装可逐步分离，但不改变既有优先级。全文读取与多生态遍历的性能需真实目录规模测量。 |
| [plugins/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/__init__.py) | 稳定操作入口值得保留；逐步让外部调用只依赖此公共接口，减少直接引用 legacy 私有方法。 |
| [plugins/adapters/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/__init__.py) | 薄导出层合理，保留。 |
| [plugins/adapters/bare_skill.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/bare_skill.py) | 单 Skill 适配器结构简单；身份校验与路径验证应由统一边界完成，避免 inspect 接受的 ID 在安装时才失败。 |
| [plugins/adapters/claude.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/claude.py) | 集中声明贡献和兼容性报告有利扩展；P11 暴露其解释与 runtime 分离。声明 process.spawn 与实际 capability gate 的对应关系需统一。 |
| [plugins/adapters/common.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/common.py) | 路径约束、JSON 类型校验有复用价值。markdown 枚举递归深度与 runtime 不同（P11）；资源遍历和解析预算应共用。 |
| [plugins/adapters/registry.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/adapters/registry.py) | 按 probe 分数选择、隔离单候选失败、报告 ID 碰撞合理。当前两个适配器无需动态注册框架；增加第三个时再规定同分行为和协议类型。 |
| [plugins/fetch.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/fetch.py) | 来源解析、GitHub 主机约束、临时目录和解压路径检查较清晰；npm 与 GitHub 限额策略不一致（P10），优先统一资源边界。 |
| [plugins/grants.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/grants.py) | 内容摘要与 capability 独立记录是正确基础，但上游 gate 与自动迁移破坏了含义（P03/P04）。grant 文件内容应验证身份字段；空 capability 集合不宜被 truthiness 当作全部授权。此两点属额外静态建议。 |
| [plugins/host.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/host.py) | 显式操作对象与 session 视图有价值；仍大量依赖 legacy Any 和私有函数。修复撤销后的会话状态（P04），明确快照包含内容版本还是仅名称/路径/开关；避免扩大为通用 DI 容器。 |
| [plugins/identity.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/identity.py) | 安全 ID 与路径规则可复用。provenance 声明不能代替内容校验（P02）；mtime/size fingerprint 只可用于可失效缓存，不能承诺安全身份。 |
| [plugins/model.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/model.py) | 模型与诊断可序列化，便于 CLI/HTTP 共享。frozen 外壳仍含可变 dict；如承诺不可变快照，应复制或限制嵌套数据。暂不为单纯类型美观新增抽象。 |
| [plugins/runtime.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/runtime.py) | 组合而不改写底层 provider 是合理方向；继承完整 McpManager 却只覆写部分接口容易产生空基类状态，P09 应先修。后续用小 Protocol 明确路由接口与资源 owner。 |
| [plugins/source.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/source.py) | 来源验证与定位独立，包含文件数/字节数和链接约束，方向正确。摘要编码有 P01；先排序整个 rglob 再检查计数，前置遍历成本并未真正受限，后续可改成有界遍历。 |
| [plugins/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/plugins/store.py) | 内容寻址与安装链接分离利于复用/回退；P02 的“不可变”假设需要落实。rollback 先删除旧链接再创建新链接，不具备完整事务保证；建议复用可恢复替换，并覆盖 GC 与其他 workspace 的引用。 |

## 方案比较与实施顺序

| 方向 | 小步修复 | 更大方案 | 本轮建议 |
|---|---|---|---|
| 摘要与授权 | 规范摘要编码、实际内容校验、逐能力 gate、撤销不自动补回 | 独立内容与授权服务 | 先修正确性，再讨论持久化服务；旧 grant 迁移需单独设计 |
| 插件模型 | 共享贡献定位并做 inspect/runtime 一致性测试 | 全量改为 DerivedPlugin 驱动 | 逐类迁移，避免同时重写安装、授权与执行 |
| Skill 发布 | 唯一 staging + 校验 + 可恢复替换 | 与插件共用完整包管理系统 | 共用小的发布步骤，保留不同产品语义 |
| LSP | 每语言共享启动任务、每文档版本状态、请求 finally | 引入通用 RPC/进程框架 | 先在 LSP 内补生命周期；待第二个稳定使用方出现再抽象 |
| MCP 组合 | 冲突拒绝、单一 provider 路由表 | 新命名空间协议 | 先拒绝歧义，命名迁移另做兼容设计 |

建议顺序：P01–P04 身份与授权 → P05–P06 数据保全与路径边界 → P07–P09 生命周期及路由 → P10 限额 → P11 贡献模型一致性。摘要、授权和存储必须一起验收，不能只修其中一个 helper 就宣布完成。

## 验证与未覆盖边界

本次相关回归集 517 项通过，包含 MCP 修复、插件、Skill、LSP、Engine 及 P1 parity；不是项目全量测试。现有测试通过与本篇探针复现问题可以同时成立，说明对应输入缺少回归覆盖。

首次扩展运行有两项 P0 parity 因前序测试未关闭 runtime 导致 Task 存储锁冲突；两项分别在独立进程/隔离 home 运行均通过。另一个旧测试断言 reload 必须调用 stop_all，已改为验证旧 client 确实关闭、连接池清空，避免绑定内部实现。详细命令与统计见第十篇验证记录。

本篇没有运行真实 npm/GitHub 下载、真实语言服务器或恶意插件代码；没有做跨进程安装/GC 并发、崩溃恢复和多平台基准。锁文件 read-modify-write、固定 staging 名、GC 对其他 workspace 引用的覆盖也值得后续补故障注入，当前不报成已复现结论。索引仍会遍历文件树，Skill 启动仍读全文，需有实际规模数据再决定是否增加缓存，不建议凭文件行数建立复杂框架。

完成本篇修复后的下一体系：**第十二篇：工作区、Git 与变更记录**。
