# 项目检查与审核清单 · 2026-11-11

## 范围与结论边界

这次完成了全仓结构/配置扫描、Python 与工作台静态检查、非 live/e2e Python 测试、工作台测试，以及核心路径的人工复核。重点阅读了客户端构造、限流、状态持久化、Goal、工具输出、文件授权、插件下载解包、浏览器权限、会话存储、数据清理、自动化投递、Electron 导航隔离等实现及相关测试。

**这不是“逐行读完所有源码，已找出所有问题”的证明。** Python 产品代码有 260 个文件、约 11 万行，工作台 src（含测试）有 837 个 TS/TSX 文件、约 13.7 万行。测试通过也不代表所有真实环境路径正确。未进行真实模型调用、真实邮件/IM 投递、完整桌面人工交互、Windows/Linux 验证和公开分享服务部署验证。以下区分已复现修复、确认的设计/维护问题与待验证风险。

开始时已有 13 个未提交修改，涉及 automation/pipeline、engine/orchestrator/core、tools/automation、registry、subagent/tools、task 三个文件及五个测试文件。本次保留这些修改，没有提交 Git commit。

## 已修复（8 类）

| 问题 | 修复与验证 | 文件 |
|---|---|---|
| 企业微信 webhook 输入异常、域名误判 | 缺少 hostname 或非法 IPv6 URL 不再抛异常；用精确域名匹配替换子串匹配。正常 key/官方 URL 仍可识别。注意原发送逻辑始终使用固定官方主机，此处不能描述成已证实的任意主机请求漏洞。 | `src/deepseek_tui/automation/inbox.py` |
| tar 包结构兼容错误 | `.` 根目录不再触发 IndexError；单独的根文件不再被当成包装目录剥掉；`./package/...` 正确去掉包装目录。保留原有拒绝链接、路径穿越和大小限制。 | `src/deepseek_tui/plugins/fetch.py` |
| IPv6 浏览器 origin 失真 | 保留地址方括号，例如 `http://[::1]:8080`，避免下游重新解析时丢失主机语义。 | `src/deepseek_tui/browser/permissions.py` |
| pytest 入口不一致 | `pythonpath` 加入仓库根目录。原先 `.venv/bin/pytest` 收集产生 17 个导入错误，而 `python -m pytest` 能收集。修改后前者也成功收集。 | `pyproject.toml` |
| 安装依赖清单漂移 | requirements 补齐 PyYAML、tiktoken、regex、Pillow、python-docx、openpyxl、python-pptx、browser-cookie3；开发清单补 types-PyYAML。解析规范化后与 pyproject 两组声明逐项一致。 | `requirements.txt`、`requirements-dev.txt` |
| 数据盘点重复读取全部轮次 | 复用已有 `list_turns_by_thread` 批量接口；3 个会话/3 个轮次场景中，轮次记录读取从 9 次降到 3 次，消息与条目数量保持一致。 | `src/deepseek_tui/server/data_inventory.py` |
| 动画测试仍使用旧常量 | 测试改为验证现有共享动画时长变量，保留布局、材质和交互断言，没有更改产品动画。 | `packages/workbench/src/renderer/src/appearance-material.test.ts` |
| 普通操作函数被误识别为 React Hook | 无 Hook 调用的异步操作 `usePluginNow` 改名为 `startChatWithPlugin`，同步调用方及测试 mock。消除两处 rules-of-hooks 错误。 | `packages/workbench/src/renderer/src/components/extensions/` 下 6 个文件 |

新增 `tests/test_audit_input_boundaries.py`：12 个输入边界用例。修复前复现了 8 个 webhook/tar 失败和 2 个 IPv6 失败，另外 2 个是正常行为对照。存储测试新增一个扫描次数回归用例，修复前为 9 次，修复后为 3 次。

## 请审核：确认存在，但需要确定处理边界

### A1 · 高：历史锁文件不能代表当前完整安装

