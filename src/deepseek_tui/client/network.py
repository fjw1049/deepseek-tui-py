"""User-level model API routing, re-read for each request without restarting streams."""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deepseek_tui.config.paths import user_deepseek_dir


class NetworkSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["system", "direct"] = "system"
    bypassHosts: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("bypassHosts")
    @classmethod
    def validate_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for value in hosts:
            host = value.strip().lower()
            try:
                address = ipaddress.ip_address(host.strip("[]"))
                if (address.version == 6) != (host.startswith("[") and host.endswith("]")):
                    raise ValueError("IPv6 addresses must use brackets")
            except ValueError:
                if len(host) > 253 or not all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in host.rstrip(".").split(".")
                ):
                    raise ValueError("Use an exact domain or IP address") from None
            result.append(host)
        return tuple(dict.fromkeys(result))

    def http_options(self) -> dict:
        # An explicit direct mount retains environment CA/certificate settings.
        hosts = {f"all://{host}": None for host in self.bypassHosts}
        if self.mode == "direct":
            return {"mounts": {"all://": None, "http://": None, "https://": None}}
        return {"mounts": hosts}


def read_network_settings() -> NetworkSettings:
    try:
        return NetworkSettings.model_validate_json(
            (user_deepseek_dir() / "network.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return NetworkSettings()

