# 工具兼容与退役清单

2026-11-11 开始新增 INFO 事件 `legacy_tool_used`，仅包含旧名、新名及 `count=1`，不记录命令、内容、凭据或其他参数。聚合日志可计次数；没有日志不等于没有使用（须确认采集覆盖）。本次不改变公开版本，不删除旧入口。

| 旧入口 | 当前入口 |
|---|---|
| agent_resume | agent(resume=...) |
| agent(action=list/result/cancel) | task_list / task_output / task_stop |
| exec_shell_interact | exec_shell(process_id=...) |
| task_read / task_cancel / task_resume | task_output / task_stop / task_create(resume=...) |
| task_shell_start / task_shell_wait | exec_shell(background=true) / task_output(process_id=...) |
| automation_create / automation_list / automation_read | cron_create / cron_list / cron_list(automation_id=...) |
| automation_update / automation_pause / automation_resume | cron_update / cron_update(paused=...) |
| automation_delete | cron_delete |

旧名不再向模型目录推荐，但执行层继续兼容。`task_gate_run`、`automation_run` 原本不在兼容转发范围，本轮未扩展。

退役条件：先连续 30 天完整采集且零调用，再人工复核发布说明和外部调用方；公开 HTTP API 另按版本提供迁移窗口。私有函数的测试/插件/导入关系也需检查，不能只因名称以下划线开头就删除。拆分大模块另开独立变更。

只读统计入口（在项目根目录执行）：

```sh
PYTHONPATH=src .venv/bin/python -m deepseek_tui.engine.compatibility_audit /path/to/runtime.log
```

完整覆盖经人工核实后，可添加 `--start YYYY-MM-DD --end YYYY-MM-DD --complete-coverage`。日期不得超出当前日期，观察起点不早于 2026-11-11；没有满 30 天时仍是 `insufficient_evidence`。统计不会执行删除，也不把同名 `agent` 的正常新调用算成旧 action。