证据：`requirements.txt` 注释仍将 `requirements.lock` 推荐为精确安装来源；后者没有 tiktoken、Pillow、python-docx、openpyxl、python-pptx、browser-cookie3 等当前直接依赖。仓库同时维护 `uv.lock` 和 freeze 风格的 `requirements.lock`。

建议：以 `pyproject.toml + uv.lock` 为权威来源，自动导出 pip 锁文件并检查漂移；或明确废弃旧 lock。未直接重新锁定，避免无意升级依赖、固定本机专用包或改变跨平台解析结果。

审核项：保留 pip 锁文件并自动生成，还是统一 uv？

### A2 · 高：前后端 DEEPSEEK_HOME 解析规则不同

证据：Python `config/paths.py::expand_path` 展开环境变量和 `~`；TS `shared/workbench-home.ts::resolveWorkbenchHome` 只对环境变量的原始值调用 `resolve`。当变量值字面包含 `~/data` 或 `$HOME/data` 时，两端会指向不同目录。

影响：配置、会话和 GUI 设置可能被分散保存。绝对路径配置不受这一差异影响。

建议：确定共同的路径展开语法；增加跨语言固定用例。修复时检查已经写到错误目录的数据，决定是否提供迁移，避免简单改路径让用户以为数据消失。

### A3 · 中：TUI 端点探测与实际客户端不共用协议选择

证据：`client/factory.py::build_llm_client` 对 OpenAI 主机选择 Responses 客户端，而同文件 `test_endpoint` 的非 Anthropic 分支固定请求 Chat Completions；TUI `commands.py` 调用此探测函数。

影响：只支持其中一种接口的模型，可能出现“测试连接失败但实际可用”或反向结果。这里确认的是代码路径差异，未调用真实供应商验证具体模型。

建议：让探测复用运行时协议选择和请求规范化。审核时确定探测是否还应验证工具、图片和推理参数，避免把简单连通性检查扩大成昂贵调用。

### A4 · 中：批量清理仍有成倍扫描

证据：`server/data_inventory.py::clear_conversation_history` 对每个会话调用 `delete_thread_tree`，后者删除前后都遍历整个 store 计算大小；`optimize_storage` 逐会话调用扫描全部轮次的 `list_turns_for_thread`。本次只优化了只读盘点路径。

影响：会话数和文件数增长后，清理明显变慢。

建议：批处理时统一计算 before/after，并复用批量轮次索引。删除路径需补并发写入、导入 generation、孤儿记录和断电恢复测试后再改。

### A5 · 中：中心模块承担过多职责

证据：`server/threads/manager.py` 约 7663 行，`engine/orchestrator/core.py` 约 3791 行，`integrations/plugins.py` 约 3140 行；工作台 `chat-store.ts` 约 4195 行、`MessageTimeline.tsx` 约 3027 行。

建议：优先按已有业务边界提取会话恢复/发布协调/生命周期操作，随后处理 GUI 会话状态与运行时连接。不要按行数机械拆文件；必须保留取消、审批、工作区发布和恢复测试。需要独立重构任务，不适合混入当前缺陷修复。

### A6 · 中：静态质量门禁尚未形成可用基线

证据：本次 Ruff 对 `src evals scripts` 报告 613 项，主要是行长/导入顺序，也包括未使用符号与闭包捕获警告；Mypy 报告 118 个文件中的 1409 项错误。数字是本次环境下工具输出，不等于同数量运行时 bug。检查了闭包警告中的即时 await 场景，没有仅凭告警改写。

前端消除两处命名导致的错误后，ESLint 仍有 13 个 Hook 依赖/ref 清理警告，分布于 AppShell、终端、浏览器视口、Composer、MessageTimeline、CUA 和 Connectors。应逐一判断是否会捕获旧值；不能统一添加依赖，否则可能重建连接或重复副作用。

建议：先建立“不引入新增错误”的基线，再按模块清理。不要通过全局关闭规则来制造绿色结果。

