❯ 从路由的入口文件开始逐一审核核心代码，找出哪些文件/函数是待调整的，以及哪些文  
  件/函数是多余的。不要做任何改动，只需要列出来就好了                            

⏺ Let me trace through the codebase from the entry points to identify unused or
  problematic code.
     
  Searched for 2 patterns, read 1 file (ctrl+o to expand)

⏺ I'll systematically audit each core package. Let me spawn parallel agents to
  cover the major subsystems.

⏺ 4 background agents launched (↓ to manage)
   ├ Audit engine/ package
   ├ Audit tools/ package
   ├ Audit cli/tui/app_server packages
   └ Audit remaining packages
   
⏺ 已启动 4 个并行审计任务，分别覆盖：
  1. engine/ 包
  2. cli/ + tui/ + app_server/ 包
  3. tools/ 包
  4. 其余所有包（client, config, execpolicy, hooks, lsp, mcp, prompts, protocol,
  secrets, skills, state, 顶层文件）

  等它们完成后我会汇总结果。
  
✻ Worked for 40s · 4 local agents still running

⏺ Agent "Audit engine/ package" completed

⏺ Engine 包审计完成，等待其余三个任务完成后一起汇总。

✻ Sautéed for 6s · 2 local agents still running

⏺ Agent "Audit tools/ package" completed

⏺ Tools 包审计也完成了，等待剩余两个任务。

✻ Churned for 10s · 2 local agents still running

⏺ Agent "Audit remaining packages" completed

⏺ 三个完成了，还在等 cli/tui/app_server 包的审计结果。

✻ Churned for 6s · 1 local agent still running

⏺ Agent "Audit cli/tui/app_server packages" completed

