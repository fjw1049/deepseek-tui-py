# 08 · 状态、上下文持久化与媒体审核

基线：2026-09-27 当前工作区，接续 [Goal 优化](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-implemented-fixes.md)。按“输入进入 → 本地展开/媒体入库 → 存储 → 恢复 → 请求投影”审核 state/ 的 5 个模块与 media.py，共 6 个 Python 文件；追踪 TUI 恢复、通用原子写与客户端媒体投影，关联 Server 全量存储事务另属 Server 篇。

**结论：保留内容寻址媒体和结构化输入展开，优先补齐存储身份、并发写入与边界验证。** 原子替换可以避免半份 JSON，却不能解决不同会话写到同一路径；文件数量/字节预算存在，也不意味着每条展开分支都执行了预算。

本篇保留修复前审核基线。S01—S07 的实施状态、测试与剩余边界见 [第八篇修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-implemented-fixes.md)。历史探针使用临时目录、合成图片和假密钥，结果不代表修复后行为。

## 1. 应保留的设计

| 维度 | 当前优点 | 改进方向 |
|---|---|---|
| 通用性 | ContextConfig 集中输入预算；display_text/model_text 分开；ImageBlock 使用稳定引用 | 不同展开分支统一遵守预算和失败契约；把恢复身份从全局路径中解耦 |
| 优雅性 | state 模块按职责拆分，小型导出层没有复杂框架；媒体解码/原件/投影分离 | secrets 的文本替换低估了 TOML 语法；使用解析结果维护正确性 |
| 可扩展性 | 图片原件不塞进历史，裁剪/缩放可重建；媒体数据按内容寻址 | 请求内复用变体，明确生命周期、缺失文件和新增格式策略 |
| 架构合理性 | 普通文本与属性转义、workspace resolve 边界、原子写已具备 | checkpoint 要核对会话/工作区；原子性、持久性、并发隔离分别定义 |
| 性能 | 文件读取有单体上限、图片有字节/像素上限 | 目录先全量排序再取前 N；媒体预算和序列化重复编码 |

值得保留的具体保护：@mention 解析后核对工作区边界；用户内容中的伪 system-reminder 标签会被中和；媒体原件按 SHA-256 存放，读取时验证完整性；解码拒绝损坏、过大像素与动画；原子文本写使用同目录临时文件、flush/fsync、replace。不要为统一代码而删掉这些边界。

## 2. 当前发现与方案比较

### S01 · P1：全局 checkpoint 与无身份恢复可把 A 工作区历史放进 B 工作区

位置：[state/session.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/session.py:15)、[TUI 恢复入口](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/session_restore.py:63)、[Engine checkpoint 写入](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/maintenance.py:99)。

所有会话使用用户目录中的 checkpoints/latest.json。写入 payload 虽带 workspace/id，恢复函数却不比较当前 engine 工作目录，直接装入 messages。探针保存 workspace-a 的消息，再向工作目录为 workspace-b 的引擎替身调用真实恢复函数，返回成功。

证据等级：真实存取与恢复函数离线复现；未操作桌面恢复按钮，不声称每次启动都会自动触发。风险是恢复后旧任务上下文与当前工具工作区不一致；另一个会话的保存/清除也会覆盖这个全局槽位。atomic replace 只能保证文件完整，不能解决身份串用。

方案：

1. 保留 latest，但恢复前校验工作区并显示来源；改动小，仍只有一个恢复槽位。
2. 以 session_id 分文件，记录 workspace 身份，latest 仅作指针；**推荐**。恢复必须显式选择相符对象，清除也按身份。
3. 全部并入 RuntimeThreadStore；长期有利于单一事实源，但涉及 Server/CLI/TUI 的迁移，不能在本篇随手替换。

验收：两个工作区交替写入与清除、同工作区两个会话、错误工作区恢复拒绝、旧 latest 迁移。第六篇提出的原始请求存档应在这个身份模型确定后统一落地。

### S02 · P2：checkpoint 没有验证顶层形状，写入版本还能被 payload 覆盖

