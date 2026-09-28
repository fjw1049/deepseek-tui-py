# 第十七篇修复与本轮收尾

日期：2026-09-28。按用户要求，修复本篇后结束这一轮，不再开启新的功能审核。此次同时提交前几轮尚未提交的审核修复、回归测试和文档，目标分支为 `build_0928`。

[原审核](17-config-cli.md) 保留发现时的代码位置和探针证据；旧探针断言的是旧行为，不作为修复后的验收脚本。本次验收使用 [test_audit_17.py](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_audit_17.py)。

## 实施结果

| 编号 | 修复与选择 | 验证/边界 |
|---|---|---|
| Q01 配置作用域 | 根文件发现和项目可信分类统一使用请求 workspace。no_project_config 关闭根配置、隐藏项目配置及项目 dotenv 的隐式读取；显式指定配置仍读取，并按所在工作区过滤。 | 双工作区、显式项目路径、全部隐式来源关闭通过。用户指定的工作区外文件仍是显式可信来源。 |
| Q02 凭据路由 | 项目覆盖屏蔽整个 automation；Config 合并切换 provider 时清空旧顶层 key/base_url/model，再应用同层显式值。沿用 config_for_model 的凭据隔离语义。 | 项目切换 provider 不携带旧 key/endpoint；没有 SMTP 或真实网络请求。 |
| Q03 profile | 在 profile 合并前选取 CLI > 环境 > 文件选择器，避免之后环境字段改标签。profile 只合并显式字段，其他合并阶段也保留其字段来源。 | 环境选择、CLI 优先、部分 UI 覆盖保留基础 locale。managed config 仍是最终覆盖层。 |
| Q04 预算隔离 | 新增纯函数 configured_context_window，按当前配置/provider/model 解析；Engine 创建时复制配置，模型切换同步 TurnLoop。输入预检、压力、工具截断、压缩、cycle 和 Engine 展示传递配置。 | 两个真实 Engine 同名模型分别保持 8192/65536；修改原始 Config 不改变快照，切换路由才更新。已知模型显式窗口覆盖生效。旧 register/set API 仅为独立调用兼容保留，加载配置/创建 Engine 不再调用它，带配置的解析不读取其全局表。 |
| Q05 CLI 参数 | Typer 根 context 保存显式参数，子命令加载配置时继承；CLI overrides 在 managed config/requirements 前合并。profile set/unset 写对应 profile。自定义 model resolve 不再回落成另一个模型。 | 模型参数跨子命令生效，审批限制不能绕过 requirements。输出仅支持 text，json 明确报不支持；sandbox check 标注安全启发式，并拒绝假装生效的 --ask。 |
| Q05 凭据实际生效 | 私有运行时凭据覆盖携带 provider 身份，不序列化；CLI key 在真实客户端工厂入口优先于环境/旧 provider key，管理配置仍可覆盖或清空；切 provider 清除此覆盖。 | 最终工厂参数捕获测试覆盖普通 CLI、管理层顶层 key、管理层 provider key、切换和空 key。普通非 CLI 配置原有 env→provider→顶层回退次序保持。 |
| Q06 one-shot/MCP | 初始化失败关闭自建客户端；成功后由 Engine 关闭。同时监督事件消费与 Engine task，失败事件/失败完成返回非零；finally 收拢任务后关闭 Engine。MCP start/展示失败也 stop_all。 | 初始化失败、运行异常无终止事件、ErrorEvent、失败/成功 TurnComplete、MCP 启动异常均验证。未增加在线模型 E2E。 |
| Q07 诊断脱敏 | show/list/get 共用递归脱敏，包含 key、password、secret、token、extra_headers/body；set 不回显值。单项 get 可显式 --show-secrets。 | 容器查询也不会泄漏伪 key，max_tokens 等非密钥预算仍显示。私有 CLI 凭据覆盖不进入 model_dump。 |
| Q08 CLI 状态修改 | archive/unarchive/set-name 在一个 ThreadLease 内使用一个 store 完成读改写；占用时明确失败。插件包装命令和 install-all 的失败返回失败退出码。 | 活跃线程拒绝写入，释放后改名成功；插件失败退出码测试通过。外部不遵循租约的写者不在保证范围。 |
| Q09 迁移协调 | 复用 FileLease 提供 home 级锁，覆盖整次迁移；Python 备份元数据读改写复用同一锁。保留原有冲突隔离策略。 | 两个真实 Python 子进程并发迁移成功；异常退出释放锁。未把这个锁声称为 Electron/外部任意 settings 写者的统一事务。 |
| Q10 原子写 | fdopen 先接管描述符再 fchmod；fdopen 失败时 finally 关闭原 fd。显式 newline="" 保留文本工具传入的换行。 | fchmod 故障不泄漏 fd，原目标内容保留；原有写失败/无 fchmod 回归通过。未增加目录 fsync，不承诺断电持久性。 |
| Q11 公共函数 | 摘要只有确需截断才留省略号空间，非正预算返回空；tail_log 最多逆向读取 1 MiB、丢弃首个残行，非正行数返回空。日志重载恢复上次修改的 logger level 后再应用本次配置。 | Unicode 尾行、禁止全文 read_text、短文不误截、极小预算、日志覆盖移除通过。日志仍为明确的进程级服务。 |
| Q12 局部约束 | timeout、token/window、并发数和日志保留期补必要范围约束；rate_limit=0、llm_max_concurrent=0、keep_hours=0 的既有禁用/无限制语义保留。 | 7 组非法值和合法零值测试。未把所有配置对象改为 forbid，以保留现有扩展兼容；视觉判断模块不做无依据重写。 |

## 验证

- 累计修复扩展回归：**1448 项通过**，覆盖 Engine、Goal、Workspace、Server 存储、TUI、插件/LSP/MCP、文件/Shell/Web、计划/Checklist，以及配置/CLI。
- 提交前补齐凭据解析优先级后，追加配置与客户端定向回归：**143 项通过**。两批有重叠，不能相加作为独立测试总数。
- 本篇新增测试最终 **51 项**；详细命令及统计以 [验证 JSON](17-fixes-validation.json) 为准。
- 新测试完整 Ruff、受影响生产边界 F/E9、compileall、git diff --check 通过。engine/context.py 有既存的 re 未使用/重复导入告警，未因本轮顺手删除；不宣称全仓库风格检查无告警。

本轮没有跑整个仓库的所有测试，没有访问真实模型/SMTP/MCP 服务，也没有进行 Windows 或掉电恢复验收。初始新测试运行混有两项测试夹具缺少事件必填字段的问题，不把最初失败数量全部计为真实产品缺陷；后续已修正夹具并验证成功/失败事件。

## 收尾范围

17 个体系都有首轮审核和修复/局部优化记录。历史保留项继续列在 [进度台账](progress.md)，包括完整 TUI rewind、外部写入竞态、权限产品语义和跨文件崩溃恢复等；按本次要求结束这一轮，不扩张实施范围，也不将其标成已经解决。
