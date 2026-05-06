# Phase A Audit — Protocol / Config / Secrets / State

**Date:** 2026-05-06  
**Scope:** Comparing Rust crates and Python modules for behavioral parity (100% fidelity target)

---

## Module Summary Table

| Module   | Rust LOC | Python LOC | Parity % | Status |
|----------|----------|-----------|----------|--------|
| protocol | 501      | 228       | ~45%     | MAJOR GAPS |
| config   | ~1555    | 482       | ~31%     | CRITICAL GAPS |
| secrets  | 677      | 50        | ~7%      | SEVERE GAPS |
| state    | 950      | 612       | ~64%     | MODERATE GAPS |
| **Total**| **3683** | **1372**  | **37%**  | **P0 PRIORITY** |

---

## 1. Protocol Module

### Rust Surface

**File:** `crates/protocol/src/lib.rs` (501 lines)

**Missing in Python (Summarized):**
- Envelope<T> generic wrapper
- 40+ core message types and enums
- EventFrame enum (20 variants) — streaming protocol entirely missing
- ThreadRequest enum (10 variants) — request routing missing
- ThreadResponse struct — response wrapper missing
- ExecApprovalRequestEvent — approval workflow missing
- MCP lifecycle event types (McpStartupStatus, McpStartupUpdateEvent, McpStartupCompleteEvent)
- ToolPayload enum (4 variants) — tool execution types missing
- NetworkPolicyAmendment and ReviewDecision types

### Python Surface

**Files:** protocol/ (228 total lines)

Only implements:
- Message protocol (Role enum, TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock)
- Streaming response types (StreamEvent, StreamError, StreamDone)
- MessageRequest for basic LLM requests
- ErrorEnvelope for error handling

### Gaps

**P0 Critical Items:**
1. EventFrame enum (20 variants) — streaming event model
2. ThreadRequest enum (10 variants) — request routing
3. Envelope<T> wrapper type
4. ThreadResponse struct
5. ExecApprovalRequestEvent and approval types
6. Thread struct (11 fields) — thread metadata
7. MCP startup event types (3 types)
8. ToolPayload enum (4 variants)
9. ToolOutput enum

**Impact:** Protocol module is 45% parity but missing the entire streaming event model and request routing — incompatible with IPC protocol.

---

## 2. Config Module

### Rust Surface

**Files:**
- `crates/config/src/lib.rs` (1414 lines)
- `crates/tui/src/config.rs` (139K+ bytes)

### Python Surface

**Files:** config/ (482 total lines)

### Gaps

**P0 Critical Items:**
1. ProviderKind enum (5 variants: Deepseek, NvidiaNim, Openai, Openrouter, Novita)
2. NetworkPolicyToml struct (default/allow/deny/audit)
3. LspConfigToml subsection
4. SkillsToml subsection
5. ProviderCapability matrix (13+ feature flags)

**P1 Major Items:**
1. 12+ missing top-level Config fields (memory_mode, max_inline_context_turns, approval_chain, namespace, use_realtime_api, use_deep_research, disable_file_tools, chatgpt_access_token, device_code_session, auth_mode, log_level, telemetry)
2. NotificationsConfig subsection
3. MemoryConfig subsection
4. SnapshotsConfig (Rust version more complete)
5. ApiProvider enum (18+ variants)
6. RequestPayloadMode enum
7. ModelDeprecation struct
8. TuiConfig struct
9. StatusItem enum
10. RetryPolicy struct
11. ContextConfig (Rust version likely larger)
12. CapacityConfig (10+ fields in Python; Rust has more)

**P2 Functions Missing:**
1. `provider_capability(provider, model)` — feature matrix lookup
2. `deprecation_for_model(model)` — deprecation warnings
3. `canonical_model_name(model)` — model alias resolution
4. `normalize_model_name(model)` — model normalization
5. Per-provider API key functions (has_api_key_for, save_api_key_for, clear_api_key)

**Impact:** Config module is 31% parity. Missing 50+ fields, 10+ enums, 15+ functions. Provider capability matrix entirely absent. Network policy missing.

---

## 3. Secrets Module

### Rust Surface

**File:** `crates/secrets/src/lib.rs` (677 lines)

### Python Surface

**Files:** secrets/ (50 total lines)

### Gaps