位置：[save_checkpoint/load_checkpoint](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/session.py:19)。

`{"schema_version": current, **payload}` 允许调用者覆盖版本。探针传 999，落盘即为 999，随后当前 loader 反而不能读取自身写出的文件。另一探针把合法 JSON 数组 `[]` 写入文件，loader 调用 raw.get 抛 AttributeError；TUI 只捕获 OSError/ValueError，因此该异常逃出恢复入口。

建议先验证 dict、版本类型和消息/metadata 基础形状，再做迁移；由存储层最终设置 schema_version。损坏数据应给出可诊断失败并保留原文件，不能静默清空。给 JSON 读取设置合理体积上限，避免异常文件在验证前占用无限内存。

本项并非远程代码执行或密钥泄露；它是本地持久化格式和恢复容错缺陷。Future-version 拒绝已有基础，需与合法旧格式迁移区分。

### S03 · P1：粘贴文件用 exists 再 write，并发可覆盖原始输入

位置：[paste_file.write_paste_txt](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/paste_file.py:27)。

文件名精度为秒；碰撞用 exists 循环加序号，最后普通 write_text。两个写入者在检查后同时继续，都可选择同一路径。探针固定时钟，并在存在性检查处设置双线程屏障，两份不同文本最终返回的唯一文件路径数量是 **1**，至少一份内容被覆盖。

推荐用独占创建（open 的 x 模式）在冲突时重试，或使用系统安全临时文件创建再返回路径。只增加时间戳精度不能构成并发保证。验收必须用受控屏障，不能只连续调用两次后看到不同文件名就认为并发安全。

这里只在临时目录制造竞争，没有覆盖用户文件。

### S04 · P2：目录展开没有检查总预算，封套/转义也不计入现有计数

位置：[context.process_turn_input 的 directory 分支](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/context.py:136)、[_list_directory](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/context.py:465)。

文本文件在加入前检查 max_total_inline_bytes，目录则直接累加并加入。探针设置总预算 20 字节，三个长文件名生成 **221 字节**目录正文，仍全部展开。实际默认阈值更大，但文本已接近预算后再接目录，同样可越界。

另外当前 bytes_inlined 统计原始正文，不包含 XML 转义扩张和封套。若该字段意图只是“原始内容预算”，需明确命名；若用于最终模型请求预算，就应在渲染后验收整个新增块。

推荐让所有分支先生成候选，再走一次统一预算判定；不足时转 reference，保留用户原文。目录虽然只显示前 80 项，却先列出并排序全部内容，超大目录仍有 O(N log N) 工作；如果不需要准确剩余数量，可考虑有界采样/选择，但不要没有测量就增加全局目录缓存。

### S05 · P1：手写 TOML 表头匹配会把合法配置改成不可解析配置

位置：[secrets._update_section_value](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/secrets.py:164)、[write_api_key](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/secrets.py:73)。

合法表头 `[providers . deepseek]` 与 `[providers.deepseek]` 语义等价，代码却用原始字符串比较。探针先用 tomllib 成功解析含空格表头的配置，再写入假密钥；函数新增第二个同义表，最终 tomllib 拒绝重复声明。原子写会完整替换为这份无效配置，并不能保证语法正确。

方案：

1. 写入前后用 tomllib 验证，至少保证失败不替换原文件；**应先做的保护**，但它不会解决如何更新已有语义等价键。
2. 使用保留注释的 TOML 语法树修改；更适合用户维护的配置，需核对依赖和格式保持行为。
3. 解析后整体重写标准 TOML；实现简单，但会丢注释和布局，必须明确产品取舍。

还应测试引号 key、多行字符串、重复赋值、嵌套表与并发设置更新。API key 分 provider 解析和环境变量优先级值得保留；本探针仅使用 fake-old/fake-new，没有触碰真实密钥。

### S06 · P2：同张图片在预算计算与请求序列化中重复解码、缩放和编码

位置：[media.image_data_url](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/media.py:84)、[客户端媒体预算](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/media.py:21)、[Chat 消息投影](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/chat_messages.py:21)。

