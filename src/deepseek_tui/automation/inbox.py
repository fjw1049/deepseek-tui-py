"""Inbox prefetch (IMAP email, Feishu JSONL store) and Feishu outbound send."""

from __future__ import annotations



import asyncio
import email
import imaplib
import json
import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.header import decode_header
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from deepseek_tui.automation.delivery import DigestConfig
from deepseek_tui.config.paths import user_deepseek_dir

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 240
_FEISHU_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0}


@dataclass(frozen=True, slots=True)
class InboxMessage:
    source: str
    sender: str
    subject: str
    snippet: str
    received_at: str
    chat: str | None = None


def automation_data_dir() -> Path:
    return user_deepseek_dir() / "automation"


def feishu_inbox_path() -> Path:
    return automation_data_dir() / "feishu_inbox.jsonl"


def email_config_path() -> Path:
    return automation_data_dir() / "email.toml"


def feishu_config_path() -> Path:
    """Prefer ``<cwd>/.deepseek/automation/feishu.toml`` when present (repo-local dev)."""
    project_cfg = Path.cwd() / ".deepseek" / "automation" / "feishu.toml"
    if project_cfg.is_file():
        return project_cfg
    return automation_data_dir() / "feishu.toml"


def _local_tz() -> ZoneInfo:
    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")  # type: ignore[arg-type]


