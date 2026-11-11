# 工具与主流程审核 · 2026-11-11

范围：除 subagent / task、自动化（cron/automation）之外的工具和主循环。重点看了 `engine/orchestrator`（`core.py` 的 `_run_conversation`、`_handle_send_message_inner`，`tooling.py` 的分发、审批、结果收尾）、`engine/turn.py`、`engine/context.py`、`tool_dedup.py`、`completion.py`、`dispatch.py`，以及 `tools/` 下的 file、search、shell、web、knowledge、todo、user_input、mcp、registry。browser 和 CUA 已有专门的审计，这次只看了它们和主循环的接口部分。

**这不是逐行读完全部代码的结论。** 测试环境的限制见文末。

## 一、已修复（12 项）

| # | 问题 | 修复 | 位置 |
|---|---|---|---|
| F1 | **同一轮里接受计划后写不了文件。** 工具目录在轮次开始时按 plan 模式算好，`exit_plan_mode` 接受后切到 agent，提示“现在开始实现”，但目录里仍然没有 `write_file`/`edit_file`/`exec_shell`，每次写都会报“不在目录中”，要等用户再发一条消息。`enter_plan_mode` 也有反方向的问题。 | 每批工具执行完后，如果模式变了，就重算目录和 `_active_api_tools`。 | `core.py::_run_conversation` |
| F2 | **被拒绝的工具调用不关闭 UI 条目。** 审批拒绝（返回 `None`）的路径没有发 `ToolResultEvent`，条目一直转圈，直到轮次结束才被标成“Turn ended before tool result”。并行路径也一样。 | 拒绝时发出失败结果事件。 | `tooling.py` 顺序、并行两处 |
| F3 | **压缩后的工具输出找不回来。** 入口压缩只留首尾片段（小窗口模型 900 字符；DeepSeek 1M 窗口是 1 万字符）。溢出到磁盘只对**成功**且超过 100 KiB 的结果生效，所以失败的测试日志、2 KB 到 100 KB 之间的输出，中间部分彻底丢失。shell 超过 64 KB 时自带的“Full output saved to …”标记位于正文中段，也正好被压缩掉。 | 压缩发生时，复用已有的溢出路径，或把全文写入 `~/.deepseek/tool_outputs/<call_id>.txt`，并在结果末尾附上读取方式。措辞与 L0 剪枝识别的格式一致，剪枝后仍保留指针。 | `tools/runtime.py::point_compacted_output_to_disk`，`tooling.py::_finish_tool_result` |
| F4 | **每次工具调用都序列化整个会话。** `parent_session_messages` 只给 `agent` 的 fork_context 用，却在每次调用前都把全部 session 做 `model_dump`，长会话里每次调用的开销是 O(历史)。 | 只在调用 `agent` 时生成。行为不变。 | `tooling.py::_execute_single_tool` |
| F5 | **token 估算每轮重复做 BPE。** 每轮至少有 L0、压缩判断、请求估算、TurnLoop 预算四次全量估算，在事件循环里同步跑 tiktoken。 | 按（编码器、文本哈希、长度）缓存 512 字符以上文本的计数，键里不保存原文，上限 8192 条。结果完全一致。 | `engine/context.py::estimate_tokens` |
| F6 | **计划提醒和 plan.md 相互矛盾。** `should_force_update_plan_first` 正是在“只要快速计划、不提代码”时触发，注入的却是“先探索仓库”；plan.md 对这种情况的规定是跳过调查。 | 提醒文本改为与 plan.md 一致。 | `engine/prompts.py::PLAN_GROUNDING_REMINDER` |
| F7 | **`file_search` 的浅层列目录看不到子目录。** 描述写的是 `max_depth=1` 等于 shallow ls，实际只输出文件。plan/ask 模式没有 shell，模型完全看不到目录结构。 | 被深度截断的子目录以 `name/` 列出，同样遵守 pattern、gitignore 和授权检查。原测试断言了旧行为（`["root.py"]`），已改为 `["root.py", "src/"]`。 | `tools/search.py` |
| F8 | `_IGNORED_DIRS` 里的 `.egg-info` 永远匹配不到，真实目录名是 `pkg.egg-info`。 | 改为后缀匹配。 | `tools/search.py` |
| F9 | `edit_file`/`write_file` 遇到非 UTF-8 文件（如 GBK 编码的 CSV）时，报的是裸的 codec 错误。 | 与 `read_file` 统一为“不是 UTF-8 文本文件”。 | `tools/file.py::_read_text` |
| F10 | `read_file` 的 `limit=0`（schema 允许）会返回空页。 | 视同未传 limit。 | `tools/file.py` |
| F11 | **`fetch_url` 把二进制当文本塞进上下文。** PDF、图片、压缩包走直连或 httpx 兜底时，会解码出最多 3 万字符乱码。 | 按 content-type（pdf、zip、image、audio、video 等，svg 等 `+xml` 除外）或前 8 KB 内有 NUL 字节判定为二进制，返回明确错误，并建议用 shell 下载。`application/octet-stream` 只凭 NUL 判定，因为有些站点用它返回纯文本。 | `tools/web.py::_reject_binary_body` |
| F12 | **shell 非零退出且没有 stderr 时，结果里看不到退出码。** 例如 grep 无匹配、`test -f`：模型收到的是一个空的错误结果。 | 内容加上 `[exit N]` 前缀。 | `tools/shell.py::_build_shell_result` |

