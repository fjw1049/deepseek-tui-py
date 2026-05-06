from __future__ import annotations


class ConfigError(Exception):
    pass


class InvalidConfigError(ConfigError):
    pass


class UnknownProfileError(ConfigError):
    pass
