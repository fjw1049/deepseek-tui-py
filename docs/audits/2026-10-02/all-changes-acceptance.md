# 全部修改代码验收记录

2026年10月2日。本轮范围为当前工作区全部未提交代码、配置与测试改动，共 100 个文件（84 个已跟踪修改、16 个新增），详见 `acceptance-scope.json` 中的路径和 SHA256。既有审计文档不计入代码数量。

结论：Electron 项目自动化检查通过，修改相关 Python 回归通过，已执行的 Electron 实机场景通过。开发服务曾出现依赖缓存失配，重启后恢复。不能将本记录解释为全部外部集成或发布包整机全流程已经通过。

## 2026年10月3日补审

发现并修复一个遗漏：分屏会话的 `state.error` 原来仍在面板内显示，现接入顶部公共 `GlobalErrorNotice`。关闭时只清除所属会话错误，其他分屏错误保留，同一错误再次发生可重新显示。先增加回归测试，确认旧实现失败（全局容器应有 2 个提示，实际为 0），修复后通过。

图片、HTML、PDF 新增 6 项组件回归，验证刷新版本进入 URL、原查询参数和 fragment 保留、旧请求晚返回不能覆盖新 URL、错误后重试以及切换文件后忽略旧失败。此处验证的是组件和异步行为，不等同于 Electron 中真实文件渲染的视觉验收。

| 补验 | 结果 | 日志 |
| --- | --- | --- |
| 全量 Electron 项目回归 | 210 文件、1277 项通过 | /tmp/workbench-followup-all-tests.log |
| 分屏和全局提示专项 | 42 项通过；修复前新增用例失败 | /tmp/split-feedback-fixed.log；/tmp/split-feedback-regression.log |
| 预览刷新专项 | 6 项通过；加强旧响应不能修改 src 的断言后再次通过 | /tmp/preview-refresh-tests.log |
| TypeScript 类型检查 | 通过 | /tmp/workbench-followup-typecheck.log |
| 本轮 3 个代码/测试文件 ESLint | 通过，无警告 | /tmp/workbench-followup-lint.log |
| 生产构建 | 通过 | /tmp/workbench-followup-build.log |
| 差异空白检查 | 通过 | git diff --check |

补审范围共 101 个代码、配置和测试文件，SHA256 见 `acceptance-scope-followup.json`。对照原 100 文件清单，仅分屏组件与其测试发生后续变化，另新增预览刷新测试；原清单保留作为历史快照。Python 代码本轮未变化，沿用前轮回归及基线比对结果。

实机续验遇到控制层阻塞：可取得 Electron 窗口截图，但点击连续返回 `noWindowsAvailable`。按项目完整应用路径重新绑定并 Raise 窗口后仍失败，已请用户确认解锁并将 DeepSeek GUI 切到前台。因此本轮未新增真实预览截图验收，先前 `aria-hidden` 焦点警告也尚未复现定位；未对其做推测性修复。

10月3日再次续验：101 个文件校验值全部一致。只读进程核对确认正在运行的是本工作区 Electron（PID 58963），没有误验另一个目录的副本。原生 View 菜单可以点击，Cancel 和 Reload 可执行，截图可显示首页；页面可访问树仍只有窗口与菜单，页面坐标点击继续返回 `noWindowsAvailable`。因此不能将菜单操作或静态截图计为预览刷新通过，实机交互阻塞仍未解除。本次没有新增业务代码修改，也未重复运行未发生变化的全量测试。

## 2026年10月3日再次实机续验

重新连接后可以读取完整控件树并观察到会话、侧栏和临时 HTML 标签状态变化，但截图持续停留在此前的页面；Raise 窗口、键盘操作和重新读取均未恢复可靠视觉反馈，实际坐标点击再次返回 `noWindowsAvailable`。因此控件树变化不能作为预览视觉通过的依据。临时 `acceptance-preview-fixture.html` 已从磁盘删除，标签关闭请求未获得可靠完成确认。没有新增业务代码变更；核对后 101 个范围文件的 SHA256 均与补审快照一致，既有 1277 项测试和构建结果仍对应当前代码。真实预览刷新和焦点警告复现继续待验。

## 自动化结果