**P0 Critical Items:**
1. **Precedence order mismatch**: Rust is `keyring → env → none`; Python appears to be `env → config → keyring` (REVERSED!)
2. FileKeyringStore fallback (for headless Linux)
3. SecretsError enum (5 variants)
4. KeyringStore trait abstraction (4 methods)
5. DefaultKeyringStore with probe() method
6. Secrets::auto_detect() with fallback logic

**P1 Major Items:**
1. SecretsError enum with variants
2. Unix permission mode validation (0600)
3. Corrupt JSON recovery logic
4. File-based secret store at ~/.deepseek/secrets/secrets.json

**P2 Items:**
1. env_for(name) function with provider-specific fallback chain
2. 12 test cases (Python has 0)

**Impact:** Secrets module is 7% parity. CRITICAL: precedence appears inverted (security risk). No fallback for headless systems. No file permissions validation. Missing 3 implementations.

---

## 4. State Module

### Rust Surface

**File:** `crates/state/src/lib.rs` (950 lines)

Database schema: 7 tables + 7 indexes  
Methods: 17 StateStore methods

### Python Surface

**Files:** state/ (612 total lines, 9 files)

Database schema: 12 tables + 6 indexes  
Stores: 8+ classes with varying methods

### Gaps

**P0 Critical Items:**
1. **Timestamp type mismatch**: Rust uses i64 (Unix epoch); Python uses TEXT (ISO 8601)
2. ThreadMetadata schema incompatible (Rust: 19 fields; Python: 10 fields)
   - Missing: rollout_path, ephemeral, model_provider, cli_version, source, sandbox_policy, approval_mode, git_sha, git_branch, git_origin_url, memory_mode
3. Session index JSONL tracking (10 methods missing from Python)
4. Checkpoint scoping model inverted (thread vs session primary key)

**P1 Major Items:**
1. Add memory_mode field to threads
2. Add approval_mode, sandbox_policy to threads
3. Add git metadata (git_sha, git_branch, git_origin_url)
4. Add session_id to checkpoints (or reconcile thread vs session scoping)
5. Missing 7+ methods (get_thread_memory_mode, set_thread_memory_mode, find_thread_name_by_id, find_thread_names_by_ids, find_thread_path_by_name_str, mark_unarchived)

**P2 Items:**
1. Add idx_checkpoints_thread_created_at index
2. Transactions for multi-table operations

**Impact:** State module is 64% parity but has critical schema mismatches. Timestamp type incompatibility breaks data portability. ThreadMetadata schema incompatible (19 vs 10 fields). Session tracking entirely absent from Rust (Python has sessions table).

---

## Phase A Action Items (Consolidated Priority List)

### P0 CRITICAL — FIX IMMEDIATELY (745 LOC, 2-3 weeks)

1. **Protocol: EventFrame enum (20 variants)** — streaming event model
2. **Protocol: ThreadRequest enum (10 variants)** — request routing
3. **Protocol: Envelope<T> wrapper** — request/response serialization
4. **Secrets: Fix precedence to keyring→env→none** — security fix
5. **Secrets: FileKeyringStore fallback** — headless Linux support
6. **Config: ProviderKind enum** — provider dispatch
7. **Config: NetworkPolicyToml** — network policy enforcement
8. **State: Fix timestamp types (i64→TEXT)** — data interop
9. **State: ThreadMetadata with 19 fields** — metadata schema
10. **State: Session index JSONL tracking** — session name lookup

### P1 MAJOR — NEXT SPRINT (550 LOC, 1-2 weeks)

11. **Config: LspConfigToml subsection**
12. **Config: SkillsToml subsection**
13. **Config: 12+ missing top-level fields** (memory_mode, approval_chain, etc.)
14. **Config: ProviderCapability matrix**
15. **Protocol: Thread struct (11 fields)**
16. **Protocol: ThreadResponse struct**
17. **Protocol: ApprovalRequest types**
18. **State: Reconcile checkpoint scoping** (thread vs session)
19. **Secrets: SecretsError enum**
20. **State: Memory mode methods**

### P2 BACKLOG (550 LOC, future)

21-28. Model canonicalization, MCP events, ToolPayload, ToolOutput, per-provider API key functions, missing indexes, transactions, keyring trait abstraction

---

## Conclusion

**Overall Parity:** 37% (1372 Python LOC vs 3683 Rust LOC)

**Blocking Issues:** 10 critical gaps requiring immediate fixes before production use

**Timeline:** 3-4 weeks to reach minimal parity (P0+P1)

**Recommendation:** Prioritize P0 items in order (protocol → secrets → config → state) to unblock streaming protocol and fix security precedence issue in secrets module.

