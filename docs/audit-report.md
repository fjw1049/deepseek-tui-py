# DeepSeek TUI 代码审核报告

> 审核范围：`src/deepseek_tui/`（约 7.8 万行 Python，8 个功能块）
> 审核日期：2026-08-14
> 审核方式：按功能块逐一深审，所有结论均在源码中核实（文件：行号）

## 数字总览

| 级别 | 数量 |
|------|------|
| 高危 | 19 |
| 中危 | 38 |
| 低危 | ~25（择要记录） |

---

## 一、高危问题（19 条，按主题归组）

### A. 密钥外泄链（同一根因的多个实例，最优先）

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| A1 | `tools/shell.py:1143` | shell 子进程 `{**os.environ, **exec_env.env}` 无差别继承全量环境；`printenv` 在免审批白名单里，模型一条命令即可读出 `DEEPSEEK_API_KEY` 等全部密钥，再用 `curl` 外传 | spawn 前过滤 `*_API_KEY`/`*_TOKEN`/`*_SECRET`，或白名单式注入（PATH/HOME/LANG） |
| A2 | `mcp/transport.py:83` | 第三方 MCP server（不可信二进制）同样继承全量环境 | 同上，只透传配置显式声明的 env |
| A3 | `policy/command_safety.py:85-91` | `printenv`/`set`/`find`（可 `-exec rm`）在 SAFE 免审批白名单 | 移出白名单或升级为 PROMPT |
| A4 | `state/secrets.py` 多处 | 多套旧凭据后端的 fallback 安全性和优先级不一致；项目级配置还可能提供明文 api_key | 删除旧后端，统一为 env → 用户 `config.toml`；项目级配置禁止提供 api_key |

**联动说明**：A1 + A3 + `sandbox.py` 全磁盘可读构成完整外泄链，单修一环不够。

### B. 配置信任（clone 即 RCE）

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| B1 | `config/loader.py:175-184` | 自动加载 cwd 下 `deepseek-tui.toml` / `.deepseek-tui.toml`，无信任提示 | 项目级配置的安全敏感字段默认禁用或首次加载要求批准 |
| B2 | `integrations/hooks.py:356-358,931-944` | 项目级配置可通过 `[[hooks]]` 注入 shell 命令并执行 | 同 B1，hooks 字段隔离 |
| B3 | `config/loader.py` | 项目级配置可改 `approval_policy`/`sandbox_mode`/`base_url`（指向恶意端点窃密钥） | 同 B1 |

**影响**：恶意仓库 clone 下来启动 TUI 即执行任意命令，无需模型犯错。全部审核中影响面最大的一条。

### C. shell 命令分级被解析绕过

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| C1 | `policy/command_safety.py:193,225-235` | 首词靠 `split()[0]`，无 shlex 规范化；`env ls`、路径前缀、引号包裹、赋值前缀均可绕过/误判 | 用 shlex 拆 token 后查表 |
| C2 | `policy/command_safety.py:254-266` | 重定向只认 `>`/`>>`，漏 `<`/`&>`/进程替换；管道 `|` 不进链式分析——`cat a \| dd of=/etc/passwd` 整条判 SAFE | 管道逐段分级；补全重定向变体 |
| C3 | `workspace/shell_write_guard.py:294-302` | `mv`/`cp` 只校验目标不校验源，`mv src/x.py /tmp/` 放行，等同删除源文件 | 源是受保护文件时拒绝或升级审批 |

### D. 引擎配对边界失守

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| D1 | `engine/capacity.py:343` | 压缩把工作集 pin 的消息直接当保留集，pinned assistant 带 tool_call 但配对 tool_result 被摘要丢弃 → 孤立 tool_call，下次 API 400 | 压缩后做配对校验，缺 tool_result 的一并 pin |
| D2 | `engine/orchestrator/tooling.py:516-520` | 并行工具 `asyncio.gather` 无 `return_exceptions=True`，一个异常整批结果丢失 | 加 `return_exceptions=True` 并映射为错误结果 |
| D3 | `server/threads/manager.py:2445-2473` | 多 thread 共享引擎的 `_mutation_sink` 回调被后启动的 turn 覆盖，前一个 turn 的文件变更 ledger 静默丢失 | 回调改多路复用（按 turn_id 路由） |

