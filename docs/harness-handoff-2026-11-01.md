# Harness 优化交接（2026-11-01）

给接手继续优化的 session。先读本文，需要细节再查第 2 节列的文件。

## 0. 最新状态（2026-11-01 晚，优先于下文）

**先读 `evals/reports/2026-11-01-holdout-audit.md`。** 下文第 1、3 节是这之前写的，已部分过期。

- **最终代码已全量跑过。** `daily_tasks` 15/22（68.2%）。新建的留出集 30 题，通过率 53.0% → 73.3%，噪声约 ±10%。
- **第 3 节第 2、3（部分）、4 项已完成。** “轮次 +19%、token +26%”经旧批次重复运行确认是噪声。
- **还没解决：** 如实率、虚报率没有改善；封存组单看不显著；`fill` 修复没有经过真实运行。
- **工作区不止这一个 session 在改。** 评测期间另一个 session 改了 `src/deepseek_tui/browser/` 的录制功能，工作区改动已到 160 个。合入只用窄补丁，不要整文件覆盖，运行前后看 `source_changed_during_run`。
- **soak 数据已不怕丢。** 完整内容在 `~/Desktop/未命名文件夹/agent-results-2026-10-29-to-30.zip`（只读）。解压后 `runtime/main` 就是 `load_sessions` 能读的目录，`replay_184.py` 改这个路径即可。
- **评测沙箱用 `workspace-write`。** `danger-full-access` 加自动批准会被 Claude Code 的权限审查拦下。
- **余额 ¥3.73。** 有效单价约 ¥0.13/M 输入 token，留出集一遍约 ¥10，`daily_tasks` 一遍约 ¥5。用过的 key 已在聊天记录里，应作废，下次重新要。

## 1. 当前状态

阶段二、三的主体已完成，全部在 `build_1024` 工作区，**未提交**，基于 `4c25f913`。不要 reset、stash 或覆盖：142 个改动里阶段一和阶段二混在一起，没有分批。

测试：全量 3885 通过、0 失败；真实 Chrome 192 通过（`DEEPSEEK_BROWSER_E2E=1`）；live 16 通过（要有效 key，否则跳过）。

### 评测结果

口径：`stage2-combined` 与基线都用 `regrade --reuse-judge` 换成同一份检查。

| 指标 | 基线 | 现在 |
|---|---|---|
| 通过率 | 54.5%（12/22） | 63.6%（14/22） |
| 如实率 | 59.1% | 68.2% |
| 虚报率 | 18.2% | 13.6% |
| 答复丢失 | 0 | 0 |

这张表**不含**之后的改动。之后只有小范围验证：

| 运行 | 内容 | 结果 |
|---|---|---|
| `office-check` | 5 个办公和 goal 用例 | 5/5 通过。当时用了一次性 HOME，环境与最终代码不完全相同 |
| `prompt-slim-check` | 第一版精简提示词，9 个用例 | 6 通过。`logs` 失败是检查写死 `*.md`（已修），`web_app` 失败是 HOME 问题（已修），`long_context` 见下 |
| `lc-full` / `lc-slim` / `lc-mid` | `long_context` 三个提示词版本 | 完整版 3/3，第一版精简 2/3，**当前版** 4/4 |
| `final-web-app` | 最终代码跑 `web_app` | 通过，519 秒 |

证据强度有限：没有 A/A，用例基本只跑一次，`stage2-combined` 当天接口偏慢。**最终代码从未全量跑过。**

## 2. 数据和文件

| 内容 | 位置 |
|---|---|
| 设计方案、各项状态、已知未解决 | `docs/harness-stage2-3-plan.md`（“进度”一节） |
| 阶段一审计、笔记数字复核 | `evals/reports/2026-10-31-stage1-audit.md` |
| 笔记和优化理念 | `~/Desktop/未命名文件夹/` |
| 正式基线 | `evals/artifacts/baseline-stage1-final`，新口径在其 `regrade-20261101-073912` |
| 全量 B | `evals/artifacts/stage2-combined`，新口径在其 `regrade-20261101-073915` |
| 小范围验证 | `evals/artifacts/{office-check,prompt-slim-check,research-check,lc-*,final-web-app}` |
| 不能当对照的运行 | `baseline-2026-10-31-flash`、`-capfix`、`baseline-stage1-flash` |
| soak 原始数据 | `/private/tmp/soak/agent-soak-2026-10-29`（739MB，先读 `START-HERE.md`） |
| 回退备份和回放脚本 | `.claude/worktrees/stage2-patches/` |