| 检查 | 结果 | 日志 |
| --- | --- | --- |
| Electron 项目 npm test | 209 文件、1270 测试通过 | /tmp/workbench-all-tests.log |
| TypeScript renderer 和 main 类型检查 | 通过 | /tmp/workbench-typecheck.log |
| ESLint | 0 错误、9 警告 | /tmp/workbench-lint.log |
| 生产构建 npm run build | 通过 | /tmp/workbench-build.log |
| git diff --check | 通过 | 命令退出码 0 |
| Python 非 live 全量 | 2882 通过、26 失败、3 跳过、36 排除 | /tmp/runtime-all-tests.log |
| HEAD 基线重跑上述 26 个失败项 | 相同 26 个测试全部失败 | /tmp/runtime-baseline-tests.log |
| Python 修改相关回归 | 48 项通过 | /tmp/runtime-modified-area-tests.log |

Python 全量使用 `--import-mode=importlib -m 'not live and not live_mcp'`。默认导入模式存在两个同名 `test_audit_fixes.py` 的收集冲突。HEAD 基线通过临时 git archive 副本测试，没有切换或覆盖工作区。基线失败表明不能把这 26 项归因于本次改动，但也不能称项目全量测试全绿。日志含缺失测试夹具字段、缺少 API Key、任务目录已有调度器锁及既有断言不匹配。

## 修改范围与验证方式

| 修改类别 | 自动化和代码核对 | Electron 实机验证 |
| --- | --- | --- |
| 全局报错、共享提示容器、复制失败、弹层关闭 | GlobalFeedback、GitBranchPicker.feedback 等回归通过；检查各调用点、i18n 与 portal 层级 | 本轮未逐个注入全部失败分支；前轮浏览器组件截图不能替代 Electron 全分支验收 |
| 编辑器工作区草稿、异步读取和保存保护 | workspace-editor-store、WorkspaceEditorPanel 回归通过 | 临时文本读取、产生未保存内容、A→B→A 草稿恢复、保存后磁盘内容比对通过 |
| 图片、HTML、PDF 刷新版本 | 代码核对与工程测试通过 | 未逐一做真实文件内容更新后的截图比对 |
| 表格分页和大 Diff 限制 | TableDocumentPreview、DiffView 回归通过 | 120 行 CSV 三页，51/101 行起始、末页禁用下一页通过；Git Diff 可显示 |
| 看板创建目标绑定、会话模型及发送保护 | chat-store-target 与相关会话测试通过 | 看板列表、现有会话打开通过；未发送真实付费模型请求 |
| 分屏渲染优化、空闲会话回收 | ChatSplitWorkspace 等测试通过，覆盖活跃任务保留和流式输出不重渲染输入框 | 未执行多模型并发长时间压力场景 |
| 历史折叠及跳转、长文本粘贴 | MessageTimeline.history、FloatingComposer.paste 等回归通过 | 历史会话与多语言代码块可加载；未实机重放全部竞态 |
| 终端跨面板生命周期输出 | terminal-session-store 回归通过 | PTY 创建、关闭显示面板、重新打开看到延迟输出通过 |
| 自动化表单、一次性任务及运行记录竞态 | AutomationTaskForm、AutomationCenter.race 及 48 项 Python 相关测试通过 | 列表、新建表单、不投递默认值、空描述拦截通过；取消未创建真实任务 |
| 任务 active_only 和 ids 筛选 | 前端索引测试和 Python 超过 100 条记录筛选测试通过；核对两套路由与 runtime 参数转发 | 未在真实数据中创建大量后台任务 |
| 请求去重和并发限制 | 核对 connector、完成轮询、pending inputs 及自动化运行读取；相关工程测试通过 | 常规页面加载正常；未实机网络延迟注入 |
| 模型临时密钥与 IPC、邮件配置竞争写入 | renderer→preload→main 参数一致；config-write 冲突保护测试通过 | 模型页、用量统计与频道页可加载；未修改真实密钥或发送邮件 |
| Git 未跟踪文件 patch 复用 | Git integration 测试通过；核对单请求缓存与最多四个并发读取 | 本工作区文件树和 Git Diff 可显示；未暂存、提交或回滚用户改动 |
| ASR Blob、文件选择可选路径、usage 类型修正 | 类型检查、相关工程测试通过 | 未配置语音识别密钥，未验收真实转录 |
| 懒加载、依赖预构建、测试配置、翻译和类型 | fresh-cache lazy import 测试、构建与全量测试通过 | 设置、模型、自动化、频道、市场、看板和编辑器均已加载 |

## 实机发现与恢复

打开项目空会话的右侧栏时，旧开发服务返回 `504 Outdated Optimize Dep`，涉及 `d3-dsv` 和 `shiki`，随后触发应用错误边界。普通刷新仍失败。检查发现服务返回的依赖 URL 哈希与磁盘 `.vite/deps/_metadata.json` 不一致。