### E. 服务端暴露面

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| E1 | `server/routes.py:846-847` | `GET /v1/plugins/registry?url=` 接受任意 URL 服务端抓取（SSRF）；webhook secret 未配时放行 | URL 限定 https + 域名白名单，或只走配置项 |
| E2 | `server/runtime.py:464-493` | HTTP 端点对外部 MCP 工具完全跳过审批（引擎路径有审批，此路径绕开） | server 路径同样走审批或按 policy 拦截 |
| E3 | `cli/app.py:269-326` + `server/auth.py:42-50` | `--host 0.0.0.0 --insecure` 无任何校验，公网裸跑带工具执行能力的 API | CLI 层 `insecure and not loopback(host)` 时拒绝启动 |

### F. 客户端与子代理

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| F1 | `client/base.py:76-80` | 流式中断自动重发整请求（最多 5 次），已收 delta 留在 buffer，重发后文本/工具调用重复且二次计费 | 流中出错只发 `StreamError(retryable=True)`，由上层决定重试 |
| F2 | `client/anthropic.py:95-101` | Anthropic 429/5xx 不重试直接抛错，与 DeepSeek 的 pre-stream retry 行为不一致 | 抽共享的 pre-stream retry helper |
| F3 | `tools/subagent/loop.py:404-411` | `input_queue` 只在循环启动前排空一次，主循环内从不消费；`send_input(interrupt=True)` 的 interrupt 标志读出即丢弃——承诺的能力不工作 | 每轮 LLM 调用前排空队列；interrupt 时 set cancel_token |
| F4 | `tools/subagent/loop.py:335-337` + `manager.py:571` | 后台/分离子代理默认 `auto_approve=True`，无审批跑受控工具 | detached 场景默认 False，或仅放行只读工具 |

---

## 二、中危问题（38 条，择要按模块列）

### tools 工具集
- `file.py:74-112`：`read_file` 无字节上限整读入内存，GB 级文件撑爆进程
- `file.py:159-180`：`write_file` stale 检查与原子写之间 TOCTOU，覆盖可被误记为新建
- 写侧无敏感文件检查（`is_sensitive_path` 只挡读不挡写）

### policy / workspace
- `shell_write_guard.py:96-104`：解释器写 API 覆盖不全（漏 `os.remove`/`unlink`/`shutil.move`/`git restore`/`dd of=`）；`.write(` 误杀 `sys.stdout.write(`
- `shell_write_guard.py:80-82`：重定向正则漏左紧贴（`echo hi>f`）与引号路径
- `command_safety.py:124-135`：多行/命令替换的阻断依赖可选策略文件，未配置时无硬阻断

### engine / orchestrator
- `core.py:1432`：子代理成本记账多代理少计、双路径重计（应以 agent_id 去重）
- `capacity.py:545`：压缩触发偏晚（反推不含本轮输出预留，`cache_read` 依赖 client 实现）
- `dispatch.py:107-129`：plan 快速通道纯英文关键词，中文请求永不触发
- `core.py:1337`：`Engine.create` 内 await 审批 handler，handler 挂起则引擎构造卡死

### server / threads
- `approval.py:35-49`：审批 future 无超时，UI 不响应则引擎永久挂起（应超时默认拒绝）
- `approval.py:158-159`：审批 ID = tool_call_id 且出现在事件流，可被伪造批准
- `manager.py`：rewind 不清事件日志（重放悬空引用）；冷线程无法中断；rewind 持全局锁做磁盘 I/O；`_pending_user_inputs` 跨 turn 泄漏

