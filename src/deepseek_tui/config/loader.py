from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from deepseek_tui.config.env_mapping import read_env_overrides
from deepseek_tui.config.errors import InvalidConfigError, UnknownProfileError
from deepseek_tui.config.models import Config
from deepseek_tui.config.paths import (
    DEFAULT_MANAGED_CONFIG_PATH,
    DEFAULT_REQUIREMENTS_PATH,
    default_config_path,
    dotenv_path,
    expand_path,
    load_dotenv_file,
    project_config_path,
)

try:
    import tomllib as toml_impl  # type: ignore[import-untyped]
except ModuleNotFoundError:
    import tomli as toml_impl  # type: ignore[import-not-found]


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
        load_dotenv_file(dotenv_path(workspace))
        config = Config()
        discovered_path = self._discover_config_file(config_path)
        if discovered_path is not None:
            config = self._load_file(discovered_path)

        active_profile = profile_name or config.profile
        if active_profile:
            config = self._merge_profile(config, active_profile)
            config.profile = active_profile

        if not no_project_config:
            project_path = project_config_path(workspace)
            if project_path.exists():
                config = Config.merge_dict(config, self._load_dict(project_path))

        env_overrides = read_env_overrides()
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

        return config

    def _discover_config_file(self, config_path: Path | None) -> Path | None:
        if config_path is not None:
            return expand_path(config_path)

        candidates = [
            Path.cwd() / "deepseek-tui.toml",
            Path.cwd() / ".deepseek-tui.toml",
            Path.home() / ".config" / "deepseek-tui" / "config.toml",
            default_config_path(),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

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
