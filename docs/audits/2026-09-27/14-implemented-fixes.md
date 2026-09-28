# 第十四篇修复：协议边界与单回合展示归约

日期：2026-09-28。接续 [原审核](14-protocol-presentation.md)，修改 6 个生产模块，新增 [test_audit_14.py](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_audit_14.py)。两个包入口无需调整。历史探针结果保留，不把修复后的结果覆盖到修复前证据上。

## 逐项处理

| 问题 | 本次实现 | 验证与边界 |
|---|---|---|
| P01 图片 crop | `ImageBlock` 拒绝负坐标、零/负宽高。 | 无效输入成为 ValidationError；合法边缘裁剪可序列化往返。真实图片范围仍由读取/编码路径校验，未依据声明尺寸新增 EXIF 越界判断。Pydantic 的 `model_copy(update=...)` 本来就不执行校验；内部调用方仍须提供已校验数据。 |
| P02 MCP failed | 外层 failed 标签优先，内层 type 不能将失败改成 ready。 | 矛盾标签保留错误信息；starting/ready/cancelled/failed 四种旧格式往返通过。没有全局启用 extra=forbid。 |
| P03 重复 round | reducer 在单 turn 内记录非空 round；相同 round 与完整工具声明返回原批次，保留部分/全部结果。工具声明深拷贝，生产者原地修改参数不会污染比较基准。 | 同 round 工具或参数冲突在状态修改前报错；round_count 不重复增长。旁白变化不视为新的执行声明。新 turn 必须 reset；不提供跨 turn 的历史重放存储。 |
| P04 重叠与取消 | 明确单活跃批次，拒绝重叠与重复工具 ID。`is_terminal` 表示生命周期结束；新属性 `all_results_received` 表示结果收齐。取消清理映射，迟到结果不会复活。 | 完成/取消后的重复结果、取消后启动新 round、reset 后重用均有覆盖。取消后的原 round 重放可以返回已取消视图，不重启执行。未扩展多来源并行批次。 |
| P05 旁白语义 | shell 类工具归为 COMMAND，使用“执行命令 / Run commands”，不猜测是在修改还是验证；绝对路径展示规范化后的路径，而非首段 Users。 | cat/pytest/touch 同样使用中性文案；Windows、Unix、相对路径覆盖。已知文件写入仍优先归 MUTATE；混合 shell/其他未知工具归 MIXED。这是展示分类，不参与授权。路径最多 64 字符。 |
| P06 数值边界 | 请求模型名至少含非空白字符，max_tokens 为正数，temperature/top_p 必须有限；Usage 五种计数非负，保留原有别名和缓存口径。 | 顶层/别名负数、OpenAI 带 prompt_tokens 的嵌套负缓存计数、NaN/Inf 均有覆盖。没有给不同 provider 强加统一 temperature/top_p 上界；缺失值继续沿用旧默认值。 |
| P07 归约成本 | 构造时缓存期望 ID 集合；每个结果分别查询三个互斥结果集合，以集合长度判断完成。 | 2048 个成功/失败混合结果、重复与未知 ID 覆盖。公开集合仍是展示视图，调用方不应直接改写；未引入第二份可漂移的终态计数器。完整 terminal_ids/all_results_received 查询仍需集合合并，热路径不再调用。 |

## 方案选择与性能

选“单 turn、单活跃批次 + 明确错误”，而非维护任意乱序多批次。这与当前 Engine 在一次 `_run_conversation` 内串行声明/执行工具批次的结构一致。TUI 在 TurnStarted 重置 reducer。若未来增加跨连接重放，需先定义 turn ID、世代与错误隔离，不能直接把该对象当通用事件总线。

旧算法每个结果重复执行 tuple 查询和集合构建。修复保留三类结果集合及既有视图，使用缓存成员集合，避免为性能另写一套语义。

本机 7 次中位数，构造与 deep copy 不计时；只测结果接收，非网络或 UI 性能：

| 工具数 | 旧算法 ms | 修复后 ms |
|---:|---:|---:|
| 16 | 0.0073 | 0.0018 |
| 256 | 1.0069 | 0.0255 |
| 2048 | 65.9593 | 0.2226 |

小批次原先的绝对开销就很低；2048 是合成边界，不代表真实模型经常返回这种规模。重复、未知 ID、denied 等混合序列的完成状态与旧算法一致。取消状态则按 P04 的新契约处理，不以旧缺陷为兼容目标。

脚本：[presentation_fixed_probe.py](presentation_fixed_probe.py)；结果：[presentation-fixed-probe-results.json](presentation-fixed-probe-results.json)。

## 验证与未处理项

- 最初 28 个缺陷回归在修复前全部失败；修复后通过。补充合法兼容输入和大批次等测试后，本篇新增测试共 **37 项**。
- 最终扩大回归：**290 passed，2 deselected，1.57 秒**，覆盖协议/展示、图片、usage、流结束、截断、恢复、审批、TUI 和 Goal。
- 协议、展示和新测试 Ruff 检查通过；编译与 diff 空白检查见验证记录。没有真实模型/网络调用，也未宣称全仓测试通过。
- 排除的旧 context 测试仍期望 204，前篇已观察到实际 7821；未改该断言。
- 新发现的旧测试 `test_conversation_bundle_restores_original_images` 将 Message 写到 ThreadRecord JSON 位置，触发第十三篇已增加的导入图校验。临时复制当前源码、仅还原本轮六个生产文件到 HEAD 后，仍出现同样五个缺失字段错误，确认不是本轮协议修改引入。尚待用真实 thread/turn/item 数据改写该测试夹具，本轮不放宽导入校验。

详细记录：[14-fixes-validation.json](14-fixes-validation.json)。下一篇：[15-tui.md](15-tui.md)。
