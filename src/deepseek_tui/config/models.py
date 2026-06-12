from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Config errors (formerly config/errors.py) --------------------------------


class ConfigError(Exception):
    pass


class InvalidConfigError(ConfigError):
    pass


class UnknownProfileError(ConfigError):
    pass


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if value is None:
            continue
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


class ProviderConfig(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout: int = 120
    rate_limit: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class UiConfig(BaseModel):
    color_scheme: str = "default"
    show_thinking: bool = True
    theme: str = "default"
    auto_compact: bool = False
    show_tool_details: bool = True
    locale: str = "auto"
    default_mode: str = "agent"
    max_history: int = 1000
    alternate_screen: str = "auto"
    mouse_capture: bool = True
    osc8_links: bool = True
    notify_method: str = "auto"
    notify_threshold_secs: float = 30.0
    frame_refresh_hz: float = 30.0


class StateConfig(BaseModel):
    database_path: Path = Path(".deepseek/state.db")
    autosave: bool = True


class RetryConfig(BaseModel):
    enabled: bool = True
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0


class FeatureConfig(BaseModel):
    shell_tool: bool = True
    subagents: bool = True
    tasks: bool = True
    web_search: bool = True
    apply_patch: bool = True
    mcp: bool = True
    exec_policy: bool = True
    # 2026-05-15: opt-in. When True, AutomationManager + scheduler are
    # constructed in ``create_tool_runtime`` and the 8 automation tools
    # are registered. Default False because automations have side effects
    # (durable scheduled fires) and should be a deliberate choice.
    automations: bool = False


class AutomationEmailConfig(BaseModel):
    """SMTP/IMAP for automation delivery — lives under ``[automation.email]`` in config.toml."""

    imap_host: str | None = None
    imap_port: int = 993
    ssl: bool = True
    mailbox: str = "INBOX"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_ssl: bool = False
    smtp_starttls: bool = True
    username: str | None = None
    from_addr: str | None = None
    to_addr: str | None = None
    password: str | None = None
    password_env: str | None = None


class AutomationFeishuConfig(BaseModel):
    """Feishu / Lark bot credentials and default delivery target (``[automation.feishu]``)."""

    app_id: str | None = None
    app_secret: str | None = None
    domain: str = "feishu"
    chat_id: str | None = None


class AutomationConfig(BaseModel):
    """Defaults for HTTP triggers / baidu-hotsearch one-shot (``[automation]``)."""

    mail_to: str | None = None
    feishu_chat_id: str | None = None
    email: AutomationEmailConfig = Field(default_factory=AutomationEmailConfig)
    feishu: AutomationFeishuConfig = Field(default_factory=AutomationFeishuConfig)


class SnapshotConfig(BaseModel):
    enabled: bool = True
    max_age_days: int = 7


class ContextConfig(BaseModel):
    enabled: bool = False
    verbatim_window_turns: int = 16
    l1_threshold: int = 192_000
    l2_threshold: int = 384_000
    l3_threshold: int = 576_000
    cycle_threshold: int = 768_000
    seam_model: str = "deepseek-v4-flash"


class CapacityConfig(BaseModel):
    enabled: bool = False
    low_risk_max: float = 0.50
    medium_risk_max: float = 0.62
    severe_min_slack: float = -0.25
    severe_violation_ratio: float = 0.40
    refresh_cooldown_turns: int = 6
    replan_cooldown_turns: int = 5
    max_replay_per_turn: int = 1
    min_turns_before_guardrail: int = 4
    profile_window: int = 8


class SubagentConfig(BaseModel):
    max_concurrent: int = 10
    default_model: str | None = None
    worker_model: str | None = None
    explorer_model: str | None = None
    review_model: str | None = None
    custom_model: str | None = None
    models: dict[str, str] = Field(default_factory=dict)


class ShellHookConfig(BaseModel):
    """Deprecated observability shell bridge — prefer ``LifecycleHookEntry``."""

    event: str
    command: str
    name: str | None = None
    timeout_secs: float = 30.0


class LifecycleHookEntry(BaseModel):
    """Single lifecycle hook — mirrors Rust ``hooks::Hook`` (hooks.rs:102-130)."""

    event: str
    command: str
    condition: dict[str, Any] | None = None
    timeout_secs: float = 30.0
    background: bool = False
    continue_on_error: bool = True
    name: str | None = None


class HooksConfig(BaseModel):
    """Hooks configuration.

    Observability sinks (``crates/hooks``): stdout / JSONL / webhook.
    Lifecycle hooks (``crates/tui/src/hooks.rs``): ``[[hooks.hooks]]`` entries.
    """

    stdout: bool = False
    jsonl_path: Path | None = None
    webhook_urls: list[str] = Field(default_factory=list)
    shell_hooks: list[ShellHookConfig] = Field(default_factory=list)
    enabled: bool = True
    hooks: list[LifecycleHookEntry] = Field(default_factory=list)
    default_timeout_secs: float | None = None
    working_dir: Path | None = None


class NotificationsConfig(BaseModel):
    """Terminal notification settings — mirrors Rust ``NotificationsConfig``.

    ``method`` / ``threshold_secs`` / ``enabled`` are consumed by
    ``DeepSeekTUI._maybe_notify_turn_done`` (see ``tui/app.py``). When the
    nested ``method`` / ``threshold_secs`` are unset, the loader falls
    back to ``Config.ui.notify_*`` for backwards compatibility.
    ``include_subagent`` / ``include_task`` are accepted but not yet
    routed; they're tracked as a Stage 6 follow-up.
    """

    method: str | None = None
    threshold_secs: float | None = None
    enabled: bool = True
    include_subagent: bool = False
    include_task: bool = False


class NetworkPolicyConfig(BaseModel):
    """Network access policy — mirrors Rust ``NetworkPolicyToml``.

    Stage 2.7 deferred OS-level sandboxing; this struct accepts the TOML
    so configs from the Rust binary load cleanly. ``rules`` and
    ``amendments`` are stored as raw dicts (Pydantic doesn't enforce the
    inner shape yet) — wiring them through to ``ExecPolicyEngine`` is
    tracked in HANDOVER as a follow-up.
    """

    enabled: bool = False
    default_action: str = "ask"
    rules: list[dict[str, Any]] = Field(default_factory=list)
    amendments: list[dict[str, Any]] = Field(default_factory=list)


class SkillsConfig(BaseModel):
    """[skills] subsection — mirrors Rust ``SkillsConfig``.

    Top-level ``Config.skills_dir`` already covers the install path. The
    nested table adds registry URL + max install size; both are accepted
    so user TOML loads, but we don't yet drive a remote registry fetcher.
    """

    enabled: bool = True
    registry_url: str | None = None
    max_install_size_mb: int = 50
    auto_update: bool = False


class MemorySmartConfig(BaseModel):
    """[memory.smart] — native L0/L1 smart memory (TencentDB-style, Python-native)."""

    enabled: bool = False
    data_dir: str = ""
    recall_enabled: bool = True
    capture_enabled: bool = True
    recall_timeout_ms: int = 5000
    flush_timeout_ms: int = 2000
    recall_score_threshold: float = 0.3
    recall_limit: int = 8
    capture_min_user_chars: int = 20
    capture_skip_slash_commands: bool = True
    l1_every_n: int = 5
    l1_warmup_enabled: bool = True
    l1_idle_timeout_seconds: int = 600
    l1_confidence_min: float = 0.6
    l1_max_per_session: int = 20
    l2_enabled: bool = True
    l2_delay_after_l1_seconds: int = 90
    l2_min_interval_seconds: int = 900
    l2_max_interval_seconds: int = 3600
    l2_session_active_window_hours: int = 24
    l2_max_scenes: int = 15
    l3_persona_llm_enabled: bool = True
    l3_persona_interval: int = 50
    l1_decay_half_life_days: int = 180
    retention_days: int = 0
    cleanup_on_start: bool = False
    l1_inject_position: str = "user"
    hybrid_search: bool = True
    embedding_provider: str = "none"
    embedding_model: str = "text-embedding-3-large"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_dimensions: int | None = None
    embedding_timeout_ms: int = 90000
    embedding_dedup_threshold: float = 0.92
    embedding_backfill_on_start: bool = False
    fts_tokenizer: str = "auto"

    def embedding_enabled(self) -> bool:
        return self.embedding_provider.strip().lower() in ("openai", "remote")

    def resolved_data_dir(self) -> Path:
        from deepseek_tui.config.paths import user_memory_data_dir

        if self.data_dir.strip():
            return Path(self.data_dir).expanduser()
        return user_memory_data_dir()


class MemoryConfig(BaseModel):
    """[memory] subsection — mirrors Rust ``MemoryConfig``.

    Top-level ``Config.memory_path`` already covers the storage path.
    Default **off** (Rust parity): opt-in via ``[memory] enabled = true``
    or ``DEEPSEEK_MEMORY=on``.
    """

    enabled: bool = False
    mode: str = "manual"
    max_entries: int = 500
    smart: MemorySmartConfig = Field(default_factory=MemorySmartConfig)




class ServerConfig(BaseModel):
    """[server] subsection for HTTP server settings."""

    host: str = "127.0.0.1"
    port: int = 8787


class LoggingConfig(BaseModel):
    """Per-hour rotating file logging — consumed by :func:`logging_setup.setup_logging`.

    Defaults match the design discussion (2026-05-10): INFO level, text
    format, ``./.deepseek/logs/`` rotation directory (project-local since
    2026-05-11), 24-hour retention, no console fallback. Tests should
    leave ``enabled=False`` so they don't spray log files into ``tmp_path``.
    """

    enabled: bool = True
    level: str = "INFO"
    dir: Path = Path(".deepseek/logs")
    console: bool = False
    keep_hours: int = 24
    # Optional per-logger level overrides — useful when the user wants
    # ``deepseek_tui.engine.turn_loop = "DEBUG"`` while leaving the rest
    # at INFO. Keys are full logger names; values are level strings.
    per_logger: dict[str, str] = Field(default_factory=dict)


class LspSettings(BaseModel):
    """Post-edit LSP diagnostics settings — Stage 4.4.

    Mirrors Rust ``LspConfig`` (crates/tui/src/lsp/mod.rs:55-103). The
    engine collects diagnostics after every successful edit tool and
    injects them as a synthetic user message before the next API call.
    """

    enabled: bool = False
    poll_after_edit_ms: int = 5000
    max_diagnostics_per_file: int = 20
    include_warnings: bool = False
    servers: dict[str, list[str]] = Field(default_factory=dict)


class AuthConfig(BaseModel):
    """HTTP API authentication settings.

    ``mode`` controls whether API endpoints require authentication:
    - ``"none"`` — open to all (default, local-only deployments)
    - ``"api_key"`` — require a valid API key via header

    ``api_keys`` is a list of accepted plain-text keys. In production,
    prefer loading these from environment variables or a secrets vault.

    ``header_name`` overrides the default ``X-API-Key`` header.
    """

    mode: str = "none"
    api_keys: list[str] = Field(default_factory=lambda: [])
    header_name: str = "X-API-Key"


class ProfileConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    default_text_model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    approval_policy: str | None = None
    sandbox_mode: str | None = None
    allow_shell: bool | None = None
    max_subagents: int | None = None
    mcp_config_path: Path | None = None
    notes_path: Path | None = None
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    ui: UiConfig | None = None
    state: StateConfig | None = None
    features: FeatureConfig | None = None


class Config(BaseModel):
    provider: str = "deepseek"
    default_text_model: str = "deepseek-v4-pro"
    model: str | None = None
    profile: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    approval_policy: str = "on-request"
    sandbox_mode: str = "workspace-write"
    allow_shell: bool = True
    tavily_api_key: str | None = None
    anysearch_api_key: str | None = None
    managed_config_path: Path | None = None
    requirements_path: Path | None = None
    skills_dir: Path = Path(".deepseek/skills")
    mcp_config_path: Path = Path(".deepseek/mcp.json")
    notes_path: Path = Path(".deepseek/notes.txt")
    memory_path: Path = Path(".deepseek/memory.md")
    max_subagents: int = 10
    instructions: list[Path] = Field(default_factory=list)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    ui: UiConfig = Field(default_factory=UiConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    snapshots: SnapshotConfig = Field(default_factory=SnapshotConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    capacity: CapacityConfig = Field(default_factory=CapacityConfig)
    subagents: SubagentConfig = Field(default_factory=SubagentConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    lsp: LspSettings = Field(default_factory=LspSettings)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    # Top-level subsection mirrors of Rust ``ConfigToml``. Accept the TOML
    # so user configs written for the Rust binary load cleanly; Stage 6
    # wires these fields into runtime behavior. ``tools_file`` is recorded
    # but never read today — same parity intent.
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    network: NetworkPolicyConfig = Field(default_factory=NetworkPolicyConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    tools_file: Path | None = None
    # Cycle / seam toggles consumed by ``Engine.create``. Mirror Rust
    # ``cycle_manager.rs`` + ``seam_manager.rs`` opt-in behavior. Off by
    # default so existing tests stay deterministic; long-running real
    # sessions can flip these via TOML once they're ready for cycle
    # archive-and-replay.
    cycle_enabled: bool = False
    seam_enabled: bool = False

    def resolved_database_path(self) -> Path:
        return self.state.database_path.expanduser()

    def resolved_memory_path(self) -> Path:
        """Resolve memory file path (``DEEPSEEK_MEMORY_PATH`` > config > default)."""
        from deepseek_tui.config.paths import expand_path, user_memory_path

        override = os.environ.get("DEEPSEEK_MEMORY_PATH")
        if override:
            return expand_path(override)
        raw = self.memory_path
        if raw.is_absolute():
            return expand_path(raw)
        return user_memory_path()

    def memory_enabled(self) -> bool:
        """Whether user-memory injection is active (Rust ``Config::memory_enabled``)."""
        from deepseek_tui.memory.user_memory import memory_enabled_from_env

        env = memory_enabled_from_env()
        if env is not None:
            return env
        return self.memory.enabled

    def smart_memory_enabled(self) -> bool:
        """Whether native smart memory (L0/L1/FTS) is active."""
        return self.memory.smart.enabled

    def effective_provider_config(self) -> ProviderConfig:
        from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

        configured = self.providers.get(self.provider, ProviderConfig())
        overrides: dict[str, Any] = {}
        if self.api_key is not None and self.provider == "deepseek":
            overrides["api_key"] = self.api_key
        if self.base_url is not None:
            overrides["base_url"] = self.base_url
        model = self.model or self.default_text_model
        if model is not None:
            overrides["model"] = model
        merged = ProviderConfig.model_validate(
            _deep_merge(configured.model_dump(), overrides)
        )
        # Fill gaps from the provider registry so switching provider without
        # a ``[providers.X]`` table doesn't silently fall back to the
        # DeepSeek endpoint.
        defaults = PROVIDER_DEFAULTS.get(self.provider)
        if defaults is not None:
            if merged.base_url is None:
                merged.base_url = defaults.base_url
            if merged.model is None:
                merged.model = defaults.model
        return merged

    @classmethod
    def merge_dict(cls, base: Config, override: dict[str, Any]) -> Config:
        merged = _deep_merge(base.model_dump(mode="python"), override)
        return cls.model_validate(merged)
