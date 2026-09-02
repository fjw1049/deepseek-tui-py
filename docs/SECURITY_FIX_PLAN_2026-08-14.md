# 安全修复方案（src 功能审核汇总）

> 日期：2026-08-14  
> 范围：`src/deepseek_tui/` 按功能域审核  
> 不含：CLI 安全相关 flag 未接线（产品确认：只是预留，不算问题）  
> 不含：性能 / 重构 / 优化（后续另议）

本文只谈**正确性与安全围栏**。每条写清：现状、建议改法、验收、不要做什么。你审完再决定改哪些。

---

## 怎么用这份方案

1. 先看「致命」6 条，逐条表态：修 / 不修（产品就是这样）/ 改描述后降级。
2. 再看「接近致命」和「刻意未列入致命」。
3. 确认后再开工。**不要和优化混在同一批。**

建议开工顺序（若 6 条都要修）：**A1 → A2 → A3 → A6 → A4 → A5**，然后 B，然后 C。

---

## A. 致命（6 条）

### A1. 工作区配置能抬高安全档位

**现状**

加载顺序：用户配置 → 项目 `.deepseek/config.toml` merge → cwd `.env` 写入环境变量 → 环境变量覆盖一切。cwd 的 `deepseek-tui.toml` 还会**整份替换** `~/.deepseek/config.toml`。

仓库里写 `approval_policy = "auto"` 或 `.env` 写 `DEEPSEEK_APPROVAL_POLICY=auto`，在该目录启动即全信任。

**建议改法**

- 安全相关键做成**项目配置黑名单**（项目 toml / 工作区 `.env` 都不可覆盖）：
  - `approval_policy` / `sandbox_mode` / `allow_shell`
  - `api_key` / `base_url` / `providers.*.api_key` / `providers.*.base_url` / `providers.*.extra_headers` / `providers.*.extra_body`
  - `features.automations`
  - `hooks.*`（见 A4）
- `~/.deepseek/config.toml` 始终做底座；cwd / 项目文件只 overlay **非安全**项。
- 发现项目试图改安全键时打 warning，写明「已忽略」。

**验收**

- 仓库 `.deepseek/config.toml` + `.env` 写 `auto` / `danger-full-access`，启动后生效策略仍是用户主配置。
- 用户主配置的 `on-request` 不被项目改掉。

**不要做**

- 不要删项目配置能力（模型、locale、instructions 仍可 overlay）。
- 不要在这一步做配置系统重构。

---

### A2. `auto` 不再等于关沙箱、拆掉路径围栏

**现状**

`approval_policy in (auto, never-ask, yolo)` → `trust_mode=True` → Seatbelt `danger-full-access`，且 `resolve_path` 不再限制工作区。

**建议改法**

- 审批档位和沙箱档位拆开：
  - `auto`：只跳过提示，默认仍 `workspace-write`，`resolve_path` 仍限制工作区。
  - `trust_mode` / `danger-full-access`：必须用户在**用户级**配置里显式打开，项目配无效（A1）。
- `Config` 若需要 `trust_mode`，做成显式字段，不要从 `auto` 推导。

**验收**

- `approval_policy=auto` 时：不问工具，但 `write_file("/etc/passwd")` 仍拒；Linux/macOS 仍按 `workspace-write` 策略走（能沙箱就沙箱）。
- 用户级显式 `sandbox_mode=danger-full-access` 时行为与现在一致。

**不要做**

- 不要改 Workbench「少弹窗」文案之前先改语义而不通知 UI。改完需要同步设置页说明：少弹窗 ≠ 全盘可写。

---

### A3. `task_create` 不能一次批准换一条高权限后台代理

**现状**

用户批准一次 `task_create` 后，任务默认 `auto_approve=True`。模型还可传 `mode=yolo`、`allow_shell=true`、`workspace` 任意绝对路径（只做 `Path(...)`，不校验）。

**建议改法**

- `auto_approve` 默认继承**当前会话**档位，不要默认 `True`。
- `workspace` 必须落在当前工作区内（resolve 后 `relative_to`）；越界拒绝。
- `mode=yolo` / `allow_shell=true` / `trust_mode`：**模型不可自行升级**，只能继承会话。程序化入队（自动化运行时）可走内部 API，不进工具 schema。
- schema 里删掉或忽略模型传入的提权字段（注释已写「不要让模型自提权」，实现要对齐）。

**验收**

- `task_create(workspace="/", mode="yolo", allow_shell=true)`：workspace 拒；mode/shell 不升。
- 主会话 `on-request` 时，后台任务写文件 / Shell 仍要桥回主会话审批（或明确失败，而不是静默 auto）。

**不要做**

- 不要为了「没人值守」继续默认免批。无人值守应走自动化产品档 + 用户级开关，而不是工具默认值。

---

### A4. 项目 Hook 不能变成启动 RCE

