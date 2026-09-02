from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from deepseek_tui.config.models import Config, InvalidConfigError, UnknownProfileError
from deepseek_tui.config.paths import (
    DEFAULT_MANAGED_CONFIG_PATH,
    DEFAULT_REQUIREMENTS_PATH,
    dotenv_path,
    expand_path,
    load_dotenv_file,
    project_config_path,
    user_config_path,
)

try:
    import tomllib as toml_impl  # type: ignore[import-untyped]
except ModuleNotFoundError:
    import tomli as toml_impl  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

ENV_TO_FIELD: dict[str, tuple[str, ...]] = {
    "DEEPSEEK_PROVIDER": ("provider",),
    "DEEPSEEK_TUI_PROVIDER": ("provider",),
    "DEEPSEEK_MODEL": ("model",),
    "DEEPSEEK_DEFAULT_TEXT_MODEL": ("default_text_model",),
    "DEEPSEEK_TUI_MODEL": ("model",),
    "DEEPSEEK_TUI_PROFILE": ("profile",),
    "DEEPSEEK_TUI_SHOW_THINKING": ("ui", "show_thinking"),
    "DEEPSEEK_LOG_LEVEL": ("logging", "level"),
    "DEEPSEEK_API_KEY": ("providers", "deepseek", "api_key"),
    "DEEPSEEK_BASE_URL": ("providers", "deepseek", "base_url"),
    "DEEPSEEK_SKILLS_DIR": ("skills_dir",),
    "DEEPSEEK_MCP_CONFIG": ("mcp_config_path",),
    "DEEPSEEK_NOTES_PATH": ("notes_path",),
    "DEEPSEEK_ALLOW_SHELL": ("allow_shell",),
    "DEEPSEEK_APPROVAL_POLICY": ("approval_policy",),
    "DEEPSEEK_SANDBOX_MODE": ("sandbox_mode",),
    "DEEPSEEK_MANAGED_CONFIG_PATH": ("managed_config_path",),
    "DEEPSEEK_REQUIREMENTS_PATH": ("requirements_path",),
    "DEEPSEEK_MAX_SUBAGENTS": ("max_subagents",),
    "DEEPSEEK_CAPACITY_ENABLED": ("capacity", "enabled"),
    "DEEPSEEK_CAPACITY_LOW_RISK_MAX": ("capacity", "low_risk_max"),
    "DEEPSEEK_CAPACITY_MEDIUM_RISK_MAX": ("capacity", "medium_risk_max"),
}


