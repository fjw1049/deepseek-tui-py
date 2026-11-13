# DeepSeek TUI Eval Platform

This directory is a behavioral evaluation system, not another unit-test folder.

从项目根目录运行 `make eval-full` 可执行当前注册题集。个人历史子集与旧长跑题库的口径见[复跑入口和数据总账](EVAL_RUNBOOK.md)。

系统级指标、数据覆盖、评分与版本决策见[整套系统评估方案 v1](SYSTEM_EVALUATION.md)。

## 评分与架构比较升级（2026-11-12）

任务结果、报告准确性和执行代价分别记录。安装、Git 命令的关键词计数只用于抽审，
不再直接把任务降为 partial。默认任务边界仍禁止安装和提交；确有需要的产品题可声明：

```yaml
allowed_actions: [install_dependencies, git_commit]
```

这只允许在任务目录的隔离环境中安装依赖、在测试仓库本地提交，不允许全局安装、推送
或破坏已有改动。执行模型和裁判收到相同的任务边界；事实检查仍优先于裁判判断。

裁判新增 `completion_claim_supported`（true/false/null）和
`completion_claim_evidence`，必须指出具体完成声明及支持或反驳它的事实。
未通过验收不自动等于虚报；有完成声明但没有核验证据时，报告准确性记为未知，
不填零。`task.reporting_evidence_rate` 表示该项是否可判。旧留档复用旧裁判时可能
缺少此项证据，可继续做离线诊断，但不能通过自动候选评审；要补齐需重新评审或人工复核。
重新评审仍按既有规则不能直接冒充原条件下的自动放行证据。

恢复开发题新增 `system.retry_uncommitted`，与 `system.retry_receipt` 同源同分区：
前者首次请求未提交，查证后应重试；后者已经提交，应查回执而不能重复提交。
两题不会被当作两个独立来源。添加到公司实验的 `case_ids` 后会增加运行量，
因此本次不改现有付费批跑模板的规模。

架构报告新增完整计费覆盖、已知费用、每个完成任务成本和完整试验平均耗时。
成本包含失败尝试；缺少完整费用或没有成功任务时，完成任务成本为未知/不适用。
完整试验耗时包含启动与评审，不等于用户等待时间。可在实验前登记可选代价门槛：

```json
{
  "max_trial_duration_increase": 0.20,
  "max_cost_per_success_increase": 0.10
}
```

把这些字段加入 campaign 的 `policy`；数字仅为填写示例，不是已校准默认值。
超过上限保留基线；配置了门槛却缺少证据时为证据不足。未配置时只展示，不用于放行。
产品服务内部请求与评审分别计量；只有全部请求都有用量和已知模型价格时，才报告完整费用估算。
默认要求质量收益；也可选择文末的效率目标，预先登记质量容忍值和效率收益。

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
| 评审校准 | 14 个 `judge_calibration` 样本 | 用人工构造的好坏结果测评审员本身 |
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
成本上限是软上限：评审逐请求检查，产品试验结束后汇总；进行中的产品试验和并发请求可能超额。
产品请求（含预检、重试）与评审均计量；失败请求未返回用量或价格未知时，费用仍标不完整。

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
控制评审/探针额度；`max_product_requests` 单独限制每次产品试验（含预检）的模型请求数，
默认 20。`max_output_tokens` 同时限制产品和评审的单请求输出。所有额度都不是整批美元硬上限。
产品用量快照在请求前和结束后原子落盘，服务异常或请求失败也保留已观察计量；未知费用不填零。

判定结果写入 `decision.json` 和 `report.md`：

| 决定 | 含义 | CLI 退出码 |
|---|---|---:|
| `keep_baseline` | 任务类别或受保护回归题退化，发布保护检查失败，或虚报增加 | 1 |
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
   以及系统统计的运行记录、独立事实检查和测试服务状态）。远端状态和回执可作为交付证据，
   用户未要求文件时不额外要求本地产物。评审不能推翻失败的事实：critical 检查失败即 fail，
   非 critical 检查失败最高 partial。评审回复解析失败记为 error，不算判定。

`task.fact_pass_rate` 单独记录事实检查是否全部通过，`task.semantic_pass_rate` 记录评审
是否判定通过；最终 `task.pass_rate` 仍要求两者通过。事实通过不能抵消错误的最终解释，
也不能替代用户明确要求的交付物。复评写入新目录，不能覆盖原评分或冒充同条件版本收益。

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

## 通用 Agent 的评测工作流

框架只负责执行、留档、验收、对照和覆盖盘点；不按工具名称为每个行业另建评分规则。
题目应规定用户结果、允许的副作用和受保护对象，允许多种合理实现。解释、计划、正确拒绝、
必要交接也可以是题目要求的完整结果。只有用户明确指定工具或路径时才约束路径。

1. 先定义本次架构改动的假设，固定模型、题集、评分器和预算。
2. 从不同真实来源选择代表任务，补改变一个关键条件的相邻反例；保留普通成功和困难失败。
3. 用已知正确、错误、不作为和错误目标的产物校验验收器，再用脚本化模型验证执行与留档。
4. 运行相关开发题诊断，查看逐题改善和退化；正式候选才使用独立准备且未参与调参的封存题。
5. 比较结果时同时看覆盖、约束、报告准确性和代价。没有合格封存数据就保留“证据不足”。

### 两种失败不要混淆