⏺ 全部审计完成。以下是汇总报告：

  ---
  核心代码审计报告

  一、完全未使用的函数/类（可删除）
  
  ┌───────────────────┬──────┬────────────────────────────┬──────────────────┐
  │       文件        │ 行号 │            符号            │       说明       │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/engine.py  │ 806  │ undo_last_tool()           │ 无外部调用，/und │
  │                   │      │                            │ o 命令未接入     │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │                   │      │                            │ 仅为             │
  │ engine/engine.py  │ 772  │ _take_pre_tool_snapshot()  │ undo_last_tool   │
  │                   │      │                            │ 服务             │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/tool_parse │ 387  │ parse_tool_input()         │ 无任何调用       │
  │ r.py              │      │                            │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/approval.p │ 24   │ DenyApprovalHandler        │ 无实例化         │
  │ y                 │      │                            │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/approval.p │ 33   │ EventApprovalHandler       │ 无实例化         │
  │ y                 │      │                            │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/dispatch.p │ 168  │ should_parallelize_tool_ba │ 无调用           │
  │ y                 │      │ tch()                      │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/dispatch.p │ 178  │ should_stop_after_plan_too │ 无调用           │
  │ y                 │      │ l()                        │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/dispatch.p │ 185  │ should_force_update_plan_f │ 无调用           │
  │ y                 │      │ irst()                     │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/dispatch.p │ 129  │ parse_parallel_tool_calls( │ 无调用           │
  │ y                 │      │ )                          │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/dispatch.p │ 231  │ mcp_tool_approval_descript │ 无调用           │
  │ y                 │      │ ion()                      │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ engine/capacity.p │ 202  │ observe_post_tool()        │ 无调用           │
  │ y                 │      │                            │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ skills/__init__.p │ 44   │ agents_global_skills_dir() │ 无调用           │
  │ y                 │      │                            │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ skills/__init__.p │ 55   │ claude_global_skills_dir() │ 无调用           │
  │ y                 │      │                            │                  │
  ├───────────────────┼──────┼────────────────────────────┼──────────────────┤
  │ protocol/app.py   │ 38-7 │ AppCapabilitiesRequest 等  │ 导出但从未被导入 │
  │                   │ 2    │ 6 个类                     │ 使用             │
  └───────────────────┴──────┴────────────────────────────┴──────────────────┘

  二、导出但仅内部使用（可降为私有）

  ┌───────────────────┬───────────────────────────┬──────────────────────────┐
  │       文件        │           符号            │           说明           │
  ├───────────────────┼───────────────────────────┼──────────────────────────┤
  │ client/pricing.py │ ModelPricing,             │ 导出到 __init__.py       │
  │                   │ PricingTable              │ 但无外部引用             │
  ├───────────────────┼───────────────────────────┼──────────────────────────┤
  │ mcp/transport.py  │ McpTransportError,        │ 导出但仅 mcp/client.py   │
  │                   │ SseTransport              │ 内部使用                 │
  ├───────────────────┼───────────────────────────┼──────────────────────────┤
  │ lsp/client.py     │ LspTransport              │ 导出但仅作为内部 ABC     │
  │                   │                           │ 基类                     │
  └───────────────────┴───────────────────────────┴──────────────────────────┘

  三、需要调整的代码

  ┌──────────────────────────┬───────────┬───────────────────────────────────┐
  │           文件           │   问题    │               说明                │
  ├──────────────────────────┼───────────┼───────────────────────────────────┤
  │ client/pricing.py │ ModelPricing, PricingTable      │ 导出到 __init__.py 但无外部引用 │
  ├───────────────────┼─────────────────────────────────┼─────────────────────────────────┤
  │ mcp/transport.py  │ McpTransportError, SseTransport │ 导出但仅 mcp/client.py 内部使用 │
  ├───────────────────┼─────────────────────────────────┼─────────────────────────────────┤
  │ lsp/client.py     │ LspTransport                    │ 导出但仅作为内部 ABC 基类       │
  └───────────────────┴─────────────────────────────────┴─────────────────────────────────┘

  三、需要调整的代码

  ┌────────────────────────────┬───────────────┬────────────────────────────────────────────────────────────────────────────────────┐
  │            文件            │     问题      │                                        说明                                        │
  ├────────────────────────────┼───────────────┼────────────────────────────────────────────────────────────────────────────────────┤
  │ engine/prompts.py:8        │ 未使用的      │ sys 已导入但未使用                                                                 │
  │                            │ import        │                                                                                    │
  ├────────────────────────────┼───────────────┼────────────────────────────────────────────────────────────────────────────────────┤
  │ engine/seam_manager.py:385 │ 命名不一致    │ truncate_chars() 是公共名，但 compaction.py:86 同功能函数叫 _truncate_chars()      │
  ├────────────────────────────┼───────────────┼────────────────────────────────────────────────────────────────────────────────────┤
  │ tools/ 多文件              │ 重复代码      │ _require_string() 在 11 个文件中重复定义，_optional_string() 在 7                  │
  │                            │               │ 个文件中重复，_optional_int() 在 6 个文件中重复                                    │
  ├────────────────────────────┼───────────────┼────────────────────────────────────────────────────────────────────────────────────┤
  │ engine/engine.py:204       │ 关联死代码    │ tool_snapshots / _max_tool_snapshots / _max_snapshot_file_size                     │
  │                            │               │ 属性仅服务于未接入的 undo 功能                                                     │
  └────────────────────────────┴───────────────┴────────────────────────────────────────────────────────────────────────────────────┘

  四、无问题的包

  - cli/ — 干净，无死代码
  - tui/ — 干净，所有函数均有调用
  - app_server/ — 干净
  - config/ — 干净
  - execpolicy/ — 干净
  - hooks/ — 干净
  - state/ — 干净
  - secrets/ — 干净
  - 顶层 trace.py, utils.py, logging_setup.py — 干净

  ---
  总结

  - 可直接删除的死代码：约 14 个函数/类，集中在 engine/ 包（dispatch.py、approval.py、tool_parser.py、capacity.py）和 protocol/app.py
  - 最大的结构性问题：tools/ 包中验证辅助函数大量重复（~100+ 行冗余），适合提取到共享模块
  - 功能桩：undo_last_tool + snapshot 机制是完整实现但未接入的功能，要么接入 /undo 命令，要么移除