### subagent / task
- `task/manager.py:167-204`：任务队列无上限 + 全量重写落盘，队列一大 O(n²) 阻塞事件循环
- `task/store.py:154-233`：resume 重放副作用型工具调用（at-least-once 无幂等，未声明）
- `task/manager.py:292-325`：取消 RUNNING 任务只是"请求"，阻塞型子进程不会被杀
- `subagent/manager.py:399-403`：父 completion 通知 `except Exception: pass` 静默丢失
- `task/manager.py:667-676`：终态任务驱逐只清内存不删磁盘，磁盘无界增长

### config / secrets / client
- `secrets.py`：旧多后端凭据写入存在进程参数泄露与权限竞态（本轮已删除）
- `deepseek.py:228-241`：429 重试不解析 `Retry-After`
- `chat_messages.py:56-63,87-91`：tool_result 出现在非 TOOL 消息时被静默丢弃但配对校验判完整 → API 400（D1 的客户端层出口未守住）

### mcp / plugins / integrations
- `mcp/transport.py:285-289`：SSE `endpoint` 事件可下发任意跨域 URL，凭据被重定向
- `mcp/transport.py:180,316`：MCP transport 不限 https、无 SSRF 防护
- `plugins/fetch.py:181-192`：npm 插件不校验 `dist.integrity`，tarball 无 checksum
- `integrations/plugins.py:1229-1236`：trusted=true 但无 grant 文件时自动补写授权，弱化信任语义

### cli / tui
- `cli/app.py:269-326`：`--host 0.0.0.0 --insecure` 无校验（E3 的入口端）
- `tui/sanitize.py`（仅 20 行）：名不副实，只剥哨兵标记，终端安全靠 Rich 渲染器隐式转义兜底

---

## 三、修复优先级（按"链"而非按"点"）

### 第一批：安全（1-2 天，互相独立可并行）
1. **环境变量过滤**（A1+A2）：`shell.py` 与 `mcp/transport.py` 两处 spawn 前统一过滤 `*_API_KEY`/`*_TOKEN`/`*_SECRET`，一个 helper 两处调用。
2. **SAFE 白名单收紧**（A3）：移出 `printenv`/`set`/`find`。
3. **项目级配置隔离**（B1+B2+B3+A4-项目级）：安全敏感字段（approval/sandbox/hooks/base_url/api_key）在项目级配置默认禁用或需批准。
4. **`--insecure` + 非 loopback 拒绝启动**（E3）。

### 第二批：正确性（本周）
5. 并行工具 gather 加 `return_exceptions=True`（D2，一行修复）。
6. 压缩保留集做 tool_call/tool_result 配对校验（D1）。
7. `send_input` 主循环消费 + interrupt 生效（F3）。
8. 客户端重试统一：流式不重发整请求、Anthropic 补 pre-stream retry（F1+F2）。

### 第三批：结构性（需排期）
9. shell 命令分级从正则升级到 shlex token 树（C1+C2+C3 根治）。
10. `threads/manager.py`（4164 行）拆分为 turn 执行器 / 持久化 / 广播三个协作对象（D3 及一批中危根治）。
11. `sanitize.py` 做真正的终端过滤（C0/C1/OSC/CSI）。

---

## 四、做得好的设计（值得保留）

- **插件授权体系**：sha256 内容摘要授权、防 zip slip、符号链接拒绝、无"trusted 但无文件"旁路——教科书级。
- **主循环骨架**：多层轮数上限、中断不落盘 partial 历史（从设计上规避孤立 tool_call 落盘）、并行批次限定只读工具。
- **命令执行**：无 `shell=True` 拼接、killpg 杀整个进程组、后台进程上限清理。
- **认证骨架**：token 不可预测（256 bit）、默认 loopback、默认拒绝、无 CORS。
- **secrets 主路径**：环境变量优先，其次用户 `config.toml`；日志不输出 key 值。

---

## 五、一句话总评

主路径设计普遍合格，失效全部集中在**边界和 fallback**：环境变量在每次 spawn 的边界、配置在"用户级 vs 项目级"的边界、压缩与并行在"配对"的边界、secrets 在每条 fallback 路径。修复方向不是加强主路径，而是把每条边界当主路径一样对待。
