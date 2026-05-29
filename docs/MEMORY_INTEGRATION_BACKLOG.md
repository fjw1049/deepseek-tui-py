# 智能记忆 — 待办 / 集中测试清单

> P1 Native 实现已落地（见 [`MEMORY_INTEGRATION.md`](./MEMORY_INTEGRATION.md)）。  
> 本文档记录**延后项**与**需真实 API / 手验**的验收，便于后续一次性集中跑。

---

## 集中测试批次（建议顺序）

开启配置后按 [`MEMORY_INTEGRATION.md` §6](./MEMORY_INTEGRATION.md) 验收表 #1–#8b 逐项勾选。

```toml
[memory]
enabled = true
mode = "hybrid"

[memory.smart]
enabled = true
```

| 批次 | 内容 | 类型 | 状态 |
|------|------|------|------|
| **A** | `pytest tests/memory tests/contract/test_memory_smart.py -q` | 单元/集成（无 API） | ✅ 33 passed（含 capture success） |
| **B** | `pytest tests/memory/test_l1_extraction_live.py -m live -v` | **真实 API L1 提取** | ✅ 2 passed（需 `DEEPSEEK_SKIP_KEYRING=1` + 有效 key） |
| **C** | 5 轮 capture → L0；flush → L1 行 | 契约 `test_memory_acceptance`（L0+L1 stub） | ✅ |
| **D** | recall 注入 `<relevant-memories>` | 契约 `test_memory_acceptance` | ✅ |
| **E** | TUI resume 同 `thread_id` 续记 + metadata | 契约 `test_memory_acceptance` + `test_memory_tui_persist` | ✅ |
| **F** | 门控：短确认无 capture；短句+tool 有 capture | 契约 `test_memory_acceptance` | ✅ |

---

## B — 真实 API L1 提取集成测（已实现）

**原则 A（HANDOVER）**：L1 走 `LLMClient.stream_with_retry`，必须用真实 API 验证 wire 行为。

**文件**：`tests/memory/test_l1_extraction_live.py` + `tests/memory/conftest.py`

| 用例 | 验证 |
|------|------|
| `test_l1_extraction_inserts_memories_from_conversation` | 直接 `L1Extractor.extract_and_store` → DB 行 + recall 含 pytest |
| `test_capture_and_flush_triggers_l1_pipeline` | `capture` + `flush_session` + `l1_every_n=1` 调度链 |

**运行**（需 `.deepseek/config.toml` 内**有效** API key；默认 `pytest tests/memory` 会 skip live）：

```bash
DEEPSEEK_SKIP_KEYRING=1 DEEPSEEK_API_KEY=sk-... \
  PYTHONPATH=src pytest tests/memory/test_l1_extraction_live.py -m live -v
```

401 时会 `pytest.fail` 并提示更新 key（不静默 skip）。

---

## P2 功能待办（非阻塞 P1）

| 项 | 说明 |
|----|------|
| `memory_search` / `conversation_search` 工具 | ✅ P2 |
| `RememberTool` → L1 双写（smart 开启时） | ✅ P1.5 |
| embedding + hybrid RRF | ✅ P2（FTS+LIKE RRF，`hybrid_search`） |
| `RememberTool` → 高 confidence L1 双写 | ✅ P1.5 |
| `threads.memory_mode` per-thread | ✅ P2（`ThreadRecord.memory_mode` + Engine） |
| Sidecar Gateway | 不实现（仅 Native 本地记忆） |
| L2 scene / L3 persona 生成 | ✅ P3（`l2_scenes` / `l3_persona` 接线） |
| FTS 中文：jieba 或专用 tokenizer | ✅ `fts_tokenize`（auto/simple + 可选 jieba） |
| embedding backfill 旧记忆向量 | ✅ `embedding_backfill_on_start` |
| embedding + 向量 hybrid RRF | ✅ `embedding_provider=openai` + `memory_embeddings` 表 |
| TUI 与 Workbench thread_id 统一 SSOT 文档化 | 文档 |

---

## 集成债登记（HANDOVER §9）

| 条目 | Stage | 内容 | 恢复条件 |
|------|-------|------|----------|
| ✅ memory.l1_live_api_test | P1.smart | `test_l1_extraction_live.py` 两则用例 | 批次 B 已还清；默认 CI 不跑 `-m live` |
| ⚠️ memory.acceptance_manual | P1.smart | C/D/E/F 已契约自动化；全链路 #2 五轮+真实 L1 live 仍建议手验 | `pytest tests/contract/test_memory_acceptance.py` |
