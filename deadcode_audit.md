# src/ 死代码审计 — 分级清单

> 工具:vulture(min-confidence 60)出 294 个 unused function/method 候选 → 11-agent 并行复核(逐条 grep 真实调用点)→ 抽样验证。
> 复核结果:**dead 90+ 唯一符号 / 35 文件,uncertain 1,false_positive 213**(框架回调/动态分发/override/入口点,已剔除)。
> **原则:只列不删,等你拍板。** 下面按"删除风险"分三层。

---

## 🟥 Tier C — 不要删(契约 API,当前零引用但有意保留)

这些 vulture 判 dead,但**删了会违反项目契约**。`config/paths.py` 文件头明确写:
> "Callers MUST go through the typed helpers below... See memory/path-layout-contract.md"

它们是 Rust `config.rs:1690-1930` 两层路径布局的完整移植,属于"尚未接线的契约 API",不是死代码。

**`src/deepseek_tui/config/paths.py`(19 个)** — 全部保留:
`user_managed_config_path` `user_requirements_path` `user_audit_log_path` `user_session_artifacts_dir` `user_stash_dir` `user_skill_state_path` `user_roles_dir` `user_onboarded_marker_path` `user_composer_history_path` `user_composer_stash_path` `user_workspace_trust_path` `project_handoff_path` `project_subagent_state_path` `project_plan_path` `project_skills_dir` `project_logs_dir` `project_agents_md` `project_claude_instructions` `project_claude_md`

---

## 🟨 Tier B — 删前需你确认(像公开 API / 成对能力)

零引用属实,但它们是**成套对外能力**,可能是给未接线功能预留的。删之前最好你确认这些功能是否还要做。

| 文件 | 符号 | 说明 |
|---|---|---|
| state/secrets.py | `set_api_key` `delete_api_key` `list_providers` | SecretsManager 的 CRUD,只有读没接写删列 |
| tools/registry.py | `read_only_tools` `approval_required_tools` `execute_full` `to_api_tools_with_cache` | ToolRegistry 的查询/缓存 API,Rust 有对应物 |
| engine/cycle.py | `briefing_max_for` `to_system_block` `estimate_briefing_tokens` `produce_briefing` `open_archive` `build_seed_messages` | 整个 "briefing/cycle" 子系统疑似未接线(8 个全 dead) |
| engine/context.py | `extract_compaction_summary_prompt` `append_working_set_summary` `turn_response_headroom_tokens` | 压缩/上下文 helper |
| policy/sandbox.py | `is_path_writable` `external_sandbox` `display_command` | 沙箱 helper(注意 [[rust-source-of-truth]]:沙箱分歧先读 Rust) |

> ⚠️ engine/cycle.py 的 8 个 + context.py 的 3 个:这像是**一整个未接线的子系统**,不是零散死代码。建议整体判断"这功能还要不要",而非逐个删。

---

## 🟩 Tier A — 较安全可删(孤立 helper,零引用、非契约、非框架)

单点孤立函数,删除影响面最小。仍建议删前 grep 一次确认。

| 文件 | 行 | 符号 |
|---|---|---|
| automation/inbox.py | 129 | `default_mail_to_from_config` |
| client/deepseek.py | 24 | `is_reasoning_model` |
| client/pricing.py | 211 | `format_cost_estimate` |
| config/models.py | 468 | `resolved_database_path` |
| engine/capacity.py | 650 | `_extract_paths_from_tool_input` |
| engine/dispatch.py | 84 | `caller_allowed_for_tool` |
| engine/prompts.py | 43 | `from_settings` |
| engine/seam.py | 82 | `should_cycle` |
| engine/tools.py | 306 | `maybe_activate_requested_deferred_tool` |
| integrations/hooks.py | 506 | `is_enabled` |
| policy/approval.py | 628/631 | `add_rule` `clear_cache` |
| policy/exec_policy.py | 765 | `is_match` |
| policy/network.py | 139 | `approve` |
| server/phase_bridge.py | 118 | `text_matches_locale` |
| state/context.py | 502 | `detect_mime` |
| state/session.py | 392 | `add_message` |
| tools/automation.py | 1130 | `default_location` |
| tools/encoding.py | 281 | `prepare_tools_for_strict_mode` |
| tools/patch.py | 830 | `apply_patch_to_file` |
| tools/subagent.py | 2030 | `share`(Mailbox 方法) |
| tools/task.py | 1387 | `is_shutdown`(TaskManager 方法) |
| tools/web.py | 519 | `_fetch` |
| tui/cards.py | 175 | `with_workers` |
| tui/notifications.py | 99/113 | `notify_done` `humanize_duration` |
| tui/plan.py | 278/282 | `is_selecting` `get_selected_idx` |
| tui/sidebar.py | 167/240 | `show_sidebar` `from_thread_metadata` |
| tui/tool_cell.py | 63 | `_is_compact_delegate_tool` |
| workflow/adapters.py | 50 | `script_meta_to_spec_skeleton` |
| workflow/models.py | 524 | `agent_run_to_dict` |

---

## ❓ Uncertain(1 个,需你看一眼)

| 文件 | 符号 | 疑点 |
|---|---|---|
| server/phase_bridge.py:114 | `preface_language_mismatch` | 唯一引用是个测试名字符串 `test_gate_uses_compute_when_preface_language_mismatches`,实际是否被调用不明 |

---

## 复核口径(为什么可信)
- 213 个 vulture 候选被正确判为**误报**并剔除:Textual 框架回调(`on_mount`/`action_*`/`compose`/`watch_*`)、dunder(`__getattr__` 等)、ToolSpec override(`name`/`description`/`execute`/`input_schema`/`capabilities`)、注册表动态分发、入口点。
- 抽样验证过 Tier B/C 的高风险项:`config/paths.py` 路径函数、secrets CRUD、`execute_full`(其"1 处引用"实为自身注释,确属 dead)均与复核结论一致。
- 原始数据:`notes_deadcode.json`、`.vulture_candidates.txt`。
