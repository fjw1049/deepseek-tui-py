# 第八篇 · 状态、上下文与媒体修复记录

日期：2026-09-27。保留工作区已有改动，原问题基线见 [第八篇审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-state-media.md)。本轮实施 S01—S07 的已复现缺陷，不把局部修复视为全量持久化架构改造。

## 实施范围

| 问题 | 实际行为 | 边界 |
|---|---|---|
| S01 checkpoint 身份串用 | 路径按工作区规范路径哈希、会话 ID 哈希隔离；工作区 latest 仅保存会话指针。恢复核对 workspace/id，恢复后沿用原会话 ID；Engine 完成、TUI 新会话只清理当前 ID | 同工作区自动恢复仍选 latest；其他会话可按 ID 读取，未新增选择 UI。清理保留指针，避免删除并发写入的新指针；指向已清理文件时返回无可恢复内容 |
| S02 格式和版本 | 校验对象、整数版本、metadata/messages 基础形状及身份字段类型；读写上限 32MiB，读取先限量再解析；写入版本由存储层决定 | 消息内容继续交给恢复层的协议模型校验。坏文件保留；未知版本拒绝 |
| S03 粘贴竞争 | 独占创建文件，名称冲突增加序号重试 | 固定秒级时间戳的双线程竞争返回两份完整不同文件；不宣称掉电期间的文件内容事务 |
| S04 输入总预算 | 所有展开块走统一渲染后预算，包含 XML 转义、块封套和展开标题；放不下时降为引用，引用也放不下则省略展开 | 保留用户原文。总额指新增 local_context 的内部文本，不限制用户问题本身和外层标签；图片另由客户端预算管理。目录仍全量排序后截取 |
| S05 TOML 写坏 | 用 tomllib 解析原件和候选，核对候选语义是否等于指定字段更新；按解析后的表头比较空格/引号等价形式；进程内锁覆盖整个读改写 | 不引入新依赖。复杂多行结构无法可靠修改时明确失败并保留原文件，不承诺支持完整 TOML 编辑。锁不协调其他进程或外部编辑器 |
| S06 重复编码 | 两个客户端构建 payload 时建立请求局部图片变体缓存；预算和序列化复用同一结果 | 缓存键为内容 ID、裁剪、缩放。构建结束或异常后释放；下一次构建重新读文件校验。视觉助手预处理、另一次 fingerprint 构建不跨调用复用 |
| S07 文件变化 | 展开入口统一兜住 OSError，给出引用/警告，保留问题 | 保留现有非法图片的 ValueError 降级；不扩大到吞掉任意程序错误 |

旧的全局 latest 仅在工作区一致且有有效会话 ID 时迁移到新路径，保留旧源文件。无 workspace 的旧底层 API 保留兼容，但实际 TUI 恢复和 Engine 清理已传入工作区身份。尚未把这些 checkpoint 合并进 Server 的线程存储，也没有增加跨进程会话锁或事务日志。

实现入口：[session.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/session.py)、[context.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/context.py)、[paste_file.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/paste_file.py)、[secrets.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/state/secrets.py)、[media.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/media.py)、[恢复入口](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/session_restore.py)。

## 方案取舍与最小对照

checkpoint 选择分会话文件加身份校验，避免把本篇扩展为 Server 存储迁移。TOML 选择解析前后验证并保留现有文本修改器，比整体重写更能保持注释；代价是部分合法复杂文件无法自动编辑，后续如需完整支持，再评估保留格式的语法树库。

图片选择请求局部缓存，生命周期跟随 payload 构建；没有引入全局 LRU、跨会话失效机制或磁盘变体存储。对照侧只绕过新缓存装饰器，保留完全相同的预算与序列化代码；每轮断言两个 payload 相等。

| 512×512 合成图片，5 组交替执行 | 无缓存中位耗时 | 请求缓存中位耗时 | 编码次数 |
|---|---:|---:|---|
| DeepSeekClient | 22.039ms | 11.289ms | 2 → 1 |
| AnthropicCompatClient | 22.025ms | 11.034ms | 2 → 1 |

这不是历史提交完整重放，也不是端到端性能提升。数据源是固定随机种子的合成 RGB 图片；真实图片尺寸、压缩率和文件系统会改变耗时。

[对照脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/state_media_compare.py) · [原始数据](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/state-media-compare-results.json)

## 验证

新增 [20 项回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_state_audit_fixes.py)：工作区与会话隔离、清理、旧文件迁移、坏格式和大小上限、并发粘贴、目录/转义预算、消失文件、语义等价 TOML 表头、多行失败保留、并发配置更新、两种协议请求缓存及异常释放。

相关测试 **441 passed**，覆盖本篇、文件展开、粘贴、状态恢复、媒体、provider、限流、stream done、Engine 和 Goal。另做相关 Ruff F 检查、编译与 diff 空白检查。未调用真实模型、未做桌面端完整构建；不宣称整个仓库全量测试通过。具体命令见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-validation.json)。

原 state_probe.py 与 state-probe-results.json 保留修复前证据，不能拿旧探针的预期当当前验收。后续审核已交付 [第九篇：模型客户端与流式协议](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-client-streaming.md)。