另外清理了一处：`core.py` 里的 `step_error_count` / `consecutive_tool_error_steps` 只累加、从不读取，是被删掉的“容量升级”留下的死代码，已删除。`load_skill` 的描述原来写“载入到下一轮上下文”，与实际行为（作为本次调用结果返回）不符，可能让模型以为要先结束本轮，已改正。

新增回归测试 `tests/test_audit_tool_pipeline.py`，共 14 个用例，覆盖上表除 F4、F6 外的全部问题。

## 二、请你审核：确认存在，但需要你定方向

### 高

**R1 · TUI/CLI 失败的轮次会丢掉整轮记忆。** `_handle_send_message_inner` 只在成功时提交 `working_messages`。轮次上限、输出截断、流错误等任何失败，都会把本轮的用户请求和所有已完成的工具往返一起丢弃，而文件改动已经落盘。用户再说“继续”时，模型既不知道要继续什么，也不知道自己改过哪些文件。server 端会在下一轮前从 store 重建（`_resync_warm_engine_from_store`），所以两种界面行为不一致。
建议：提交到最后一个完整的 tool_use/tool_result 配对为止，只丢弃末尾不完整的 assistant 消息。

**R2 · `note` 工具只写不读。** 它把内容追加到 `~/.deepseek/notes.txt`，但没有任何代码再把这个文件读回上下文；`config.notes_path` 字段也没有被这个工具使用。base.md 却告诉模型“用 note 记录跨会话的决定和阻碍”，等于承诺了一个并不存在的记忆功能。
可选：(a) 删除工具和 base.md 里对应的那句；(b) 在会话开始时把 notes 注入上下文。两种都会改变工具目录或提示前缀，需要你选。

**R3 · skill 的配套文件读取受阻。** `load_skill` 列出配套文件的绝对路径，并让模型用 `read_file` 打开。但 `~/.deepseek/skills`、`~/.claude/skills` 和内置 skill 目录都不在工作区内，每次读取都会弹审批，无人值守运行时直接被拒。另外只列同级文件，`scripts/`、`references/` 这类子目录完全不可见（Anthropic skill 格式常用这种结构）。
建议：`load_skill` 成功后，把该 skill 目录作为本会话的只读根；有上限地列出子目录内容。这涉及权限模型，需要你确认。

**R4 · ask 模式。** 审核时 GUI 的“只回答、不执行操作”在后端完全没有落实：没有 ask 提示词，工具和 agent 模式一样全量开放。审核期间另一个进程已经加上 `ASK_MODE_TOOL_ALLOWLIST`、`modes/ask.md`、分发检查和注册表过滤，相关测试通过。请确认允许名单是否合适，其中包含 `request_user_input`、`task_list`/`task_output`、`cron_list`、`GetGoal`。

### 中

**R5 · plan/ask 模式下没有 MCP。** 并行改动给最终目录加了允许名单过滤，所以 plan/ask 下 MCP 工具全部不可见。与分发检查一致，但只读的 MCP 工具（搜索类连接器）也用不了。要开放，需要可信的只读信号，例如 MCP tool annotations 里的 `readOnlyHint`。

**R6 · 中途切换模式后，系统提示词还是旧模式。** F1 只刷新了工具目录。接受计划后，系统提示里仍写着“Mode: Plan … file writes are unavailable”，与“现在开始实现”冲突。重建系统提示会多一次前缀缓存未命中；也可以只注入一条提醒。

**R7 · `grep_files` 一超预算就丢掉全部结果。** 5 秒或 64 MB 预算用完时直接报错，已经找到的结果全部作废。它对每一行单独调用带超时的 regex，并对每个文件做一次 `check_path`（包括 `resolve()`），大仓库里很容易触顶。
建议：返回部分结果，并明确标注“已提前停止，结果不完整”。

**R8 · 探测性 shell 命令被记成“未解决的工具失败”。** 非零退出都算失败，并计入 `TurnFacts.failures`，所以 `grep` 无匹配、`test -f`、`git diff --exit-code` 都会在回复下方出现“未解决的工具失败”，任务状态也被标成 partial。需要你决定判定规则，例如退出码 1 且没有 stderr 时不计入。

**R9 · soft-resume 的压缩上限与实时不同。** `server/threads/items.py` 重建历史时固定使用 `"gpt-4"` 的小窗口上限（1.2 万、2 千、900 字符），而 DeepSeek 实时运行的上限是 4 万、1.5 万、1 万字符。被中断的轮次恢复后，读过的文件只剩 900 字符片段，但 SOFT_RESUME_LEAD 又要求模型“不要重复对话里已有结果的调用”。
建议：使用线程实际模型的上限，并复用 F3 的落盘指针。

