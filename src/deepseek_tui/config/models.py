from __future__ import annotations

from pathlib import Path
from typing import Any

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


class MemoryConfig(BaseModel):
    """[memory] subsection — mirrors Rust ``MemoryConfig``.

    Top-level ``Config.memory_path`` already covers the storage path.
    The nested table adds opt-in / mode toggles; runtime reads
    ``Config.memory_enabled`` heritage flag for backwards compat.
    """

    enabled: bool = True
    mode: str = "manual"
    max_entries: int = 500


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

    def effective_provider_config(self) -> ProviderConfig:
        configured = self.providers.get(self.provider, ProviderConfig())
        overrides: dict[str, Any] = {}
        if self.api_key is not None and self.provider == "deepseek":
            overrides["api_key"] = self.api_key
        if self.base_url is not None:
            overrides["base_url"] = self.base_url
        model = self.model or self.default_text_model
        if model is not None:
            overrides["model"] = model
        return ProviderConfig.model_validate(_deep_merge(configured.model_dump(), overrides))

    @classmethod
    def merge_dict(cls, base: Config, override: dict[str, Any]) -> Config:
        merged = _deep_merge(base.model_dump(mode="python"), override)
        return cls.model_validate(merged)
