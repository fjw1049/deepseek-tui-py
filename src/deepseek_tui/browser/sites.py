"""Group cookie hosts into sites and flag sites whose sign-in grants broad access."""

from __future__ import annotations

import ipaddress

# Country-code TLDs commonly register under a generic second level (b.com.cn, b.co.uk).
# A heuristic instead of the full public suffix list: hosted subdomains such as
# a.github.io group under github.io, which only widens one choice.
_GENERIC_SECOND_LEVEL = frozenset({"com", "net", "org", "gov", "edu", "co", "ac", "or", "ne", "go"})

# Accounts that reach mail, money, infrastructure or other passwords. Not imported
# unless the user explicitly selects them.
SENSITIVE_SITES = frozenset({
    # Mail and identity
    "google.com", "gmail.com", "live.com", "outlook.com", "hotmail.com", "microsoft.com",
    "microsoftonline.com", "office.com", "yahoo.com", "icloud.com", "apple.com", "proton.me",
    "protonmail.com", "qq.com", "163.com", "126.com", "yeah.net", "foxmail.com", "sina.com",
    "sina.com.cn",
    # Payment, banking and exchanges
    "paypal.com", "stripe.com", "alipay.com", "tenpay.com", "unionpay.com", "95516.com",
    "icbc.com.cn", "ccb.com", "boc.cn", "abchina.com", "bankcomm.com", "cmbchina.com",
    "spdb.com.cn", "cib.com.cn", "cebbank.com", "psbc.com", "citicbank.com", "pingan.com",
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com", "hsbc.com", "wise.com",
    "revolut.com", "coinbase.com", "binance.com", "okx.com",
    # Cloud consoles and code hosting
    "amazon.com", "azure.com", "aliyun.com", "tencent.com", "huaweicloud.com",
    "volcengine.com", "digitalocean.com", "cloudflare.com", "vercel.com", "github.com",
    "gitlab.com",
    # Password managers
    "1password.com", "bitwarden.com", "lastpass.com", "dashlane.com",
})
_SENSITIVE_SUFFIXES = (".gov", ".gov.cn", ".mil", ".bank")


def site_of(host: str) -> str:
    host = host.strip().strip(".").lower()
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) > 2 and len(labels[-1]) == 2 and labels[-2] in _GENERIC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_sensitive(site: str) -> bool:
    return site in SENSITIVE_SITES or site.endswith(_SENSITIVE_SUFFIXES)
