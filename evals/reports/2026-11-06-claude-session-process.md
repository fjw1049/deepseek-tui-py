# 众安 Flash 历史会话的逐轮复核

范围是上一批相同的 26 个评测会话、38 个用户回合。本次回放留档并重新执行了分类、自动化存储和路由函数的验收。按 transcript 的 keep 和 messages 重建各次请求中的对话前缀，区分原用户输入、助手推断、工具回包和已交付产物。工具次数按留档的调用条目计，合并在一个 Shell 命令里的多步操作仍计一次。没有重新请求模型。

| 同一批任务与复测 | 旧 base | 新 base |
|---|---:|---:|
| 工具调用 | 81 | 91 |
| 标记失败的工具调用 | 3 | 5 |
| 模型轮次 | 85 | 95 |
| 模型累计输入 token，含重复历史 | 2,940,165 | 3,660,356 |
| 去掉压缩说明 HTML 后的工具调用 | 53 | 53 |
| 去掉该题后的累计输入 token | 1,597,661 | 1,605,312 |

累计输入是每轮模型请求相加，受长输入和轮数共同影响，并非一次请求占用的窗口或最终账单。归档记录能还原对话输入；单从这些记录无法拆出系统提示词、工具定义各自的 token 开销。完整原始历史也不等于每次请求都含所有原始内容。新版长 HTML 的五处历史差分中，首个变化都是旧工具回包缩短；保留的用户消息继续可见。样本中的 12 个第二轮请求均沿用上一轮前缀。

**验收复核。** 原分类题，新旧实现对 (F,OTHER，F,PRICE) 均返回 False，却对 (OTHER，F,PRICE) 和 (F，F,PRICE) 返回 True。给样例后的两份实现对三组依次返回 True、False、False。自动化题四份存档代码的实际结果均为 t9/r1=retry 与 t8/r1=elsewhere，没有失败记录和时间。两个架构题产物中的源函数均实际返回 202、404 与 422，并把结果追加到正确键；客户端是否轮询无法由样例验证。

逐场景表里的“多余”表示当时已有足够证据、调用也没有改变下一项判断。复核不因调用次数少就加分，也不因有工具报错就把最终交付判错。表中记录链接指向该试验的对话轨迹。

