# Codex Browser Use 审核交付

先打开 [REPORT.html](REPORT.html) 阅读可视报告，或阅读 [REPORT.md](REPORT.md)。证据目录提供来源摘要、真实 Codex IAB 结果和项目差距；独立演示与 Codex 实测分别保存。

本机 REA 6.4.0 已安装且 MCP 握手通过。新注册的 MCP 需要 Codex 重新连接或重启后进入工具目录。

运行独立演示：

```sh
./run-demo.sh
```

在本机它使用已安装的 Node 24、Playwright Core 1.58.2 与 Chrome。复制到其他机器时，先在 `replica/` 运行 `npm ci`，安装 Chrome，必要时设置 `CHROME_EXECUTABLE_PATH`；更多协议和边界见 [运行说明](replica/README.md)。两份上级验收页面必须一起保留。

已验证：独立演示 18/18、项目已有能力测试 20 项、两个客户端 mock 合同 12 项。真实 Codex IAB 则为 8 项预期通过、2 项预期失败，异常没有被演示通过数掩盖。

最后独立复审通过，源码身份、函数位置与证据数字一致；详情见 [复审记录](evidence/final-review.json)。`delivery-manifest.json` 提供交付文件的 SHA-256，便于核验。

最先应修当前项目的观察裁剪与滚动派发；本次交付没有修改现有业务代码。报告与证据不包含原应用 bundle、凭证或私人会话。