### A7 · 中：Cookie 站点归并使用启发式规则

证据：`browser/sites.py::site_of` 仅使用常见二级域后缀表，不使用 Public Suffix List，注释明确 `a.github.io` 会归到 `github.io`。因此不同租户可被归到同一个 Cookie 导入选择项。

建议：决定是否引入可更新的公共后缀数据，包含私有后缀规则。需兼顾离线使用、更新策略，以及已保存站点选择的迁移。这里是 Cookie 选择粒度风险，不应直接声称所有浏览器操作审批都跨租户共享；操作 origin 是另一条路径。

### A8 · 低：兼容代码和疑似无用依赖应有退役标准

候选项：`client/base.py::RetryConfig.max_error_retries` 仅保留构造兼容，当前没有消费点；`utils/__init__.py::DEFAULT_LOG_DIR` 只保留旧名称，实际读取走动态路径；`server/app.py` 保留 legacy 路由；`integrations/plugin_compat.py` 保留跨生态转换；`sessions/` 仍服务旧导出/恢复。

依赖候选：生产 `src` 中未搜索到 `jose` / `passlib` 使用；pre-commit 的 Mypy 环境仍安装 aiosqlite/keyring，而当前产品依赖表没有它们。未搜索到直接使用不能证明插件、外部调用或部署脚本不依赖它们。

建议：先给外部 API、配置字段、旧数据格式定义兼容支持期，再删除。内部未使用 import 可以单独清理；没有批量删除旧数据或兼容入口。

### A9 · 低：Goal 持久化含有写出但不恢复的字段

证据：`goal/persist.py::state_to_dict` 写出 `last_progress_signature` / `stalled_turns`，`state_from_dict` 不恢复；`goal/service.py::resume` 又明确重置二者。

这可能是合理的“重启/人工恢复视为新一轮进展检查”语义，并非已确认的恢复缺陷。建议明确语义：若字段只为诊断而保存，应注明；若要求恢复连续停滞计数，需要一起修改 resume 规则，不能只在反序列化时补字段。

### A10 · 中：跨平台与最低 Python 版本的承诺需明确

项目声明 Python >=3.10，但浏览器依赖只在 >=3.11 安装，浏览器工作台实现使用 `asyncio.timeout`；CUA 的文件锁和系统 API 是 Unix/macOS 路径。README 推荐 3.12，却未详细列出各平台/版本的功能降级矩阵。

建议：明确“核心运行时支持 3.10，浏览器需 3.11+，CUA 支持哪些平台”，或统一提升最低版本；再增加对应平台 CI。当前没有 Python 3.10、Windows/Linux 的实际验证结果，不能据此声称这些平台的核心运行时整体不可用。

## 验证结果与复现命令

| 检查 | 结果 |
|---|---|
| Python 非 live/e2e/live_mcp 全量，首次沙箱内运行 | 4096 passed、173 skipped、50 deselected；2 failed + 40 errors，集中在本地端口/子进程限制 |
| 上述两个受影响测试文件，允许本地端口/子进程后复核 | 43 passed，包含原 42 个失败/初始化错误及同文件正常测试 |
| 修改后的 Python 定向回归 | 48 passed、1 skipped |
| pytest 脚本入口收集复核（较早阶段，后续新增用例另有定向验证） | 4321/4371 collected，50 deselected，无收集错误 |
| 工作台全量首次运行 | 2068 passed、11 failed；其中 10 个端口限制、1 个旧动画断言 |
| 前端上述三个文件复核 | 27 passed |
| 插件入口更名后相关三个测试文件 | 10 passed |
| 前端 TypeScript | 修改前后均通过 |
| 前端 ESLint | 修改后 0 errors、13 warnings |
| eval 用例结构验证 | 94 cases validated |
| requirements 与 pyproject 比较 | 两组直接依赖的规范化集合完全一致 |
| `git diff --check` | 通过 |

