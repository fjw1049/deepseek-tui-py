# DeepSeek TUI Eval Platform

This directory is a behavioral evaluation system, not another unit-test folder.

从项目根目录运行 `make eval-full` 可执行当前注册题集。个人历史子集与旧长跑题库的口径见[复跑入口和数据总账](EVAL_RUNBOOK.md)。

系统级指标、数据覆盖、评分与版本决策见[整套系统评估方案 v1](SYSTEM_EVALUATION.md)。

## 独立 Eval Lab（本地端口 7879）

```bash
bash scripts/dev-eval.sh
# 或 make eval-serve
# 自定义端口：EVAL_PORT=7889 bash scripts/dev-eval.sh
```

打开 http://127.0.0.1:7879 。页面、API、实验进程独立于 Workbench，
不挂载产品聊天/线程路由，不需要启动 Electron 或 7878 服务。
仅监听本机，不支持直接作为公网服务部署。

界面支持：场景选择、实验命名、请求/输出/费用/超时预算、重复试验、
实验提示词补充、停止、历史结果、逐题评分与原始证据、文件 diff、请求/工具轨迹、
证据导出和两次实验对比。运行中的场景结束后逐条更新；重启后保留已有结果，
中断实验不会显示为成功。每次实验单独启动进程，重新加载当前代码。

推荐使用流程：

1. 新建“基线”，选择场景，先运行一次并保留结果。
2. 修改产品代码，或在“实验提示词补充”中填写候选指令；用相同场景与预算新建候选。
3. 在“版本对比”选择 A/B，检查逐题改善、退步与可比性，再查看原始证据。

界面将四类评测分开：

| 范围 | 当前能力 | 边界 |
|---|---|---|
| 离线机制 | 9 个确定性检查 | 不调用模型，不能证明 Agent 任务精度 |
| 单步决策 | 真实模型探针 | 观察一次响应，工具不执行 |
| 真实文件任务 | 3 个真实 Engine 文件任务 | 生产文件工具与工具循环；临时目录；独立 JSON/保护文件验收 |
| 产品任务 | 22 个 `daily_tasks` 场景 | 真实 HTTP 入口、完整工具、持久化；事实检查 + 独立评审 |
| 评审校准 | 10 个 `judge_calibration` 样本 | 用人工构造的好坏结果测评审员本身 |
| 缓存探针 | 1 个 provider 缓存实验 | 人工稳定前缀；不代表真实任务质量 |

真实模型读取现有用户级模型配置与环境变量；Key 不通过页面或导出接口暴露。
未配置可用模型时，“开始运行”明确报错，不会伪造结果。
文件任务只提供 read_file / edit_file / write_file，不运行 Shell、第三方 MCP、插件、
子代理、用户 hooks 或桌面会话生命周期。因此它是受控的真实文件任务评测，
还不能替代完整编程任务、真实摘要压缩策略和前后端恢复流程评测。

提示词补充仅追加到本次真实决策/文件任务的系统提示词，不改产品文件；
离线和缓存实验不接受该字段。页面仍采用先保存基线、再运行候选的流程；
自动冻结版本及 A/A、A/B 交错编排见下面的 `campaign` 命令。
每次运行记录代码、题集、评分器、预算与实际请求指纹。
执行期间检测到源文件变化会标记为不可比较；本版记录身份，尚不提供完整环境快照恢复。

比较按题等权展示成功率变化，拒绝题集/评分器/预算不同、缺题、错误、跳过和中断的实验。
区间是探索性场景重采样估计，不自动宣称统计显著或推荐发布。
费用同时显示已知部分和计费覆盖；未上报用量或未知价格不填零。
成本上限是逐请求检查的软上限，已在途的并发请求仍可能超额；请求额度由并发试验共享。
产品任务的完整费用标记为不完整，已知费用当前仅包含评审；产品请求和 preflight 尚未计价。

## 自动架构实验（campaign）

先将假设、版本、选题、重复次数、预算与判定规则写入 JSON，再执行：

```sh
# 不调用模型：验证整条编排和留档链路。
PYTHONPATH=src:. .venv/bin/python -m evals campaign evals/campaigns/offline-smoke.json \
  --output evals/artifacts/architecture-smoke-001

# 公司批跑模板：先填写公司的 provider/model，再检查预算。共 36 个独立试验。
PYTHONPATH=src:. .venv/bin/python -m evals campaign evals/campaigns/system-pilot.json \
  --output evals/artifacts/architecture-pilot-001

# 已配置公司 endpoint 的本机：执行与评审均使用 deepseek-v4-1-flash。
PYTHONPATH=src:. .venv/bin/python -m evals campaign evals/campaigns/system-company-flash.json \
  --output evals/artifacts/company-flash-001
```