| 版本和场景 | 模型当时可依据什么 | 工具调用判断 | 最终交付复核 | 调用数 |
|---|---|---|---|---:|
| [旧 label_score](../../scratch/claude-session-ab/old/sessions/claude.label_score-26005570/transcripts/thr_e4963991.jsonl) | 输入给出 F,OTHER 及四个子标签，无样例数据。 | 读了实现并运行自测，但自测按拆开的 F 或 OTHER 造预期。 | 独立验收失败，原样字符串的正例被拒。 | 5 |
| [旧 linux_command](../../scratch/claude-session-ab/old/sessions/claude.linux_command-10ceae56/transcripts/thr_799e607e.jsonl) | 第一问的“当前环境”可解释为本机；第二轮明确要 Linux 指令。 | 第一轮查空间合理，随后列父目录和查磁盘设备帮助有限。第二轮直接回答。 | 总量命令可用；按项的 glob 漏掉 ..cache。 | 3 |
| [旧 cache_evidence](../../scratch/claude-session-ab/old/sessions/claude.cache_evidence-ead25645/transcripts/thr_1b8d9fa2.jsonl) | 三条日志，分别为正值、零和未报告。 | 已知文件名，列目录和文件搜索后才读，直接读取即足够。 | 三条状态区分正确，额外原因作为可能性提出。 | 3 |
| [旧 select_changes](../../scratch/claude-session-ab/old/sessions/claude.select_changes-285f1f3a/transcripts/thr_71f36d13.jsonl) | 只要依据变更清单分组。 | 读取清单合理；另写 commit-groups.md 超出所需交付，虽可逆但无必要。 | 按 hunk 拆分并配对测试，分组可用。 | 4 |
| [旧 git_direction](../../scratch/claude-session-ab/old/sessions/claude.git_direction-40a064cb/transcripts/thr_08ce3d3c.jsonl) | 第一轮只分析，第二轮纠正为远端到本地；输入是快照。 | 先读 refs；在当前目录检查真实 Git 能区分能否执行。两度发现无仓库，后一次证据增量小。 | 说明方向、本地改动和环境限制，没有虚报同步。 | 4 |
| [旧 takeover_history](../../scratch/claude-session-ab/old/sessions/claude.takeover_history-6e0b8a3d/transcripts/thr_9d0908f6.jsonl) | 第二轮保留源码和先前回答。 | 首轮读 handoff.py，追问直接复用源码；无需重读。 | 分清清空旧引用和追加历史。 | 2 |
| [旧 automation_runs](../../scratch/claude-session-ab/old/sessions/claude.automation_runs-76efeb88/transcripts/thr_8906f65c.jsonl) | 源码、事件、第一轮建议均在第二轮请求。 | 所需文件已读；额外列父目录和上一级无助于解释存储。第二轮直接答合理。 | 按现状解释成功覆盖、失败不存、没有时间戳。 | 5 |
| [旧 architecture_html](../../scratch/claude-session-ab/old/sessions/claude.architecture_html-3cb2531a/transcripts/thr_1e32725d.jsonl) | 三个模块能证明按 thread_id 追加，无法证明现场客户端如何收取。 | 沿源码追踪，再用 Chrome 检查 SVG 呈现，有明确用途。 | 交付 HTML 和错误分支；“没有回去的路”把样例外消费者也排除，说得过强。 | 10 |
| [新 linux_command](../../scratch/claude-session-ab/new/sessions/claude.linux_command-25d1f286/transcripts/thr_703e2ac3.jsonl) | 第二轮已有平台纠正。 | 仍重在 macOS 临时空目录跑 du，目录没有隐含的反例，不能检验所给命令的覆盖。 | 同样漏掉 ..cache；裁判另加“必须 Linux 专属”的条件也不合理。 | 2 |
| [新 label_score](../../scratch/claude-session-ab/new/sessions/claude.label_score-4da0b899/transcripts/thr_765ceae4.jsonl) | 同样的业务表述，解释有歧义且直接影响计分。 | 列目录、再搜、又列父目录；多次探索没有解决标签边界，自测沿用同一误读。 | 独立验收失败，还放过了原本不应通过的 F 和 OTHER。 | 7 |
| [新 cache_evidence](../../scratch/claude-session-ab/new/sessions/claude.cache_evidence-fc66efc0/transcripts/thr_982d6990.jsonl) | 前缀摘要相同，日志没有路由或缓存作用域字段。 | 两个列目录操作后才读日志。 | 三条状态答对；断言在同一作用域超出证据。 | 3 |
| [新 select_changes](../../scratch/claude-session-ab/new/sessions/claude.select_changes-1603cc44/transcripts/thr_4ae6d787.jsonl) | 明确只要按清单出方案。 | 读清单并直接交付；额外 Git 状态检查对静态清单帮助小。 | 分组可用，无额外方案文件。 | 3 |
| [新 git_direction](../../scratch/claude-session-ab/new/sessions/claude.git_direction-bf690f2c/transcripts/thr_fa73c8ba.jsonl) | 同样的纠正和快照。 | 本目录核实有价值；随后枚举兄弟试验目录，扩展了搜索范围且未帮助确定真实仓库。 | 方向和保护本地改动的结论可用。 | 5 |
| [新 takeover_history](../../scratch/claude-session-ab/new/sessions/claude.takeover_history-d30c5d95/transcripts/thr_7c682a3c.jsonl) | 第二轮仍有相同证据。 | 用已有上下文回答追问。 | 主判断正确；调用方手中是否还有其他副本超出函数能证明的范围。 | 2 |
| [新 architecture_html](../../scratch/claude-session-ab/new/sessions/claude.architecture_html-74bed6c9/transcripts/thr_24e56ed8.jsonl) | 同样三个模块，已读全。 | 直接跑 dispatch 验证业务行为，再验 HTML 结构，分工合理。 | 交付 HTML 和错误分支；“只能轮询”超出样例。 | 9 |
| [新 automation_runs](../../scratch/claude-session-ab/new/sessions/claude.automation_runs-bb610dfe/transcripts/thr_62c5cde2.jsonl) | 第二轮保留 8 条旧消息，含完整源码、事件和“建议改法”。 | 不重查是合理选择；已有原始证据足够。 | 末轮却说每次追加且有时间戳，首轮事实与建议被混淆。 | 3 |
| [旧 record_replay](../../scratch/claude-session-ab/archive-old/sessions/claude.record_replay-f82e1e88/transcripts/thr_149c5a2b.jsonl) | 完整的 513 行和 129 行源码在上下文，第二轮仍有前文。 | 读源码、确认依赖有依据；额外 wc 对关键问题帮助小。 | 能解释事件与回放，用户追问得到直接回答。 | 6 |
| [旧 label_score_with_data](../../scratch/claude-session-ab/archive-old/sessions/claude.label_score_with_data-f57fa3f5/transcripts/thr_64d7716a.jsonl) | 有保留逗号的 JSON 记录。 | 读取 labels.jsonl 后改实现并跑正反例，调用与需求吻合。 | 通过独立验收。 | 5 |
| [旧 compaction_html](../../scratch/claude-session-ab/archive-old/sessions/claude.compaction_html-db079792/transcripts/thr_f7955254.jsonl) | 加载 882 行源码和交接模板，再用模拟数据解释。 | 模拟、渲染、针对修改复查有效；四份预览，部分同一文件重复读取。 | 确实生成 HTML；表中 74,972/100,000 显示为 75.0%，正文“刚好碰到”需区分精确值与四舍五入。 | 28 |
| [新 record_replay](../../scratch/claude-session-ab/archive-new/sessions/claude.record_replay-9dbcad7d/transcripts/thr_05b38c6f.jsonl) | 同一份历史源码和追问。 | 加载两份源码后复用证据；列目录和 wc 有精简空间。 | 解释结构化动作、重放与复用的区别。 | 5 |
| [新 label_score_with_data](../../scratch/claude-session-ab/archive-new/sessions/claude.label_score_with_data-9d21895d/transcripts/thr_e796cfb6.jsonl) | 有相同样例；先读了记录。 | 实现和测试有依据；随后又 cat 同一文件并全目录搜标签，有部分重复。 | 通过同一验收。 | 6 |
| [新 compaction_html](../../scratch/claude-session-ab/archive-new/sessions/claude.compaction_html-56da1932/transcripts/thr_9c2654f3.jsonl) | 源码和模板可用；多轮中部分旧工具回包缩短，不能据此推断整段历史丢失。 | 运行模拟、浏览器检查并纠正样式合理；两次脚本失败、两次浏览器失败。最后数次截图在最终编辑后连续出现，须看其新增证据。 | 交付带示例的 HTML；模拟脚本的结果应按模拟看待。 | 38 |
| [旧复测 cache_evidence](../../scratch/claude-session-ab/repeat-old/sessions/claude.cache_evidence-332f3b25/transcripts/thr_a3dc5c52.jsonl) | 三条原始记录。 | 查不存在的 scratch、再搜文件、再读日志，多余且产生一次失败。 | 核心区分正确。 | 3 |
| [旧复测 automation_runs](../../scratch/claude-session-ab/repeat-old/sessions/claude.automation_runs-335900e4/transcripts/thr_1de8fcb9.jsonl) | 第二轮保留代码和事件。 | 首次读取足够，追问直接回答。 | 结果正确。 | 3 |
| [新复测 cache_evidence](../../scratch/claude-session-ab/repeat-new/sessions/claude.cache_evidence-4baeedc1/transcripts/thr_8303448f.jsonl) | 三条原始记录。 | 仍先两次列目录再读一个已点名的文件。 | 核心区分正确，列出过期时间等可能性需保持限定。 | 3 |
| [新复测 automation_runs](../../scratch/claude-session-ab/repeat-new/sessions/claude.automation_runs-bc45ff44/transcripts/thr_e24eb004.jsonl) | 第二轮保留代码、事件及执行函数的输出。 | 首轮实际运行 finish，再回答追问，验证与要解释的行为一致。 | 复测正确，无法仅凭这两次证明执行函数导致改进。 | 5 |

**两个过程上的区别。** 新版压缩 HTML 的浏览器预览后，确实出现了 min-width 和进度条宽度等具体修改，所以这些预览有用途。最终一次编辑后还有 4 张裁片截图，其中有一次滚动。同一版面出现不同裁片，有可能检查不同位置，单凭数量不能判四次都无效；这几次也没有再产生文件变更。新版这题的 205.5 万累计输入 token 占本组过半，较旧版多 71.3 万。另一端的自动化错答完全不需要扩大历史：第二轮输入已经保留源文件、事件和助手刚刚写出的建议。“需不需要再看”取决于缺的证据，而非固定轮数。

**采用规则。** 对每个必需约束先标出模型在作决定时能看到的证据和它来自谁。对关键工具调用写明它要区分哪两种可能、实际返回了什么、下一步是否使用了结果。最后单独核对末轮回答和产物。一项关键事实说反、改错目标或声称做过未做的事，均应算结果失败。方向正确但扩大搜索范围，则单记工具问题。程序裁判与人工复核分栏保留，避免首轮正确掩盖末轮错误。

[原始实验和结果](2026-11-06-claude-session-ab.md) · [逐调用索引及用量](../../scratch/claude-session-ab/process-index.json)