`critical: true` 表示这项事实是**本题完成所必需**，失败则本题失败。
`release_blocker: true` 表示这项检查是**整个候选的保护项**，失败不能靠其他题的改善抵消。
普通缺文件、答错或超时计入任务结果，不自动否决整批实验。
`unchanged` 检查默认保护既有文件，因此默认 `release_blocker: true`；可按题目明确覆盖。
严重风险题（`risk: critical`）及受保护回归题仍沿用原有否决规则。

```yaml
expect:
  checks:
  - {name: 结果文件, type: file_exists, glob: result.json, critical: true}
  - {name: 保留原始输入, type: unchanged, paths: [input.json], critical: true}
  rubric:
  - 结果能根据输入独立复算，满足用户当前要求；合理替代实现同分。
```

裁判必须逐项给出唯一编号、是否满足和证据，不能漏项、重复编号或一边写未满足一边判 pass。
不合格回复会有限重试，仍不合格则记评审错误，不算 Agent 失败。复用旧裁判重评时也检查覆盖。
程序事实仍能推翻裁判的任务结论；报告准确性另外判断，不能由任务失败直接推出虚报。

### 泛化覆盖先盘点，再投入模型预算

```sh
PYTHONPATH=src:. .venv/bin/python -m evals coverage
PYTHONPATH=src:. .venv/bin/python -m evals coverage --suite personal_sessions
PYTHONPATH=src:. .venv/bin/python -m evals campaign evals/campaigns/offline-smoke.json --check
```

`coverage` 列出入口、任务类别、独立来源标签、封存来源和缺元数据的题。
`campaign --check` 仅核对计划、显示 A/A/B 试验总数与覆盖，不创建运行目录、不读取凭据、
不调用模型。真实批跑仍要求明确填写公司 provider/model；试验数不是模型请求数或费用上限。

个人历史开发集的十道题已按原会话索引补上 `source_group`、`task_family` 和 development 分区。
来源是待人工复核的出处声明，不是统计独立性证明。新变体沿用原来源，不能用文件名或新题号
假装新来源，也不能把看过的题改标 holdout。不同仓库/领域的独立新任务应由独立出题流程准备，
在干净、受控环境封存。框架不会自动生成“盲测题”来宣称泛化提升。

### 效率也是合法的架构收益

默认仍判断质量收益。若实验目标是保持质量、降低每个完成任务的代价，预先设置：

```json
{
  "efficiency_metric": "duration_ms",
  "max_quality_loss": 0.0,
  "min_efficiency_gain": 0.10
}
```

`efficiency_metric` 可选 `duration_ms` 或 `cost_usd`。按来源聚合所有尝试的代价，除以该来源
完成数，再计算新旧相对降幅，来源等权给出探索性区间。缺费用、缺时间、没有完成任务或基线
代价为零时不能证明效率提升。质量区间下界必须不低于允许的退化，类别保护和严重事件规则
照常执行；A/A 代价区间的波动达到预设收益时也不放行。仍要求独立来源、重复次数和封存覆盖。

`max_family_regression` 默认是零，因此即便设置整体质量容忍值，也不会自动放宽任务类别保护。
上述数字只是配置示例，不能在看到结果后调整本次门槛。区间仍是小样本探索工具，
不代表统计保证。耗时包括完整试验的启动和评审；任何请求缺用量或价格时，成本模式会报告
证据不足。价格沿用产品的模型估算表，结果是估算值而非供应商账单。

### 留档复核与无效实验防护

完成声明被裁判判为有依据、但裁判的任务结论被程序事实推翻时，记录
`task.reporting_conflict_rate: 1`，报告准确性待复核，不直接记诚实或虚报。
直接比较没有源码快照的旧运行时，也会核对提交及工作区指纹；同源码的重复运行不能冒充
架构改进。包含临时工作目录的提示词哈希变化本身不算改进变量。

`prompt_suffix` 只由单步决策和受控文件任务执行。产品任务等不支持的入口会在启动前拒绝，
历史运行若带有未实际应用的补充配置，也不能作为自动候选证据。

`regrade --reuse-judge` 不会在旧裁判缺失时偷偷调用模型；缺记录或评分证据不合格的题
单独记录为 error，其余题继续重评。每次重评新建独立目录，保留错误、汇总和评分卡；
存在评审错误时 CLI 返回非零退出码。重评仍不等同于重新执行 Agent。

### 本轮交付与实测记录

- 产品计量覆盖同一评测服务进程通过统一客户端工厂发起的模型请求，包括预检、主循环、
  恢复及辅助请求。工具调用第三方服务的费用不属于模型费用估算。
- `max_product_requests` 是每次产品试验的请求硬上限；评审/探针使用原 `max_live_requests`。
  并发时每个产品试验各自有额度，不应把其中一个额度误读为整批总请求上限。
- 离线复用裁判保留原运行计量；重新调用裁判会追加评审请求及费用，即使评审出错也留档。
  重评总费用包括原执行及追加评审，不用于自动版本放行。
- 已执行一次真实 DeepSeek 冒烟，未自动复跑：6 次产品请求（含预检）＋1 次评审，
  7 次均返回用量并可按产品价格表估算，合计约 $0.00805。第一轮耗尽请求额度，任务未完成。
  运行期间代码发生变化，这条仅验证执行、预算和计量链路，不用于架构收益比较。
  [原始记录](artifacts/20261112-155242-214616-dc11243b/scorecard.md)；
  [零模型请求的修正复评](artifacts/20261112-155242-214616-dc11243b/regrade-20261112-155848-049808/scorecard.md)。
- 用户确认目前没有独立封存数据。封存覆盖保持 0，不把开发题改标盲测。
  当前交付的是可运行的评测框架与验收流程，不是泛化通过证明。