`HEAD` 表示已提交基线，`working-tree` 包含当前未提交及未忽略的新源码；也可填写
具体 Git 提交。命令只读 Git，将两侧产品代码复制到各自的 `sources/`，不切分支、
不提交或覆盖工作区。两侧使用同一份当前评测器和题集；依赖锁不同则停止，避免用
同一个 Python 环境冒充不同依赖环境。快照不含用户配置、凭据、历史产物或 `.git`。

个人账户资金有限，默认只做离线/本机脚本化模型验证及少量冒烟测试。批量真实模型
评测由用户在公司环境发起。`system-pilot.json` 的 provider/model 故意留空；未填写时
会在启动前报错，不会回退到个人默认模型。

每道题每次重复都从新进程和任务初态执行。基线 A、同版本重复 A′、候选 B 的顺序
按种子打乱并交错，所有原始试验保留；不挑最好的一次。`campaign.json` 先记录
规格和完整顺序，随后记录进度；`runs/` 保存每次的轨迹、产物和评分卡，汇总记录的
`artifact_run` 指回原始目录。源码或本地路由配置变化、运行错误、超时和取消均不放行。
在输出目录创建 `STOP` 文件会在当前试验结束后停止调度；Ctrl-C 会终止当前进程组并
保存“证据不足”。不自动续跑或覆盖旧实验，复测使用新目录。
本版使用 POSIX 进程组，适用于 macOS/Linux；Windows 尚未验收。

`worker_timeout_seconds` 限制一次完整试验，`campaign_timeout_seconds` 限制整个
执行阶段。`timeout_seconds` 是产品每轮或其他 runner 的限时。`max_live_requests`
和 `max_output_tokens` 沿用原 runner 的计量范围：产品任务目前只对评审请求使用
该请求计量器，产品服务内部模型循环不受它的全链路硬限制；不能把这些字段当成
整批费用上限。产品用量按实际会话留档，未知费用不填零。

判定结果写入 `decision.json` 和 `report.md`：

| 决定 | 含义 | CLI 退出码 |
|---|---|---:|
| `keep_baseline` | 任务类别或受保护回归题退化，关键检查失败，或虚报增加 | 1 |
| `insufficient_evidence` | 条件不可比、A/A 不稳定、缺题、缺分组、缺封存证据或收益区间不足 | 2 |
| `review_candidate` | 达到事先配置的门槛，可进入人工候选评审；不自动发布 | 0 |

新增用例可记录 `source_group`、`task_family` 和 `split`（development/regression/holdout）。
同源变体必须在同一分区；变体先在来源内平均，再按来源等权估计收益及区间。
来源缺失的旧题仍能诊断，但不能为自动候选判定贡献独立样本。离线、单步决策、
裁判校准与端到端任务分开，前几类通过不会充当任务成功率。
两侧产品源码相同时仅作 A/A 重复，不会因偶然分差进入候选评审。

默认规则要求至少 8 个独立封存来源、两个任务类别、每题 3 次重复，收益区间下界
超过 5 个百分点，类别不得退化，A/A 逐题平均波动不超过 0.15。
这些是保守的**试点配置，不是已经校准的统计保证**；应先通过 A/A 调整下一批规则，
不能看到结果后为当前候选降低门槛。现有 system_v1 的四道示例来自三个开发来源，
即使全过也不会宣布泛化收益。`require_holdout: false` 仅适合开发筛查。
封存标签不证明环境隔离；本机已有进程/目录隔离的边界仍适用，正式封存验收需要
独立准备和控制访问的环境。

对已有结果应用明确的规则（不调用模型）也可使用：

```sh
PYTHONPATH=src:. .venv/bin/python -m evals decide <基线目录> <候选目录> \
  --repeat <同版本重复目录> --policy <规则JSON> --output <新的判定JSON>
```

改评分器时先在原始 `runs/` 留档上复评；重评结果不能直接冒充原条件下的自动放行证据。
自动实验支持来源级比较，尚不代替架构师提出因果假设、审查修改或封存环境管理。

Artifacts 下的 `_jobs` 保存调度状态与本地进程日志；每个 run 下保存 JSONL、summary、
manifest 和 traces。日志不通过网页提供，导出的是脱敏结构化证据。
请勿将包含私人任务内容的 artifacts 上传到公开仓库。

验证命令：

```bash
.venv/bin/python -m pytest tests/evals -q
make eval-typecheck
make eval-offline
node --check evals/web/app.js
```

新增回归覆盖评分误判、缺失证据、失败请求计数、取消落盘、真实 Engine 文件修改、
路径边界、独立 API、跨站请求拒绝、真实离线子进程、历史/导出与比较。

- `src/` implements the product.
- `tests/` proves deterministic code contracts and tests this platform.
- `evals/` measures the combined behavior of prompts, context assembly, models,
  provider serialization, tools, approval policy, compaction, and completion claims.

## 产品任务评测（daily_tasks）

这是判断 harness 改动好坏的主要依据。结构分三段，互相不依赖：