全量测试与定向复核是分次执行，**没有声称修改后的全部测试在同一次运行中全绿**。分享 worker 的测试要求已有 `127.0.0.1:8791` 服务；本次尝试受到环境限制，未启动/部署 D1/R2 服务验证，计为未验证。

常用复现命令：

```sh
.venv/bin/python -m pytest -q -m 'not live and not e2e and not live_mcp'
.venv/bin/python -m pytest -q tests/test_audit_input_boundaries.py tests/test_plugin_fetch.py tests/test_browser_local_pages.py tests/contract/test_data_inventory.py
PYTHONPATH=src:. .venv/bin/python -m evals validate
.venv/bin/ruff check src evals scripts
.venv/bin/python -m mypy src
cd packages/workbench
npm run typecheck
npm run lint
npm test -- --maxWorkers=2
```

本轮未执行联网更新依赖、删除兼容模块、删除用户历史数据、发送邮件/IM、发布或部署。

## 第二轮修复与真实验证（用户确认保留兼容后）

以下为后续进展，覆盖上面的初轮状态。保留公开接口、旧数据读取能力与现有版本选择；没有提交 commit。工作区同时存在其他任务修改，本轮没有覆盖它们。

### 已落地

1. **A1：可复现依赖锁。** 新增 `scripts/export-requirements.py`、`make requirements-lock` 和 `make check-lock`；从现有 `uv.lock` 离线、locked 导出带哈希和平台条件的 pip 锁文件，包含 dev extra。`uv.lock` 未改变，未升级版本。`make check` 加入漂移检查；原锁文件先被检查命令拒绝，重新生成后通过。
2. **A2：数据路径统一。** Workbench、配置目录和 runtime token 复用同一解析函数，支持当前用户 `~`、`$VAR`、`${VAR}`，保留路径中的合法空格。给 Python 子进程传入绝对 `DEEPSEEK_HOME`，避免不同 cwd 使相对路径指向别处。`PYTHONPATH` 使用平台分隔符，修复 Windows 仍使用 `:` 的代码问题。Windows 的 `%VAR%` 路径分支未在真实 Windows 上运行；`~其他用户名` 也不在本轮共同语法保证内。
3. **A3：端点探测与请求实现统一。** 复用实际客户端的协议选择、URL 和 payload 构造；Responses 使用 input/max_output_tokens，Anthropic 和 Chat 保留各自格式。探测输出上限 32 token，关闭推理以降低费用。HTTP 200 但返回错误对象、字段类型错误、failed/cancelled 状态不再报告成功。
4. **A4：批处理消除重复扫描。** 优化读取采用批量索引，清空历史只在整个操作前后测量大小。4 会话场景下轮次读取从 20 次降到最多 8 次，整库大小扫描从 10 次降到 2 次。原有拒绝清理未发布代码、最近写入保护、能力配置保留测试仍通过。
5. **A4 附加真实缺陷：删除单个会话遗漏未索引消息。** 原代码先删除 item_ids 对应文件，随后仍通过 item_ids 查询，无法找到已落盘但未进入索引的消息。改为按已删除轮次 ID 扫描剩余条目；批量清理继续使用自己的全局扫尾，避免每会话重复扫描。复现测试在修复前留下 `unlisted` 文件，修复后只保留其他轮次的 `keep` 文件。
6. **A6 局部：客户端类型声明。** 为 `LLMClient.media_config` 声明真实的 `Config | None` 类型，不再被推断为只能赋值 None；端点工厂的定向 Mypy 检查通过。没有通过关闭规则消除全仓类型欠账。
7. **A9：明确恢复语义。** 保留原行为，用注释和真实 JSON 文件往返测试确认：恢复后 Goal 暂停、累计 token/轮次保留，停滞窗口清零。没有把诊断字段擅自变成恢复控制条件。
8. **A10：说明功能版本边界。** README 说明核心 Python 3.10 声明与浏览器 3.11+ 的差异；核对源码后，CUA 平台入口是 Apple Silicon macOS 与 X11 Linux（Linux 安装为手动），Windows 不接受该入口。未声称已跨平台实测。

