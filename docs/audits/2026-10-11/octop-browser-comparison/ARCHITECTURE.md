# 浏览器执行职责与边界

决定日期：2026-10-13。保留主模型决策、BrowserService 唯一执行入口、Workbench 展示/人工接管、录制与 Skill 复用的结构，不增加网页规划模型或假想多后端层。

- 主模型负责用户意图、允许的影响、路线选择和业务成功证据。网页、录制步骤、视觉事实不能发放授权。
- BrowserService 负责所有权、generation、截止时间、派发、独立操作收据和未决操作。导航读取可用于对账；未知变更阻止再次变更，只有人工核对可清除未决状态。
- observation/frames 使用受控世界绑定 DOM 节点与祖先文档，校验名称、角色、链接目的、父节点和局部记录。共享 marker 不参与最终派发。
- recording/workflows/skills 共用目标语义与 scope。先完整编译全部参数，再接管和执行；每步使用新观察。停止按 flush、传输 barrier、脱敏与编译、保存、清理处理，关键失败拒绝回放和 Skill。
- routes/Workbench 传递同一 receipt。画面刷新失败不改变执行事实。人工输入绑定控制代次、文档/标签、viewport 和可见记录键；旧队列丢弃，键鼠释放单独清理，晚到画面按序列淘汰。
- context/media 负责硬字符预算、补读、选项句柄、快照续读和图像来源/实际传输变换。token 估算与供应商实际用量分别记录。

支持：8 层祖先 frame/OOPIF、open shadow 与 shadow 中的 frame owner、显式上传、线程下载目录、原生 JS 弹窗、多标签任务 alias 回放。录制动态 frame 要在输入前安装采集，人工输入入口会同步新 frame。closed shadow、frame CSS transform/zoom 坐标明确受限。视频需要 FFmpeg，环境 readiness 与完整支持能力分别声明。

这里验证的是定义的行为不变量；网页仍可在检查与原生派发之间异步改变。字段即时确认不是业务保存成功，无业务断言的回放只表示路径完成。精确任务授权只复用同任务、同文档、同节点、同 scope 和同影响；文档/节点/收件人/账号/资源或控制变化使其失效。
