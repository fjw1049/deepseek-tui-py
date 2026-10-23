# Computer Use 真实验收 — 2026-10-23

## 环境与范围

使用当前工作区源码、已安装 LCU 及独立 Chromium。用户确认另一个任务仍在操作共享 Workbench，因此停止共享界面操作，继续无桌面输入的独立运行时测试。没有批准新的应用访问，没有修改长期权限或真实登录态，没有运行付费模型自主桌面任务。

## 已完成

### Workbench 界面（共享操作暂停前）

- 实际打开“应用市场 → Plugins → 电脑控制”详情。
- 界面显示“组件已安装并启用，模型兼容性与访问权限将在使用时检查”。
- 已授权应用列表正常加载；撤销提示明确要求 Touch ID 或登录密码。
- 点击“刷新状态”后详情保持正常，无错误提示。
- 此进程是运行中的开发版；本次未重启，因此不将主进程撤销超时改动算作真实验收通过。

### 真实 LCU 集成（非模拟、非模型自主 E2E）

运行 check_runtime.py：
- 真实共享客户端返回 js / js_reset 工具目录。
- 对 TextEdit 发起实际权限请求，在批准前关闭连接。
- 实际授权事件顺序为 Required → Resolved(response=None)，pending_user_inputs 清空。
- 进程和桌面锁释放。
- 重新连接获得工具目录。
- 真实连接经过普通用户提问路径关闭；返回值为合法 JSON，包含 CUA 会话重置提示。

运行 check_failed_completion.py：
- 读取实际运行时 API 文档。
- 在真实 JavaScript REPL 中抛出带固定标记的无副作用异常，工具返回失败。
- finish_task(completed) 使用错误前证据被拒绝。
- 实际 js_reset 成功，但不生成完成证据，旧证据再次被拒绝。
- 最终进程和桌面锁释放。

证据：runtime-result.json、failure-result.json。

### 独立真实 Chromium

命令：

```sh
DEEPSEEK_BROWSER_E2E=1 .venv/bin/python -m pytest tests/test_browser_chromium.py -k 'private_session or human_handoff or native_dialog or human_viewport_dialog or field_input_does_not_edit_previous_field or printable_press_respects_cancelled or close_session_returns_success' -q
```

结果：8 passed，110 deselected，14.29 秒。

覆盖临时会话不继承 Cookie/localStorage 且关闭后清空、焦点失败不误写前一输入框、网页取消按键默认行为、原生对话框不重复提交、人工交接后旧观察失效，以及正常关闭。

## 待独占共享桌面后验收

- 模型从 Workbench 发起 TextEdit 中文输入、保存、读回文件的完整链路。
- 实际授权卡的允许一次/本次会话交互与用户停止。
- 人工接管按钮点击、返回模型后的重新观察。
- Touch ID 撤销权限完整流程（需要用户本人完成，不撤销现有真实应用权限来凑测试）。
- 外部 Chrome 的网站授权与登录态任务；本轮不触碰用户的现有标签页。

不能将本轮结果表述为完整桌面 E2E 或 Touch ID 验收通过。

## 第二轮独立真实验收

用户要求继续测试；共享桌面是否已空闲尚待确认，因此本轮没有重新操作 Workbench 或 TextEdit。

### 真实 LCU 断连与暂停

脚本：check_reconnect.py；证据：reconnect-result.json。

- 使用真实 REPL 建立测试变量，随后终止本测试自己创建的桥接子进程。
- 后续调用被拒绝，明确提示旧绑定丢失，要求重新初始化与观察。
- 再初始化成功，生成新的运行段 ID。
- 查询旧 JavaScript 变量返回 undefined，确认没有沿用旧上下文。
- 在无调用进行时触发真实暂停监听器，桥接进程和桌面锁均释放。
- 首次脚本运行因断言期待“re-observe”而实际文案为“observe again”失败；按实际语义修正脚本后通过，没有因此修改产品代码。

### 扩大 Chromium 验收

```sh
DEEPSEEK_BROWSER_E2E=1 .venv/bin/python -m pytest tests/test_browser_chromium.py -k 'not observation_reports_page_and_panel_scroll_sizes' -q
```

结果：117 passed，1 deselected，138.63 秒。日志：chromium-full.log。
排除的一个滚动条尺寸断言已在上一轮使用修改前源码复现失败，不能算通过。

本轮未发现新的产品缺陷。共享桌面中的模型自主输入保存、实际授权卡操作、Touch ID 与外部 Chrome 网站授权仍待验收。

## 第三轮：纠正模型连通性结论（独占授权后）

此前脚本将 endpoint::kimi-k3 / endpoint::qwen-3-8-max 放入 turn 请求的 model 字段。前端实际分别传入 provider 和 model。创建线程路径拆分组合名，但开始 turn 的路径直接使用 model；此前 403 不能解释为用户模型不可用。

改为独立 provider=endpoint、model=kimi-k3 后，thr_371e8bfc / turn_69982ab6 正常响应并调用真实 cua_js，发起 TextEdit 授权。qwen-3-8-max 同格式对照正常回复“连通正常”，turn 状态 completed，见 qwen-connectivity.json。无需用户更换这两个连接的密钥。DeepSeek 此前 401 本轮未复测。