### 真实例子与结果

| 场景 | 结果 |
|---|---|
| 真实临时目录，GUI 写文件、独立 Python 进程读并回写 | `~/state`、`$AUDIT_HOME/state`、`${AUDIT_HOME}/state`、带空格路径均通过；不是 mock 路径比较 |
| Python 从另一个 cwd 启动 | 与 GUI 保持同一个绝对数据目录 |
| 真实 loopback HTTP 服务 | 实际收到 Chat、Responses、Anthropic 对应的路径、JSON 与鉴权头；错误 200 被拒绝；协议测试修复前 3 failed，修复后通过 |
| 临时会话存储，经过 Runtime API 清理/优化 | 正确删除/保留真实 JSON 文件，并实测扫描次数；单会话未索引消息清理也有修复前失败证据 |
| 实际 DeepSeek Flash 供应商 | 返回的可用型号是 `deepseek-flash`；端点探测成功（2182ms），第二次流式请求返回准确的 `OK`；流式 usage 为输入 9、输出 1、推理 0 token。共做两次短生成验证，没有调用其他收费模型；未获得第一请求的完整 usage，因此不把 10 token 当作两次总量 |
| 全新临时虚拟环境安装 | 清华镜像 TLS 失败后改用官方 PyPI，安装同一锁文件的 100 个依赖；再安装项目，`uv pip check` 检查 101 个包全部兼容 |
| 新环境实际文件往返 | DOCX 段落、XLSX 单元格、PPTX 页数、PNG 尺寸保存并重新读取均符合预期；浏览器、tokenizer 等新增直接依赖 import 成功 |
| Python 完整非 live/e2e/live_mcp 测试 | **4199 passed，168 skipped，50 deselected**，2 warnings；运行后追加的单会话清理修复另做最终定向回归 |
| 最终 Python 定向回归 | **27 passed**，同一组在全新锁定环境再跑也是 **27 passed**；含最终清理逻辑、端点与 Goal 持久化 |
| 工作台完整测试 | **317 文件 / 2084 测试通过**；随后平台分隔符小改动再跑路径/启动相关测试 **14 passed** |
| 最终前端 TypeScript / 工厂定向 Mypy / diff whitespace | 通过 |

本轮密钥仅通过关闭回显的临时进程输入传入；没有写入项目、配置文件或报告。测试只操作临时数据，没有删除用户真实会话，也没有发送邮件/IM。

### 保留的后续工作

- **A5**：大型模块按业务边界拆分，不与本轮明确缺陷修复混做。
- **A6**：全仓历史类型/lint 欠账及 13 个 React Hook 警告尚未清完。完整 Python 测试的两个警告分别涉及多线程进程中的 `fork()`、事件循环关闭后的 subprocess transport 析构；尚未证明稳定触发路径，不声称已修复。
- **A7**：PSL/私有域名归并涉及依赖、已保存 Cookie 选择语义及迁移，仍保留现状，需要独立变更设计。
- **A8**：遵照保留兼容的选择，没有删除旧接口、历史字段、legacy 数据目录或疑似无用的公开符号。
- **A2 迁移边界**：当前检查所用 shell 未设置自定义 DEEPSEEK_HOME；没有发现需要本机迁移的配置证据。没有自动搬迁旧版本写入字面 `~`/`$VAR` 目录的数据，其他安装若已有这类数据应先确认再迁移。

可重复执行：`make check-lock`，以及 `python -m pytest -q tests/test_endpoint_probe.py tests/goal/test_state.py tests/contract/test_data_inventory.py`（需要本地端口权限）。上述 DeepSeek 联网检查未加入自动测试，避免日常测试反复消耗额度。