**R10 · 流中途重采样留下孤立的工具条目。** TurnLoop 丢弃已经发出 `ToolCallEvent` 的半截样本后，这些调用永远收不到结果，最后被标成“Turn ended before tool result”。可以像 `discard_streamed_round` 那样，给被丢弃的调用补发 not-executed 结果。

**R11 · 快速计划启发式只认英文。** F6 已修正提醒文本，但 `should_force_update_plan_first` 只匹配英文关键词，中文请求永远不会触发。既然 plan.md 已经写明这条规则，建议直接删掉这个启发式。

**R12 · `network_policy` 为 prompt 时 `fetch_url`/`web_search` 永远失败。** 代码注释写明“这条路径没有交互式网络审批”，所以未列入名单的主机一律拒绝。建议接入现有的审批门。

### 低

- **R13** · 不论是否配置了 MCP 服务器，只要开启 `features.mcp`，`list_mcp_resources`/`read_mcp_resource` 就会注册，每次请求都多带两份 schema。
- **R14** · `write_file` 无法覆盖已存在的非 UTF-8 文件：rewind 捕获要求旧内容是文本。F9 只让报错变清楚，能力缺口还在。建议按字节捕获。
- **R15** · 搜索时 `_IGNORED_DIRS` 静默跳过 `dist`、`build` 等目录，不像 gitignore 那样报告跳过了多少，模型可能误判文件不存在。
- **R16** · fork_context 子代理只能拿到之前轮次的 session，拿不到当前轮（连本轮的用户请求也没有）。这个问题在 subagent 的接口上，本次没改。
- **R17** · 已不再需要的代码：`_timeout_fallback_hint` 的非 curl 分支只有测试在用；`job_hint` 元数据没有消费方；`dispatch.normalize_legacy_tool_call` 里 task/automation 的旧名转发写着“保留一个弃用周期”，可以定个删除日期（属于本次排除的范围，只记录）。
- **R18** · exec_shell 结果的 metadata 里有完整的 stdout/stderr（各最多 64 KB），与 content 重复，又随 `ToolResultEvent` 写入条目存储。如果 UI 用不到，可以去掉。
- **R19** · F5 只省掉了 BPE；估算时每条消息仍然要做一次 `model_dump` 和 `json.dumps`。如果要继续优化，需要按消息缓存，前提是先确认消息对象不会被原地修改。

## 三、验证情况与局限

- 本机 Python 环境是 macOS 的 venv，审核所用的 Linux 环境用不了，也无法联网安装依赖。我在另一台 Python 3.13 环境里放了项目快照，给缺失的依赖（regex、tiktoken、textual、fastapi 等）加了占位模块，并用一个简易 asyncio 插件代替 pytest-asyncio。
- 新增的 14 个用例：在**修复前**的代码上全部失败（引擎层的两个分别复现为“拒绝后没有结果事件”和“第二轮目录里没有 write_file”），修复后全部通过。
- 对 34 个相关测试文件或目录，在修复前后两份代码上跑同一套：结果除新增用例和并行进程的 ask 模式测试外完全相同。两边都存在的失败有 1 个 engine 用例、16 个依赖异步 fixture 的 error、`test_transcript` 1 个、`test_audit_tool_dispatch` 1 个，原因是占位环境或并行改动，与本次修改无关。其中 `test_audit_tool_dispatch::test_registry_validates_dictionary_values…` 报 `ToolRegistry.execute() missing … 'context'`，请在真实环境复查。
- `test_search_tool.py::test_grep_rejects_pathological_regex_promptly` 依赖真实 regex 库的超时功能，占位环境下会卡住，已跳过。
- **没有跑全量测试，也没有调用真实模型。** 请在本机执行：

```sh
.venv/bin/python -m pytest -q tests/test_audit_tool_pipeline.py tests/test_search_tool.py tests/test_file_tools.py tests/test_fetch_url.py tests/test_plan_mode_tools.py tests/test_ask_mode_readonly.py tests/engine
.venv/bin/python -m pytest -q -m 'not live and not e2e and not live_mcp'
```

- 审核期间工作区有另一个进程同时在改 `core.py`、`tooling.py`、`prompts.py`、`engine/tools.py`、`registry.py`（ask 模式、cron 相关）。我的修改都是按原文精确替换，写完后逐项确认过仍然存在，没有覆盖对方的改动。由于同一文件里混有双方的改动，提交前请分别审核。
- 临时文件：`.claude/audit-2026-11-11-src.tgz`、`.claude/audit-tests.tgz`、`.claude/audit-bk.tgz`、`.claude/audit-bk/`（修改前的备份），以及 py_compile 生成的 `*.cpython-310.pyc`。这些都在 git 忽略范围内，可以手动删除。