已正常退出并重启本项目 `npm run dev`，重新生成一致依赖；之后右侧栏、文件读取编辑保存、跨项目草稿、CSV 分页均通过。没有把重启环境写成业务代码修复。重启后的日志位于 `/tmp/workbench-electron-acceptance.log`，本轮检查未见新的界面崩溃；日志仍记录了一条 `aria-hidden` 与焦点保留冲突的可访问性警告，尚未定位到具体触发控件，不能记为零警告。

## 未覆盖的整机验收边界

- 实际付费模型流式请求、长时间多任务并发、外部 MCP 及第三方渠道投递。
- 真实密钥更新、语音识别与系统权限弹窗。
- 永久删除、真实归档批处理、分享发布以及 Git 破坏性操作的实机提交。
- 安装包构建、签名、公证、安装升级，以及 Windows/Linux 实机。
- 报错分支逐一在 Electron 内注入、图片/HTML/PDF 更新后逐项视觉比对。

这些项不影响上述自动化结果，但不能标为已验收。没有为使测试全绿而修改与当前差异无关的 Python 行为。

## 证据与清理

终端截图：`/Users/fjw/.codex/visualizations/2026/10/02/01a0fbe0-497f-7c01-8ef8-323560035930/electron-terminal-acceptance.png`。

表格截图：`/Users/fjw/.codex/visualizations/2026/10/02/01a0fbe0-497f-7c01-8ef8-323560035930/electron-table-acceptance.png`。

临时 `acceptance-ui-fixture.txt` 与 `.csv` 已关闭标签并删除；未改业务文件、密钥或投递真实消息。应用保留运行。本轮新增验收记录及范围清单，未额外修改业务代码。

## HEAD 可复现的失败项

- `tests/contract/test_auto_publish.py::test_start_turn_never_dispatches_without_checkpoint`
- `tests/contract/test_l0_hard_clear_batching.py::test_batching_keeps_the_payload_prefix_reusable`
- `tests/contract/test_summary_input_fidelity.py::test_consumer_hint_names_the_ledger_and_gives_a_tiebreaker`
- `tests/contract/test_thread_resume.py::test_resume_thread_returns_detail`
- `tests/contract/test_turn_user_input_integration.py::test_monitor_turn_user_input_required_event_log`
- `tests/evals/test_eval_lab.py::test_start_actual_offline_worker_history_export_and_comparison`
- `tests/evals/test_platform.py::test_offline_platform_writes_traceable_artifacts`
- `tests/golden/test_static_contracts.py::test_end_of_turn_self_check_clause_present`
- `tests/golden/test_static_contracts.py::test_long_session_reminder_covers_core_disciplines`
- `tests/parity/phase_d/test_mcp_hooks_p0.py::TestAppServerMcpToolRoute::test_handle_tool_routes_external_mcp`
- `tests/parity/phase_d/test_mcp_hooks_p0.py::TestAppServerMcpToolRoute::test_handle_tool_denies_mcp_tool_requiring_approval`
- `tests/parity/phase_d/test_mcp_hooks_p0.py::TestAppServerBuiltinToolApproval::test_handle_tool_denies_builtin_requiring_approval`
- `tests/parity/phase_d/test_mcp_hooks_p0.py::TestAppServerBuiltinToolApproval::test_handle_tool_allows_read_only_builtin`
- `tests/parity/phase_d/test_mcp_hooks_p0.py::TestEngineLifecycleHooks::test_mcp_startup_emits_generic_event_frames`
- `tests/test_audit_16.py::test_search_authorizes_real_targets`
- `tests/test_audit_fixes.py::test_action_quit_awaits_cancelled_engine_task`
- `tests/test_multimodal_pipeline.py::test_conversation_bundle_restores_original_images`
- `tests/test_multimodal_pipeline.py::test_switch_route_updates_new_subagent_runtime_only`
- `tests/test_p0_audit_fixes.py::test_elevation_wait_rethrows_cancelled_error`
- `tests/test_p0_audit_fixes.py::test_collect_turn_events_streams_live_text_to_task_record`
- `tests/test_rlm_subagent_task_integration.py::TestToolRuntimeIntegration::test_create_tool_runtime_attaches_managers`
- `tests/test_rlm_subagent_task_parity.py::TestTaskSecurity::test_add_task_default_auto_approve_true`
- `tests/test_subagent_context_ingress.py::test_file_search_caps_huge_listings`
- `tests/test_subagent_stage_a_fixes.py::test_hidden_internal_turn_carries_its_own_provenance[goal_continuation]`
- `tests/test_tool_schema_docs.py::test_tool_parameters_are_documented`
- `tests/test_usage_token_semantics.py::test_context_breakdown_uses_full_prompt_instead_of_uncached_remainder`