- **soak 数据在 `/private/tmp`，没有进版本管理，可能被系统清理。** 里面有 449 个任务 session、4 个诊断 session，含其他模型；Qwen 的 233 条记录已标为不可用于模型对比。此前只分析过 `canonical-runtime/deepseek-v4-1-flash`（211 个 session），其他模型的数据没有审计过。
- `evals/artifacts/` 和 `.claude/` 都被 git 忽略，只在这台机器上。
- 回退：`main-before-merge.tgz`、`main-diff-before-merge.patch`、逐项 patch。**合回之后的改动没有单独 patch**，包括旁白删除、提示词精简、评审和检查的调整。提示词原版是 `base.before-3.4.md`。
- 离线回放不花钱：`prune_offline.py <artifacts目录>`、`replay_184.py`（读 soak，路径写死）。

## 3. 下一步

按顺序：

1. **决定提交方式**，由用户定。还没提交就别做大改动。
2. **全量跑一次最终代码**，约 ¥5。这是目前最大的验证缺口，退步要先在这里暴露。
3. **用新评审重判基线**：`regrade` 不带 `--reuse-judge`。评审材料改过（产物上限 24K、加运行记录），新运行和旧判定不可比。
4. **查轮次和 token**：配对 14 个用例轮次 +19%、输入 token +26%，方案“轮次下降”未达成，原因未明。先做 A/A 量噪声，否则分不清是波动。
5. **研究类**：`public_research`、`software_research` 仍是 0.5，关键事实没写来源。提示词加一句无效，已撤回。查到的来源要怎么进入答复，需要换思路。
6. **继续瘦身**：`base.md` 18.7KB（目标 ≤12KB），`browser.md` 17.5KB 未动，后者要靠 UI 用例验证。
7. **3.1a 有效窗口**：需要专门的长上下文用例。B 的最大请求约 45 万字符。
8. **审计 soak 里其他模型的数据**，如果用户要做模型对比或按模型维护提示词。

已决定不做，除非数据变了：单独的“提前结束”门控（36 回合出现 1 次）；CUA 排队（现状已有等待和交接，那 28 次错误主要来自并行）；2.3 的自动恢复（合法移动也会被撤销）。

## 4. 踩过的坑

- **不要替换 HOME。** 一次性 HOME 下 Chrome 访问本地页面卡 30 秒。隔离用户 skill 用 `evals/product_server.py` 的 `hide_user_skills`。
- **评测用 `caffeinate -ims`，不要合盖。** 有一轮因电脑睡眠作废。
- **评测期间不要改 `src`、`evals`**，否则 `source_changed_during_run` 为真，运行作废。并行开发用 worktree。
- **`session.input_tokens` 对超时用例记 0。** 均值不能直接比，要配对。
- **检查别写死 `*.md`。** 有了办公库后模型会交 docx。这是合理行为，也可能让任务变重（`goal_execution` 曾因此超时）。
- **精简提示词要测判断力。** `long_context` 这种要发现隐含冲突的用例最敏感，其他用例看不出来。第一版精简就栽在这里。
- **删东西先读提示词历史。** “重读最后一段”8 周前被删，后来又要加回来；`record_tool_result` 里有续跑依赖的计数器。
- **用真实数据回放。** `cd inbox && rm x` 和 `cd "$PWD"` 这两个漏洞都是回放真实命令才发现的。
- **uv 走清华镜像时要直连**：`NO_PROXY='*' no_proxy='*' uv sync --inexact`。
- **macOS 没有 `timeout` 命令。**

## 5. 怎么跑评测

key 不在机器上，找用户要，写到 session scratchpad 的临时配置（权限 600），用完删除，不进仓库，也不写 `~/.deepseek/config.toml`。配置模板见方案 1.2。之前在聊天里给过的 key 应已作废，不要从记录里取用。

最后查询余额 ¥0.40。一次全量约 ¥5，单个 UI 用例约 ¥1，`long_context` 每次约 ¥0.04。**全量前先确认余额**，查询方式见方案 1.2。

```bash
export DEEPSEEK_CONFIG_PATH=<临时配置> PYTHONPATH=src:.
caffeinate -ims .venv/bin/python -m evals run --mode live --suite daily_tasks \
  --provider deepseek --model deepseek-flash \
  --concurrency 4 --timeout 1200 --max-live-requests 50 --max-input-tokens 150000000 \
  --label <名字> --output evals/artifacts/<名字>
.venv/bin/python -m evals compare-runs <A> <B>
.venv/bin/python -m evals regrade <run> --reuse-judge   # 只改确定性检查时，不调用模型
```

单个用例加 `--case daily.xxx`，多次加 `--trials N`。

## 6. 工作约定

- 用户用中文交流。提交、推送要用户明确要求。
- 判断规则见《我对这套 harness 的优化理念和方案》第三节：代码能确定的在代码里做，语义判断交给模型或循环外；只有不可逆才阻断；每个拒绝配一条可走的路；每个机制要有日志和下线条件。
- 改动没有指标支持就撤回，来源规则就是这样撤的。