def read_env_overrides(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if environ is None else environ
    overrides: dict[str, Any] = {}
    for env_name, path in ENV_TO_FIELD.items():
        value = source.get(env_name)
        if value is None:
            continue
        typed_value: Any = value
        if path[-1] in {"show_thinking", "allow_shell", "enabled"}:
            typed_value = value.lower() in {"1", "true", "yes", "on"}
        elif path[-1] in {
            "skills_dir",
            "mcp_config_path",
            "notes_path",
            "managed_config_path",
            "requirements_path",
        }:
            typed_value = Path(value)
        elif path[-1] in {"max_subagents"}:
            typed_value = int(value)
        elif path[-1] in {"low_risk_max", "medium_risk_max"}:
            typed_value = float(value)
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = typed_value
    return overrides


# Security-sensitive keys that project-level config sources (cwd
# ``deepseek-tui.toml`` / ``.deepseek-tui.toml`` and
# ``<workspace>/.deepseek/config.toml``) must never set: they come from
# cloned, potentially untrusted repos, while these keys relax approvals,
# disable sandboxing, redirect provider endpoints (exfiltrating credentials
# API key), or install shell hooks (clone-to-RCE). The path-pointer keys
# (``managed_config_path`` / ``mcp_config_path`` / ``requirements_path`` /
# ``skills_dir``) are blocked because they would let a repo redirect the
# load location of security-relevant files (managed policy, MCP server
# definitions, requirements, executable skills) to files inside the repo —
# an indirect bypass of this very filter. Only the pointer is stripped;
# content of managed/user-designated files remains trusted.
_PROJECT_SENSITIVE_KEYS = (
    "approval_policy",
    "sandbox_mode",
    "allow_shell",
    "api_key",
    "base_url",
    "hooks",
    "profile",
    "managed_config_path",
    "mcp_config_path",
    "requirements_path",
    "skills_dir",
)
_PROJECT_SENSITIVE_FEATURE_KEYS = ("automations",)
_PROJECT_SENSITIVE_PROVIDER_KEYS = (
    "api_key",
    "base_url",
    "extra_headers",
    "extra_body",
)

# Same idea for the workspace ``.env``: these map (via ``ENV_TO_FIELD``)
# onto the sensitive fields above.
_PROJECT_SENSITIVE_ENV_KEYS = frozenset(
    {
        "DEEPSEEK_APPROVAL_POLICY",
        "DEEPSEEK_SANDBOX_MODE",
        "DEEPSEEK_ALLOW_SHELL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MANAGED_CONFIG_PATH",
        "DEEPSEEK_MCP_CONFIG",
        "DEEPSEEK_REQUIREMENTS_PATH",
        "DEEPSEEK_SKILLS_DIR",
        # Trust-root pointers: not in ENV_TO_FIELD, but they redirect
        # user_config_path() / user_deepseek_dir() / active profile
        # before the overlay filter runs.
        "DEEPSEEK_HOME",
        "DEEPSEEK_CONFIG_PATH",
        "DEEPSEEK_TUI_PROFILE",
    }
)


def strip_project_security_keys(
    raw: dict[str, Any], source: Path
) -> dict[str, Any]:
    """Drop security-sensitive keys from a project-level config document.

    Non-sensitive keys (model, locale, instructions, ...) still apply.
    Each stripped key is logged as a warning.
    """
    cleaned = dict(raw)
    for key in _PROJECT_SENSITIVE_KEYS:
        if key in cleaned:
            cleaned.pop(key)
            logger.warning(
                "project config ignored security-sensitive key: %s (%s)", key, source
            )
    features = cleaned.get("features")
    if isinstance(features, dict):
        features = dict(features)
        for key in _PROJECT_SENSITIVE_FEATURE_KEYS:
            if key in features:
                features.pop(key)
                logger.warning(
                    "project config ignored security-sensitive key: features.%s (%s)",
                    key,
                    source,
                )
        cleaned["features"] = features
    providers = cleaned.get("providers")
    if isinstance(providers, dict):
        stripped_providers: dict[str, Any] = {}
        for name, table in providers.items():
            if isinstance(table, dict):
                table = dict(table)
                for key in _PROJECT_SENSITIVE_PROVIDER_KEYS:
                    if key in table:
                        table.pop(key)
                        logger.warning(
                            "project config ignored security-sensitive key: "
                            "providers.%s.%s (%s)",
                            name,
                            key,
                            source,
                        )
            stripped_providers[name] = table
        cleaned["providers"] = stripped_providers
    profiles = cleaned.get("profiles")
    if isinstance(profiles, dict):
        # A project file can smuggle sensitive keys past the top-level
        # strip via ``[profiles.x]`` + ``profile = "x"``; clean each
        # profile table the same way.
        cleaned_profiles: dict[str, Any] = {}
        for name, table in profiles.items():
            if isinstance(table, dict):
                table = strip_project_security_keys(table, source)
            cleaned_profiles[name] = table
        cleaned["profiles"] = cleaned_profiles
    return cleaned


class ConfigLoader:
    def load(
        self,
        config_path: Path | None = None,
        profile_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        workspace: Path | None = None,
        no_project_config: bool = False,
    ) -> Config:
        dotenv_values = load_dotenv_file(
            dotenv_path(workspace), blocked_keys=_PROJECT_SENSITIVE_ENV_KEYS
        )
        config = Config()
        discovered_path = self._discover_config_file(config_path)
        if discovered_path is not None:
            if self._is_project_level(discovered_path):
                config = self._load_project_overlay(discovered_path)
            else:
                config = self._load_file(discovered_path)

        active_profile = profile_name or config.profile
        if active_profile:
            config = self._merge_profile(config, active_profile)
            config.profile = active_profile

        if not no_project_config:
            project_path = project_config_path(workspace)
            if project_path.exists():
                project_raw = strip_project_security_keys(
                    self._load_dict(project_path), source=project_path
                )
                config = Config.merge_dict(config, project_raw)

        env_overrides = read_env_overrides({**dotenv_values, **os.environ})
        if env_overrides:
            config = Config.merge_dict(config, env_overrides)

        cli_overrides: dict[str, str] = {}
        if provider is not None:
            cli_overrides["provider"] = provider
        if model is not None:
            cli_overrides["model"] = model
        if cli_overrides:
            config = Config.merge_dict(config, cli_overrides)

        managed_path = config.managed_config_path or DEFAULT_MANAGED_CONFIG_PATH
        managed_path = expand_path(managed_path)
        if managed_path.exists():
            config = Config.merge_dict(config, self._load_dict(managed_path))

        requirements_path = config.requirements_path or DEFAULT_REQUIREMENTS_PATH
        requirements_path = expand_path(requirements_path)
        if requirements_path.exists():
            self._validate_requirements(config, requirements_path)

        # Make [providers.X] context_window (and the 500K custom-model
        # default) visible to context_window_for_model() everywhere.
        from deepseek_tui.config.providers import register_provider_context_windows

        register_provider_context_windows(config)

        return config

    def _discover_config_file(self, config_path: Path | None) -> Path | None:
        if config_path is not None:
            return expand_path(config_path)

        candidates = [
            Path.cwd() / "deepseek-tui.toml",
            Path.cwd() / ".deepseek-tui.toml",
            Path.home() / ".config" / "deepseek-tui" / "config.toml",
            user_config_path(),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _is_project_level(self, path: Path) -> bool:
        """Whether ``path`` should be treated as an untrusted project file.

        True for the two cwd candidates and for any file inside the cwd
        (e.g. an explicit relative ``--config ./deepseek-tui.toml``), except
        the user-level candidates, which stay trusted even when the cwd is
        the user's home. Comparison is done on resolved paths so relative
        or symlinked spellings cannot escape the filter.
        """
        resolved = path.resolve()
        cwd = Path.cwd().resolve()
        if resolved in (
            cwd / "deepseek-tui.toml",
            cwd / ".deepseek-tui.toml",
        ):
            return True
        user_candidates = (
            Path.home() / ".config" / "deepseek-tui" / "config.toml",
            user_config_path(),
        )
        if any(resolved == candidate.resolve() for candidate in user_candidates):
            return False
        return resolved.is_relative_to(cwd)

    def _load_project_overlay(self, path: Path) -> Config:
        """Load a project-level file as an overlay on the user-level base.

        The user config (first existing of ``~/.config/deepseek-tui/
        config.toml`` and ``user_config_path()``) stays the trusted base;
        the stripped project document only overlays its non-sensitive keys.
        Without a user base the behavior matches a plain stripped load.
        """
        project_raw = strip_project_security_keys(self._load_dict(path), source=path)
        base: Config | None = None
        resolved = path.resolve()
        for candidate in (
            Path.home() / ".config" / "deepseek-tui" / "config.toml",
            user_config_path(),
        ):
            # Never let the project file become its own trusted base (e.g.
            # via $DEEPSEEK_CONFIG_PATH pointing into the repo).
            if candidate.exists() and candidate.resolve() != resolved:
                base = self._load_file(candidate)
                break
        try:
            if base is None:
                return Config.model_validate(project_raw)
            return Config.merge_dict(base, project_raw)
        except ValidationError as exc:
            raise InvalidConfigError(f"Invalid config file: {path}") from exc

    def _load_file(self, path: Path) -> Config:
        try:
            return Config.model_validate(self._load_dict(path))
        except ValidationError as exc:
            raise InvalidConfigError(f"Invalid config file: {path}") from exc

    def _load_dict(self, path: Path) -> dict[str, object]:
        try:
            with path.open("rb") as fh:
                raw = toml_impl.load(fh)
                if not isinstance(raw, dict):
                    raise InvalidConfigError(f"Invalid config file: {path}")
                return raw
        except toml_impl.TOMLDecodeError as exc:
            raise InvalidConfigError(f"Invalid config file: {path}") from exc

    def _merge_profile(self, config: Config, profile_name: str) -> Config:
        profile = config.profiles.get(profile_name)
        if profile is None:
            raise UnknownProfileError(f"Unknown profile: {profile_name}")
        return Config.merge_dict(config, profile.model_dump(mode="python", exclude_none=True))

    def _validate_requirements(self, config: Config, requirements_path: Path) -> None:
        try:
            with requirements_path.open("rb") as fh:
                raw = toml_impl.load(fh)
        except toml_impl.TOMLDecodeError as exc:
            raise InvalidConfigError(f"Invalid requirements file: {requirements_path}") from exc

        approval_values = raw.get("allowed_approval_policies")
        if isinstance(approval_values, list) and config.approval_policy not in approval_values:
            raise InvalidConfigError(
                f"approval_policy={config.approval_policy!r} is not allowed by {requirements_path}"
            )
        sandbox_values = raw.get("allowed_sandbox_modes")
        if isinstance(sandbox_values, list) and config.sandbox_mode not in sandbox_values:
            raise InvalidConfigError(
                f"sandbox_mode={config.sandbox_mode!r} is not allowed by {requirements_path}"
            )