1. **执行**（`evals/harness/product.py`）：每次运行启动一个产品服务，用一次性 home，
   不带用户的 AGENTS.md、skills、插件、MCP；工作区在仓库外。先做一次真实往返
   （preflight），模型不可达就停止，不产生“看起来像行为”的失败样本；连续 3 个回合
   模型请求失败同样停止，超时和无人回答是任务自身的结果，不算环境问题。用户提问 60 秒无人回答视为卡住。
2. **留档**：每个试验的 turns/items/events/transcript 和工作区产物存到
   `sessions/<case>-<id>/`，打分只依赖这份留档。
3. **打分**：`checks` 是可复核的事实，`rubric` 交给独立评审（看要求、答复、产物，
   以及系统统计的运行记录，看不到 harness 状态）。评审不能推翻失败的事实：critical 检查失败即 fail，
   非 critical 检查失败最高 partial。评审回复解析失败记为 error，不算判定。

修改 rubric 或评审后不用重跑 Agent：

```bash
python -m evals regrade evals/artifacts/<run-id>
python -m evals regrade evals/artifacts/<run-id> --reuse-judge  # 只改了确定性检查时不调用模型
```

一次基线（办公类任务常超过 15 分钟，回合上限用 1200 秒）：

```bash
python -m evals run --mode live --suite judge_calibration \
  --provider deepseek --model deepseek-flash --max-live-requests 12 --timeout 120
python -m evals run --mode live --suite daily_tasks \
  --provider deepseek --model deepseek-flash \
  --concurrency 4 --timeout 1200 --max-live-requests 50 --max-input-tokens 150000000
```

`--timeout` 在这里是每回合上限。`--max-input-tokens` 是软上限：达到后不再开始新试验，
在跑的试验会继续。桌面用例设 `input.exclusive: true` 后不与其他试验并行。

`session.*` 指标由 `evals/session_metrics.py` 从留档算出，历史数据走同一份代码：

```bash
python -m evals soak-baseline <thread-store> --output report.json
```

其中命令模式匹配（绕过、安装、sleep）是启发式，只看趋势，不参与判定通过。
界面类用例目前只能看到源码，评审无法真正操作页面。

场景的 `command` 检查在工作区副本里执行 `argv`，不经过 shell。这是对
“用例不含可执行内容”的唯一放宽，因为脚本能不能跑只有运行才知道。

## Commands

Validate the versioned YAML corpus:

```bash
python -m evals validate
```

Run all deterministic suites and write an append-only artifact bundle:

```bash
python -m evals run --mode offline
```

Run and compare against committed hard gates in one CI-friendly command:

```bash
python -m evals run \
  --mode offline \
  --baseline evals/baselines/offline.json
```

Or compare an existing artifact:

```bash
python -m evals compare \
  evals/baselines/offline.json \
  evals/artifacts/<run-id>/summary.json
```

Run opt-in real-provider cases with explicit request, output-token, timeout,
and known-cost budgets:

```bash
python -m evals run \
  --mode live \
  --provider anthropic \
  --model your-model-id \
  --trials 3 \
  --max-live-requests 20 \
  --max-output-tokens 1024 \
  --max-cost-usd 5
```

`--max-cost-usd` is enforced when the product has pricing for the selected
model: scheduling stops after recorded cost reaches the cap, so the final
in-flight request can overshoot it. The request and output-token limits remain
the hard provider-independent budgets. Live mode includes deterministic cases
and is never run implicitly.

## Artifact contract

Every run writes:

- `manifest.json`: commit, dirty-diff hash, dataset hash, prompt hash, tool
  catalog hash, runtime versions, model, and provider.
- `cases.jsonl`: one flushed, redacted record per case trial.
- `summary.json`: aggregate metrics used by baseline comparison.
- `failures/*.json`: isolated evidence for failures and runner errors.

Credentials and common bearer/API-key forms are redacted before persistence.
Raw system prompts are not stored; reports contain hashes and structural
evidence instead.

## Case contract

Cases are data, not executable code. YAML may select only registered harnesses
and graders. Arbitrary Python, shell assertions, dynamic imports, and embedded
judge prompts are intentionally unsupported.

Critical runtime invariants must still have ordinary tests. An eval can measure
how often a model attempts an unsafe action, but only product tests can prove
that the runtime always blocks it.

每次 run 会生成 `scorecard.md`，按入口和套件分开统计首试、复测和未判样本，并链接产品会话。对已有运行执行 `.venv/bin/python -m evals scorecard <运行目录>` 即可补生成，无模型调用；用 `regrade <运行目录> --reuse-judge` 可在原产物上重跑事实检查。[实际校准结果、误判与隔离范围](reports/2026-11-06-eval-integrity.md)。

[个人会话开发集](suites/personal_sessions/README.md)收录从本机 Claude Code、Codex 的真实需求改编的多轮产品任务，附原会话索引、脱敏改动和逐题验收说明。