image_data_url 每次都读原件、检查 SHA、解码、裁剪、缩放、编码。预算阶段调用它只是取字符串长度；序列化阶段又调用一次。探针用同一真实 ImageBlock 依次执行预算和消息投影，编码入口被调用 **2 次**。多轮重复图片会反复付出同样成本。

推荐请求内准备一次媒体变体，预算读取真实字节数，序列化复用同一份结果。键至少包含 asset_id、crop、max_side 与编码策略版本。先做请求内缓存，避免长生命周期缓存的容量、缺失文件、完整性检查和清理问题。

这里证明重复工作，没有测得整个模型请求的加速比例。PNG 超过 2MiB 后切 JPEG 是策略阈值，不是最终文件必然小于 2MiB；客户端另有总请求预算，不把该阈值误报为无保护的网络溢出。

### S07 · P2：图片分类后读取失败，没有转换成可恢复的展开结果

位置：[context 媒体展开](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/context.py:151)、[media.import_image_path](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/media.py:79)。

图片分支只捕获 ValueError；文件从检测到打开之间被删除或权限变化时，会抛 OSError/子类。探针在真实 process_turn_input 的图片读取边界注入 FileNotFoundError，异常向外传播。文本路径也在 try 外调用 stat，存在类似竞态窗口。

建议把分类后的 stat/open/read 视为同一个可能失败的输入阶段，转换成 missing/unreadable reference 与明确警告，保留用户原始提问。路径先 resolve 再打开仍存在文件系统变化窗口，不能宣称这是对恶意并发文件替换的完整防护。

证据等级：故障注入，不是实际测量用户删文件的发生频率；不因此推断整个桌面进程必然退出。

## 3. 逐模块结论

| 模块 | 审核结论与建议 |
|---|---|
| state/__init__.py | 四个 checkpoint API 的显式导出足够，不需要注册器或插件机制 |
| state/session.py | 小接口易测；优先 S01/S02。原子替换之外应明确身份、格式、恢复失败和并发语义，避免把 legacy checkpoint 宣传成完整会话数据库 |
| state/context.py | 用户正文/附加内容分层、工作区边界、转义合理；优先 S04/S07。把预算与读取失败统一到各类 reference，保持解析函数可独立测试 |
| state/paste_file.py | 大粘贴转文件再 @mention 能复用现有读取链路；优先 S03。后续明确保留和清理策略，清理时不要删除仍被会话引用的原始输入 |
| state/secrets.py | 不同 provider 的凭据解析边界合理；优先 S05。用解析后的语义保证更新正确，不继续给行级正则叠加全部 TOML 语法 |
| media.py | 原件寻址、校验、EXIF 方向和尺寸保护应保留；优先 S06 的请求内复用。_write_atomic 有 replace 但无 fsync，语义是原子可见，不等同于断电耐久；与完整性检查、媒体缺失恢复一起定义 |

跨模块仍需后续审核：Server 的线程/turn/item 事务、媒体回收引用关系、配置 UI 的并发更新、客户端辅助视觉模型失败处理。此次追踪相关调用点，不把这些体系整体标为完成。

## 4. 取证、验证与实施顺序

[探针脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/state_probe.py) · [结果数据](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/state-probe-results.json)。运行：`PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/state_probe.py`。

探针使用真实存取/展开/媒体投影函数；并发粘贴用屏障控制时序，图片消失用异常注入。输出描绘当前缺陷，不是“这些功能验收通过”。全部写入均在临时目录，未请求模型或网络。

本轮 Goal 修复及状态相关测试 **408 passed**；运行范围见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-validation.json)。既有测试通过不能覆盖上述新发现，没有据此宣称全仓或桌面发布就绪。

建议顺序：S01 身份隔离 + S03 并发输入保护 + S05 配置有效性 → S02/S07 恢复容错 → S04 统一预算 → S06 请求内媒体复用。下一审核体系：**模型客户端与流式协议**；先按本篇修复，再继续逐模块推进。
