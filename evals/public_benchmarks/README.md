# Public benchmark campaigns

This adapter runs the existing `Engine.create` / `Engine.run` entry point inside
official Harbor task containers. Production code and the official verifier are
unchanged. The supported dataset is Terminal-Bench 2.1, one attempt per task.

A campaign lives in one run directory. Its `manifest.json` freezes everything that
defines the run: the model route, the task order, budgets, the optional published
reference score and the hash of the evaluated source. The supervisors, the config
exporter and the report all read it, so nothing campaign-specific is hard-coded.

## Starting a campaign

Prepare the run directory with the Terminal-Bench checkout under
`datasets/terminal-bench-2.1`, a Harbor 0.24.0 virtual environment in `venv/`,
the Linux uv bootstrap archives (`uv-<arch>.tar.gz`), `source.tar.gz` (the frozen
source) and `pilot.json` (the Harbor job config for the `WorkbenchAgent`). Then
start the parallel supervisor from the repository root (requires Docker and
endpoint connectivity):

```sh
.venv/bin/python -m evals.public_benchmarks.parallel evals/artifacts/<run> \
  --model endpoint/glm-5-3 \
  --reference-percent 88.2 --reference-scaffold "Claude Code 2.1.207" \
  --reference-source https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md \
  --concurrency 2 --memory-budget-mb 8192
```

`--model` is required for a new campaign. Without `--reference-percent` the report
makes no comparison. Other options (`--limit`, `--seed`, `--request-limit`,
`--idle-timeout`, `--task-timeout`, `--supervisor-timeout`, `--max-output-tokens`,
`--temperature`, `--top-p`, `--gateway`, `--docker-platform`) default to the
values in `campaign.py --help`. They apply only when the manifest is created;
resuming always uses the frozen manifest. `campaign.py` takes the same options and
runs one task at a time.

The supervisor schedules tasks until the concurrency limit or the combined
`memory_mb` budget of the running tasks is reached. A file lock prevents duplicate
supervisors. Create a `STOP` file in the run directory to request a graceful stop.

Resume by running the same command without the new-campaign options. Resume skips
all already recorded attempts, including failures; a repaired rerun must be a
separate campaign, not a silent replacement or best-of selection. To switch from a
running sequential supervisor without restarting its trial, stop that supervisor
and pass its saved progress as a handoff file:
`... parallel evals/artifacts/<run> evals/artifacts/<run>/parallel-handoff-<id>.json`.

## Budgets and stop rules

Each worker enforces the request limit, the idle timeout and the task timeout
from the manifest. A trial running past the supervisor timeout is stopped on its
own and scheduling continues. Quota, authentication and persistent API errors stop
scheduling. Three consecutive environment, runtime or idle failures, or trials the
supervisor had to stop, also stop the campaign. Valid wrong answers do not.

When `fast-policy.json` exists in the run directory, attempts started after it
was created get tighter limits: `setup_seconds`, `idle_seconds` (without model
progress) and `total_seconds` including verification, by default 300, 300 and
1800. Its optional `created_at` (Unix time) defaults to the file's modification
time; trials started earlier keep the original budgets. A timed-out trial receives
SIGINT, then forced termination after 30 seconds. A campaign that uses this is a
mixed-budget campaign, not an official same-budget comparison. Preserve the
policy file when resuming.

## Evidence

- `source.tar.gz` freezes the evaluated source; `manifest.json` records its hash,
  dataset commit, task order, model and budgets.
- `progress.json` records the supervisor PID, `active_tasks` and the last heartbeat.
- `configs/*.console.log` preserves Harbor output.
- `results.jsonl` is the append-only result ledger. Pilots are separate.
- `jobs/<attempt>/<trial>/agent/trace.jsonl` contains complete model requests,
  normalized provider events and Engine events, including tool arguments/results.
- The same `agent/` directory holds `final.json`, `status.json`, sanitized runtime
  configuration, package versions and installation/worker output.
- Each `verifier/` directory and trial `result.json` hold official test evidence.
- `analysis.json` and `analysis.md` summarize outcomes and review candidates.

Refresh the analysis without making model calls:

```sh
.venv/bin/python -m evals.public_benchmarks.analyze evals/artifacts/<run>
```

Credentials travel through a private pipe and a temporary container file, which
the worker removes before executing the task. Known credential values are
redacted from traces. No results are uploaded to a public leaderboard. Cost is
reported as unknown unless the gateway has a verified price.

The model sees task instructions and the task container, not host benchmark
solutions/tests. Harbor supplies the verifier after the agent finishes. Container
access is unrestricted within the isolated task. Personal plugins, MCP, web
search, child agents and background tasks are disabled, so GUI and multi-agent
behavior remain outside the measured scope.

Task correctness comes from the official verifier. Tool errors are diagnostic: an
expected merge conflict followed by successful recovery is not automatically an
architecture defect. Repeated identical calls and a completed turn that fails
verification are review candidates, not automatic judgments of dishonest claims.
A published reference is directional only: gateway identity, hardware, agent
implementation, reasoning defaults and repetitions can differ, so a score
difference is not a causal architecture penalty. Broader scores require separate
BFCL/SWE/interactive-task adapters and an explicit matched baseline.

Raw artifacts under `evals/artifacts/` are local and git-ignored; keep the
directory when cleaning the checkout, and preserve the source archive and adapter
while a campaign is active.

## Recorded campaign

`evals/artifacts/public-benchmarks-20261019/` ran `endpoint/glm-5-3` on all 89
tasks against the GLM-5.3 model card's 88.2% (Claude Code 2.1.207). It started
sequentially and was adopted by the parallel supervisor (two tasks, 8192 MiB)
without replaying its live trial; `parallel-handoff-*.json` records that change.
Its manifest predates the configurable fields, so resuming it uses those recorded
values. Some of its attempts ran under a fast policy, making it a mixed-budget
campaign.

Official references:

- https://github.com/harbor-framework/terminal-bench-2-1
- https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md
- https://docs.harborframework.com/agents/custom-agents