Workbench AX 可读，但点击/滚动间歇失败 noWindowsAvailable。授权通过本地后端 API 回应，不能记为前端授权卡点击通过。首个 API 回答误用了 answer 字段，实际解析接受 value/label/selected_option，因此被拒绝；随后按契约修正为 value，允许一次成功，再为 TextEdit 选择本次会话，无永久授权。

### 新发现：共享工具注册表覆盖 CUA 会话绑定

真实模型已打开 note.txt，但并行启动 qwen 普通对话后，后续输入被桌面互斥锁拒绝。停止本测试后锁消失，未发现其他运行中的后端会话。代码检查发现共享 ToolRuntime.registry 注册的 CuaTool 含有会话实例，新 Engine 的准备会覆盖旧 Engine 的工具。

新增 test_shared_runtime_does_not_replace_another_engines_cua，修复前复现失败。修复为仅在启用 CUA 且使用共享注册表时建立本 Engine 私有注册表，保留已有非 CUA 工具，并在私有表注册 CUA。修复后 tests/test_cua.py 58 passed；tests/contract/test_cua_status.py 4 passed。当前运行中的后端尚未重启加载修复，不将上述单测记为修复后真实多会话验收。

随后 check_shared_registry.py 使用新代码与已安装真实 LCU 验证：首会话获取锁后，准备第二个共享运行时 Engine，首会话工具实例保持不变且再次调用成功，共享注册表未被污染，关闭后全部锁释放。见 shared-registry-result.json。此测试不调用模型、不操作应用。

### 模型驱动的真实 TextEdit 验收通过

- 模型：endpoint / qwen-3-8-max；线程 thr_6f1c7c8b，turn_a433a4c6。
- 真实 cua_js 获取 TextEdit、定位文末、回车、输入指定中文行、通过 super+s 保存。
- read_file 与验收方独立读回均确认 note.txt 包含原始行和“真实桌面验收：中文输入与保存成功。”，未用文件写入代替 UI。
- 普通 request_user_input 进入等待后，lsof 确认桌面锁无持有者。
- 经 API 回复继续并只读复查后，模型重新使用 cua.getApp 初始化句柄，观察保存内容，不再次写入；finish_task 和 task_outcome 均为 completed。
- 此次模型执行使用运行中的后端；新注册表隔离修复另由上述真实 LCU 测试验证，尚未加载进现有 Workbench 后端。
- 另一次 kimi-k3 顺序测试已打开目标文件，但模型下一轮没有发出工具调用，运行时随后触发 finalization-only 提醒并以 partial 收尾；不能记为完整通过，也不是连通性失败。

仍未通过：Workbench 前端授权卡按钮实际点击、人工接管按钮完整流程、Touch ID、外部 Chrome 网站授权。后端接口回应授权和普通问题恢复不能替代这些 UI 验收。

## 第四轮：真实前端授权与桌面接管

当前开发后端 PID 91405，启动于 2026-10-23 18:30:46（上海），晚于注册表隔离修复。测试线程 thr_a015051e / turn_d59f622f，事件 ui-events.jsonl。

- 验收端 CUA 对 Electron 存在 noWindowsAvailable / 无效元素问题；用户确认手动点击正常。重置验收端 REPL 后能进入测试会话，但自动点击仍不稳定，不能将此直接归因于产品按钮代码。
- 实屏确认授权卡完整展示 TextEdit 名称、四种授权选项，无 Other，自由输入不可用，未选时提交禁用。
- 用户真实选择允许一次并提交，后端记录 value=once，随后 cua_js 成功返回。此步骤不是 API 模拟。
- 等待授权期间启动独立普通模型对话，返回“并行对话正常”并 completed；原会话后续 cua_js 继续成功，没有上轮共享注册表覆盖导致的互斥锁错误。证据 live-concurrent-result.json。
- 后续 TextEdit 访问再次请求权限，符合 once 范围；为继续接管测试，后续 session 范围通过 API 回应，未选择 always。
- 模型在重新 getApp 后沿用旧元素索引，误点分组菜单，随后恢复；记录为模型操作可靠性不足，不记为成功点击。文件没有写入。
- 模型实际调用 request_user_input(kind=action, surface=desktop)，生成 desktop_action 卡，选项“我已完成／跳过这一步”；此时 lsof 确认桌面锁无持有者。等待真实人工点击与恢复核验。
- 等待期间界面曾提示事件流恢复，首次用户报告提交后后端尚无回答，再次手动提交成功；未有足够证据确定首次原因。

### 第四轮结果

用户完成真实 TextEdit 操作并通过前端提交“我已完成”。后端返回 choice=done，同时明确告知模型会话已重置、旧 JavaScript 变量及元素引用失效，必须重新观察。随后模型重新绑定 TextEdit，观察正文并只读核对磁盘文件。前端显示“已回答／我已完成”，最终 turn.status 与 task_outcome.status 均为 completed。验收方独立断言文件仍完全等于原两行文本（78 字节），结束后桌面锁无持有者。结果见 ui-handoff-result.json。

本轮通过的是有用户实际点击参与的前端授权与桌面接管闭环，以及运行中新后端的跨会话隔离；不是无人参与的 Electron UI 自动化通过。自动化窗口定位不稳定、模型重新绑定后沿用旧索引造成误点、事件流恢复提示仍需继续定位。模型最终描述“自行打开文件”不能替代验收证据：用户按指引可能完成了打开步骤，不能将打开文件自动操作可靠性记为通过。Touch ID、永久权限撤销与外部 Chrome 网站授权仍未验收。