**现状**

Hook 用 `create_subprocess_shell(hook.command)`。项目 `config.toml` 的 `[[hooks.hooks]]` 无 grant，启动即执行。

**建议改法**

- 与 A1 一起：项目配置忽略 `hooks.*`。
- 只加载用户级 `~/.deepseek/config.toml` 和已 grant 的 plugin hook。
- 保持 `create_subprocess_shell` 可以（用户自己写的 hook 本来就是 shell），但来源必须可信。

**验收**

- 仓库 toml 带恶意 `session_start` hook，启动不执行该命令。
- 用户主配置里的 hook 仍执行。

**不要做**

- 不要这一步重写整套 hook 方言 / Claude 兼容层。

---

### A5. `extra_body` / `extra_headers` 不能劫持请求

**现状**

`payload.update(request.extra_body)` 在填好 `messages` / `tools` 之后，可整包替换对话。`extra_headers` 写在 `Authorization` 后面，可盖掉 Key。

**建议改法**

- `extra_body` 禁止覆盖：`messages`、`tools`、`tool_choice`、`model`、`stream`。
- `extra_headers` 禁止覆盖：`Authorization`、`x-api-key`、`Cookie`。
- 项目配置本就不能带这些键（A1）；用户级自定义 endpoint 仍可用 `extra_body` 做温度等扩展，但不能改对话本体。

**验收**

- 用户级 `extra_body.messages = [...]` 被忽略或启动时报错。
- `extra_headers.Authorization` 被忽略，实际仍用 SecretsManager 解析出的 Key。

**不要做**

- 不要禁止所有 `extra_body`（自定义厂商字段还要用）。

---

### A6. 写工具也要挡敏感路径

**现状**

`read_file` / grep / file_search 走 `is_sensitive_path`；`write_file` / `edit_file` 不走。Agent 可改工作区 `.env` 写入 `DEEPSEEK_APPROVAL_POLICY=auto`，下次启动走 A1。

**建议改法**

- `write_file` / `edit_file` 同样拒绝敏感 basename（与读名单一致）。
- 若产品需要「用户明确要求改 `.env`」，走单独确认，而不是静默写。
- 名单可小幅补：`secrets.json`、`id_rsa_*` 等（别做成万能 glob）。

**验收**

- `write_file(.env)` / `edit_file(.env)` / 写 `id_rsa` 失败。
- 读侧行为不变。

**不要做**

- 不要在这一步给 Shell 做完整敏感拦截（那是 B2）；先堵住文件工具这条持久化通道。

---

## B. 接近致命（3 条，第二批）

### B1. Linux：不要假装有 OS 沙箱

**现状：** `workspace-write` 无 Seatbelt 时只 warning，Shell 照跑。

**建议：** `doctor` / 设置页明确「OS sandbox: unavailable」。非 darwin 上 Shell 至少复用工作区路径约束，或默认把 Shell 审批保持 REQUIRED 且不可被项目改掉（A1）。不要只靠日志。

**验收：** Linux 上 `doctor` 可见不可用；文档与 UI 一致。

### B2. macOS Seatbelt：收紧读 + 敏感路径对 Shell 也拦

**现状：** `has_full_disk_read_access()` 恒 `True`，默认 `network_access=True`。`cat ~/.ssh/id_rsa` 不受 `is_sensitive_path` 约束。

**建议：** 默认只读工作区 + 必要系统路径（`/usr/lib` 等已有）。敏感 basename 在 `exec_shell` 的命令文本里做保守拦截（假阳性只会多一次拒绝）。联网保持现默认或改成「审批过的命令才带网」——这点你审的时候拍板。

**验收：** 默认策略下 `cat ~/.ssh/id_rsa` 被拒或 Seatbelt 读不到家目录密钥。

### B3. 自动化入站：空 secret 拒、test-send 锁死目标

**现状：** `--insecure` 时本机任意进程可打 `/v1/automation/feishu/inbound`（`run_agent=true`）和 `*-test-send`（发到请求体任意目标）。`DEEPSEEK_FEISHU_WEBHOOK_SECRET` 为空则不做校验。

**建议：**

- 入站：无 webhook secret → 401，不要「没配就放行」。
- `test-send`：只允许配置里的默认 `chat_id` / `mail_to`，请求体不能改目标。
- `--insecure` 是否覆盖入站，由你拍板；方案倾向：**insecure 只管 Workbench UI，入站仍要 secret**。

**验收：** 空 secret 打 inbound 失败；test-send 改目标失败。

---

## C. 刻意未列入致命（第三批）

这些是真问题，单独通常打不穿，但会扩大 A/B 的伤害。A/B 落地后再修。