def _window_bounds(kind: str) -> tuple[datetime, datetime]:
    """``yesterday_local`` / ``today_local`` in local calendar."""
    tz = _local_tz()
    today = datetime.now(tz).date()
    if kind == "yesterday_local":
        start_day = today - timedelta(days=1)
        end_day = today
    else:
        start_day = today
        end_day = today + timedelta(days=1)
    start = datetime.combine(start_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(end_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end


def _parse_source(source: str) -> tuple[str, str] | None:
    parts = source.strip().lower().split(":", 1)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return raw if isinstance(raw, dict) else {}


def _email_from_app_config() -> dict[str, Any]:
    """Merge ``[automation.email]`` from discovered config.toml (if any)."""
    try:
        from deepseek_tui.config.loader import ConfigLoader

        cfg = ConfigLoader().load()
        dumped = cfg.automation.email.model_dump(mode="python")
        return {k: v for k, v in dumped.items() if v is not None and v != ""}
    except Exception as exc:
        logger.debug("[automation][email] config.toml section unavailable: %s", exc)
        return {}


def _email_account_section(account: str | None) -> dict[str, Any]:
    key = (account or "default").strip() or "default"
    merged: dict[str, Any] = dict(_email_from_app_config())
    raw = _load_toml(email_config_path())
    section = raw.get(key)
    if isinstance(section, dict):
        merged.update(section)
    elif key != "default" and isinstance(raw.get("default"), dict):
        merged.update(raw["default"])
    return merged


def default_mail_to_from_config() -> str | None:
    """``[automation].mail_to`` or ``[automation.email].to_addr``."""
    try:
        from deepseek_tui.config.loader import ConfigLoader

        cfg = ConfigLoader().load()
        if cfg.automation.mail_to and str(cfg.automation.mail_to).strip():
            return str(cfg.automation.mail_to).strip()
        to_addr = cfg.automation.email.to_addr
        if to_addr and str(to_addr).strip():
            return str(to_addr).strip()
    except Exception:
        pass
    return os.getenv("MAIL_TO", "").strip() or None


def _resolve_password(section: dict[str, Any], account: str | None) -> str | None:
    env_key = section.get("password_env")
    if isinstance(env_key, str) and env_key.strip():
        value = os.getenv(env_key.strip())
        if value:
            return value
    acct = (account or "default").upper().replace("-", "_")
    for candidate in (
        os.getenv("DEEPSEEK_EMAIL_PASSWORD"),
        os.getenv(f"DEEPSEEK_EMAIL_PASSWORD_{acct}"),
    ):
        if candidate:
            return candidate
    pwd = section.get("password")
    return str(pwd) if isinstance(pwd, str) and pwd else None


def _decode_mime_header(value: str) -> str:
    chunks: list[str] = []
    for part, enc in decode_header(value):
        if isinstance(part, bytes):
            chunks.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            chunks.append(str(part))
    return "".join(chunks).strip()


def _message_snippet(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    return re.sub(r"\s+", " ", text).strip()[:_SNIPPET_MAX]
        return ""
    payload = msg.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return re.sub(r"\s+", " ", text).strip()[:_SNIPPET_MAX]


def _imap_fetch_sync(
    section: dict[str, Any],
    account: str | None,
    start_utc: datetime,
    end_utc: datetime,
) -> list[InboxMessage]:
    host = str(section.get("imap_host", "")).strip()
    user = str(section.get("username", "")).strip()
    password = _resolve_password(section, account)
    if not host or not user or not password:
        raise ValueError(
            "email account incomplete: set imap_host, username, and password "
            "(or password_env / DEEPSEEK_EMAIL_PASSWORD*) in "
            f"{email_config_path()}"
        )
    port = int(section.get("imap_port", 993))
    use_ssl = bool(section.get("ssl", True))
    mailbox = str(section.get("mailbox", "INBOX")).strip() or "INBOX"

    if use_ssl:
        client = imaplib.IMAP4_SSL(host, port)
    else:
        client = imaplib.IMAP4(host, port)
    try:
        client.login(user, password)
        client.select(mailbox)
        since = start_utc.strftime("%d-%b-%Y")
        before = end_utc.strftime("%d-%b-%Y")
        status, data = client.search(None, f'(SINCE "{since}" BEFORE "{before}")')
        if status != "OK" or not data or not data[0]:
            return []
        out: list[InboxMessage] = []
        for num in data[0].split():
            st, fetched = client.fetch(num, "(RFC822)")
            if st != "OK" or not fetched:
                continue
            raw = fetched[0][1]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)
            from_hdr = _decode_mime_header(msg.get("From", "unknown"))
            subject = _decode_mime_header(msg.get("Subject", "(no subject)"))
            date_hdr = msg.get("Date", "")
            try:
                received = email.utils.parsedate_to_datetime(date_hdr).astimezone(
                    timezone.utc
                )
            except (TypeError, ValueError):
                received = datetime.now(timezone.utc)
            if received < start_utc or received >= end_utc:
                continue
            out.append(
                InboxMessage(
                    source="email",
                    sender=from_hdr,
                    subject=subject,
                    snippet=_message_snippet(msg) or "(no body snippet)",
                    received_at=received.isoformat(),
                )
            )
        out.sort(key=lambda m: m.received_at)
        return out
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


async def fetch_email_messages(
    window_kind: str,
    account: str | None = None,
) -> list[InboxMessage]:
    start, end = _window_bounds(window_kind)
    section = _email_account_section(account)
    return await asyncio.to_thread(_imap_fetch_sync, section, account, start, end)


def append_feishu_inbound(
    *,
    text: str,
    sender_id: str,
    sender_name: str = "",
    chat_id: str = "",
    received_at: datetime | None = None,
) -> None:
    path = feishu_inbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (received_at or datetime.now(timezone.utc)).isoformat()
    row = {
        "received_at": stamp,
        "sender_id": sender_id,
        "sender_name": sender_name or sender_id,
        "chat_id": chat_id,
        "text": text[:4000],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_feishu_rows() -> list[dict[str, Any]]:
    path = feishu_inbox_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def list_feishu_messages(window_kind: str) -> list[InboxMessage]:
    start, end = _window_bounds(window_kind)
    out: list[InboxMessage] = []
    for row in _load_feishu_rows():
        raw_at = row.get("received_at")
        try:
            received = datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if received < start or received >= end:
            continue
        sender = str(row.get("sender_name") or row.get("sender_id") or "unknown")
        chat = str(row.get("chat_id") or "")
        text = str(row.get("text") or "")
        out.append(
            InboxMessage(
                source="feishu",
                sender=sender,
                subject="",
                snippet=text[:_SNIPPET_MAX],
                received_at=received.astimezone(timezone.utc).isoformat(),
                chat=chat or None,
            )
        )
    out.sort(key=lambda m: m.received_at)
    return out


def _format_email_block(window_kind: str, messages: list[InboxMessage]) -> str:
    label = "yesterday" if window_kind == "yesterday_local" else "today"
    lines = [f"<email_inbox_{label} window=\"{window_kind}\">"]
    if not messages:
        lines.append(f"- (none) No email in local {label} window.")
    for msg in messages:
        lines.append(
            f'- [{msg.received_at}] from="{msg.sender}" subject="{msg.subject}" '
            f'snippet="{msg.snippet}"'
        )
    lines.append(f"</email_inbox_{label}>")
    return "\n".join(lines)


def _format_feishu_block(window_kind: str, messages: list[InboxMessage]) -> str:
    label = "yesterday" if window_kind == "yesterday_local" else "today"
    lines = [f"<feishu_inbox_{label} window=\"{window_kind}\">"]
    if not messages:
        lines.append(f"- (none) No Feishu messages recorded in local {label} window.")
    for msg in messages:
        chat = msg.chat or "unknown"
        lines.append(
            f'- [{msg.received_at}] sender="{msg.sender}" chat="{chat}": {msg.snippet}'
        )
    lines.append(f"</feishu_inbox_{label}>")
    return "\n".join(lines)


async def build_digest_block(digest: DigestConfig | None) -> str:
    if digest is None or not digest.sources:
        return ""

    sections: list[str] = ["<automation_digest>"]
    for source in digest.sources:
        parsed = _parse_source(source)
        if parsed is None:
            sections.append(f"<!-- unknown digest source: {source} -->")
            continue
        channel, window = parsed
        try:
            if channel == "email":
                msgs = await fetch_email_messages(window, digest.account)
                sections.append(_format_email_block(window, msgs))
            elif channel == "feishu":
                msgs = list_feishu_messages(window)
                sections.append(_format_feishu_block(window, msgs))
            else:
                sections.append(f"<!-- unsupported digest channel: {channel} -->")
        except Exception as exc:
            logger.warning("[automation][digest] source=%s failed: %s", source, exc)
            sections.append(f"<!-- digest:{source} error: {exc} -->")
    sections.append("</automation_digest>")
    return "\n".join(sections) + "\n\n"


def _feishu_api_base(domain: str) -> str:
    key = domain.strip().lower()
    if key in ("lark", "lark_suite", "international"):
        return "https://open.larksuite.com"
    return "https://open.feishu.cn"


def _feishu_from_app_config() -> dict[str, Any]:
    """Merge ``[automation.feishu]`` from discovered config.toml (if any)."""
    try:
        from deepseek_tui.config.loader import ConfigLoader

        cfg = ConfigLoader().load()
        dumped = cfg.automation.feishu.model_dump(mode="python")
        return {k: v for k, v in dumped.items() if v is not None and v != ""}
    except Exception as exc:
        logger.debug("[automation][feishu] config.toml section unavailable: %s", exc)
        return {}


def default_feishu_chat_id_from_config() -> str | None:
    """``[automation].feishu_chat_id`` or ``[automation.feishu].chat_id``."""
    try:
        from deepseek_tui.config.loader import ConfigLoader

        cfg = ConfigLoader().load()
        if cfg.automation.feishu_chat_id and str(cfg.automation.feishu_chat_id).strip():
            return str(cfg.automation.feishu_chat_id).strip()
        chat_id = cfg.automation.feishu.chat_id
        if chat_id and str(chat_id).strip():
            return str(chat_id).strip()
    except Exception:
        pass
    return None


def _load_feishu_app_credentials() -> tuple[str, str, str]:
    app_id = os.getenv("DEEPSEEK_FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("DEEPSEEK_FEISHU_APP_SECRET", "").strip()
    domain = os.getenv("DEEPSEEK_FEISHU_DOMAIN", "feishu").strip()
    if app_id and app_secret:
        return app_id, app_secret, domain
    merged = dict(_feishu_from_app_config())
    legacy = _load_toml(feishu_config_path())
    if legacy:
        for key in ("app_id", "app_secret", "domain"):
            if key not in merged and legacy.get(key):
                merged[key] = legacy[key]
    app_id = str(merged.get("app_id", "")).strip()
    app_secret = str(merged.get("app_secret", "")).strip()
    domain = str(merged.get("domain", "feishu")).strip() or "feishu"
    if app_id and app_secret:
        return app_id, app_secret, domain
    raise ValueError(
        "Feishu credentials missing: set DEEPSEEK_FEISHU_APP_ID/SECRET, "
        "[automation.feishu] in config.toml, or "
        f"{feishu_config_path()}"
    )


async def _feishu_tenant_token(client: httpx.AsyncClient, base: str, app_id: str, app_secret: str) -> str:
    import time

    now = time.time()
    if (
        _FEISHU_TOKEN_CACHE.get("base") == base
        and _FEISHU_TOKEN_CACHE.get("token")
        and float(_FEISHU_TOKEN_CACHE.get("expires_at", 0)) > now + 30
    ):
        return str(_FEISHU_TOKEN_CACHE["token"])

    resp = await client.post(
        f"{base}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if int(data.get("code", -1)) != 0:
        raise RuntimeError(f"Feishu token error: {data.get('msg', data)}")
    token = str(data["tenant_access_token"])
    expire = now + int(data.get("expire", 7200)) - 60
    _FEISHU_TOKEN_CACHE.update({"base": base, "token": token, "expires_at": expire})
    return token


def feishu_receive_id_type(receive_id: str) -> str:
    """Infer Feishu ``receive_id_type`` from id prefix (``oc_`` → chat, ``ou_`` → open_id)."""
    rid = receive_id.strip()
    if rid.startswith("oc_"):
        return "chat_id"
    if rid.startswith("ou_"):
        return "open_id"
    if rid.startswith("on_"):
        return "union_id"
    return "open_id"


async def feishu_send_text(
    *,
    receive_id: str,
    text: str,
    receive_id_type: str | None = None,
) -> None:
    app_id, app_secret, domain = _load_feishu_app_credentials()
    rid_type = receive_id_type or feishu_receive_id_type(receive_id)
    base = _feishu_api_base(domain)
    body_text = text if len(text) <= 4000 else text[:3997] + "..."
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": body_text}, ensure_ascii=False),
    }
    async with httpx.AsyncClient() as client:
        token = await _feishu_tenant_token(client, base, app_id, app_secret)
        resp = await client.post(
            f"{base}/open-apis/im/v1/messages",
            params={"receive_id_type": rid_type},
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if int(data.get("code", -1)) != 0:
            raise RuntimeError(f"Feishu send error: {data.get('msg', data)}")
    logger.info(
        "[automation][delivery][feishu] sent receive_id=%s len=%d",
        receive_id,
        len(body_text),
    )


def _smtp_send_sync(
    section: dict[str, Any],
    account: str | None,
    *,
    to_addr: str,
    subject: str,
    body: str,
) -> None:
    host = str(section.get("smtp_host", "")).strip()
    user = str(section.get("username", "")).strip()
    password = _resolve_password(section, account)
    from_addr = str(section.get("from_addr") or user).strip()
    if not host or not user or not password or not from_addr:
        raise ValueError(
            "SMTP incomplete: set smtp_host, username, from_addr, and password "
            f"in {email_config_path()}"
        )
    port = int(section.get("smtp_port", 587))
    use_ssl = bool(section.get("smtp_ssl", False))
    starttls = bool(section.get("smtp_starttls", not use_ssl))

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if use_ssl:
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port)
    else:
        client = smtplib.SMTP(host, port)
    try:
        if starttls and not use_ssl:
            client.starttls()
        client.login(user, password)
        client.sendmail(from_addr, [to_addr], msg.as_string())
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001
            pass


async def email_send_text(
    *,
    to_addr: str,
    subject: str,
    body: str,
    account: str | None = None,
) -> None:
    """Send plain-text mail using ``~/.deepseek/automation/email.toml`` SMTP section."""
    section = _email_account_section(account)
    await asyncio.to_thread(
        _smtp_send_sync,
        section,
        account,
        to_addr=to_addr,
        subject=subject,
        body=body,
    )
    logger.info(
        "[automation][delivery][email] sent to=%s subject=%s len=%d",
        to_addr,
        subject,
        len(body),
    )
