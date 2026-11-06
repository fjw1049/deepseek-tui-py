"""User-level model API routing, re-read for each request without restarting streams."""

from __future__ import annotations

import ipaddress
import re
import urllib.request
from typing import Literal

import httpx
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

    def http_options(self, url: str = "") -> dict:
        # An explicit direct mount retains environment CA/certificate settings.
        hosts = {f"all://{host}": None for host in self.bypassHosts}
        if self.mode == "direct":
            return {"mounts": {"all://": None, "http://": None, "https://": None}}
        host = _url_host(url)
        proxy = _hidden_os_proxy(url)
        if host and (
            _system_bypasses(host, restored_proxy=bool(proxy))
            or urllib.request.proxy_bypass_environment(host)
        ):
            # Following the system proxy includes its exception list, as the
            # Workbench connection test (Electron) does.
            hosts[f"all://{f'[{host}]' if ':' in host else host}"] = None
        options: dict = {"mounts": hosts}
        if proxy:
            options["proxy"] = proxy
        return options


def _url_host(url: str) -> str:
    try:
        return httpx.URL(url).host if url else ""
    except Exception:  # noqa: BLE001 — an invalid URL fails on the request itself
        return ""


def _os_proxies() -> dict[str, str]:
    reader = getattr(urllib.request, "getproxies_macosx_sysconf", None) or getattr(
        urllib.request, "getproxies_registry", None
    )
    try:
        return reader() if reader else {}
    except Exception:  # noqa: BLE001 — unreadable OS settings mean no proxy
        return {}


def _hidden_os_proxy(url: str) -> str | None:
    """The OS proxy for ``url`` when the environment hides it from httpx.

    urllib, and so httpx, reads the OS proxy settings only while no
    ``*_proxy`` variable is set. The browser service sets ``NO_PROXY`` to keep
    CDP on loopback, which on its own would send every later request direct.
    """
    if set(urllib.request.getproxies_environment()) - {"no"}:
        return None  # Explicit proxy variables: httpx applies them itself.
    try:
        scheme = httpx.URL(url).scheme if url else ""
    except Exception:  # noqa: BLE001 — an invalid URL fails on the request itself
        return None
    return _os_proxies().get(scheme) or None


def _system_bypasses(host: str, *, restored_proxy: bool) -> bool:
    """Whether the OS proxy settings exempt ``host`` (macOS: "Bypass proxy settings for")."""
    try:
        if urllib.request.proxy_bypass(host):
            return True
        # NO_PROXY can hide the macOS exception list along with the proxy itself.
        native_bypass = getattr(urllib.request, "proxy_bypass_macosx_sysconf", None)
        return bool(restored_proxy and native_bypass and native_bypass(host))
    except Exception:  # noqa: BLE001 — unreadable OS settings mean no exemption
        return False


def read_network_settings() -> NetworkSettings:
    try:
        return NetworkSettings.model_validate_json(
            (user_deepseek_dir() / "network.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return NetworkSettings()