| ID | 问题 | 建议改法 | 验收 |
|----|------|----------|------|
| C1 | 审批指纹丢掉所有 `-`/`--`：`git push` 记住后放行 `--force`；`rm`≡`rm -rf` | 指纹保留会改变语义的 flag（`-f` `-r` `-rf` `--force` `--no-verify` 等） | 测：session 批 `git push` 后 `git push --force` 仍要问 |
| C2 | `cron_create` 指纹是固定 `tool:cron_create` | 纳入 `name` + `schedule` / `run_at` | 批任务 A 不能放行任务 B |
| C3 | `fetch_url` 不挡回环 / 链路本地 | 拒 `127.0.0.0/8` `10/8` `172.16/12` `192.168/16` `169.254/16` `::1` | `http://127.0.0.1:7878` 失败 |
| C4 | MCP SSE `endpoint` 接受任意绝对 URL（带用户 headers） | 必须与 `base_url` 同 origin | 绝对 URL 指向其它 host 则拒 |
| C5 | MCP stdio 继承整份 `os.environ` | 环境变量白名单 + 配置里显式 `env` | 子进程默认看不到 `DEEPSEEK_API_KEY`，除非 mcp.json 显式传 |
| C6 | `cron_create` 的 `delivery.to` 由模型填 | 只允许配置白名单（默认飞书 chat / `mail_to`） | 模型填陌生 chat_id 失败 |
| C7 | Seam / cycle 摘要可能编造「用户已同意」 | 提示写明摘要不可靠；敏感工具结果不要进归档原文 | 打开 context 时仍以 verbatim 窗口为准（正确性，非权限） |
| C8 | `_has_api_key` 与主凭据解析链不一致 → task/subagent 走 stub | 与主路径一样走 `SecretsManager.resolve_api_key` | 只有 config、无 env 时后台任务仍走真模型 |
| C9 | `untrusted` 比 `on-request` 更松（写文件不问） | 改名 `sensitive-only`，或让 `untrusted` 更严 | 设置页文案与行为一致 |
| C10 | `command_safety` 按首词放行（`find -exec` 等）；Starlark `PolicyParser` 未接线 | `find` 带 `-exec/-delete` 升档；未接线的 Starlark 标明或删文档 | 不给「写了 prefix_rule 就会生效」的假安全感 |
| C11 | 旧文件凭据后端先写后 chmod，且可能回退到 cwd | 删除旧后端，统一原子写入 `config.toml` | cwd 不再出现额外凭据文件 |
| C12 | 每次工具调用把完整 `session_messages` 塞进 `metadata` | 只在 `fork_context` 需要时拷贝，不要挂在共享 metadata | 普通工具读不到整段对话 |

---

## 明确不做（本方案范围外）

- CLI `--api-key` / `--approval-policy` / `--sandbox-mode` 接线（已确认预留）。
- 配置系统大重构、Hook 方言重写、自研 Linux 内核沙箱。
- 性能、上下文压缩效果、TUI/Workbench UI 美化。
- 删掉项目配置（只限制安全键）。

---

## 批次与依赖

```
第一批（致命）     A1 ──┬── A2
                       ├── A4（依赖 A1 的项目配置过滤）
                       ├── A5（依赖 A1 的 extra_* 过滤 + 客户端硬拒）
                       └── A6
                  A3（独立，可与 A1 并行）

第二批（接近致命） B1 B2 B3   （A2 定稿后再动 B1/B2，避免沙箱语义打架）

第三批（扩大伤害） C1–C12     （A/B 合上后再做，避免指纹/SSRF 和总开关重复劳动）
```

**A1 是总开关。** 不先做 A1，A4/A5 的项目侧仍能绕。A3 不依赖 A1，可并行。

---

## 你审的时候需要拍板的 4 个产品问题

1. **`auto` 的产品含义：** 只是少弹窗，还是「我信任这台机器」？方案按前者修（A2）。若你要后者，A2 降级，但 A1 仍必须做（项目不能替用户宣布信任）。
2. **后台任务没人值守时：** 失败返回、桥回主会话审批、还是单独的「允许无人值守」用户开关？方案按「继承会话 + 禁止模型自提权」（A3）。
3. **`--insecure` 是否包含自动化入站？** 方案倾向不含（B3）。
4. **Seatbelt 默认是否允许出网？** 方案倾向先收紧读（B2），出网你定。

---

## 对照：审核时的功能域

| 域 | 致命落点 | 非致命落点 |
|----|----------|------------|
| 1 配置启动 | A1 | C8 C11 |
| 2 LLM 客户端 | A5 | — |
| 3 引擎循环 | — | C12 |
| 4 上下文记忆 | — | C7 |
| 5 审批沙箱 | A2 | C1 C2 C9 C10 |
| 6 工作区 | A6 | C3 |
| 7 子代理/任务 | A3 | — |
| 8 扩展 | A4 | C4 C5 |
| 9 自动化 | — | C6；入站见 B3 |
| 10 会话/API | — | B3（insecure） |

CLI 预留 flag：不在本方案。
