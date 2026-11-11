"""Idempotent run migration with encrypted, recoverable pre-images."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from pathlib import Path

from deepseek_tui.automation.delivery import sanitized_delivery_snapshot
from deepseek_tui.state.secrets import load_delivery_secret, store_delivery_secret
from deepseek_tui.utils import write_json_atomic

logger = logging.getLogger(__name__)


def protect_delivery(raw):
    if not isinstance(raw, dict):
        return raw
    result = dict(raw)
    if str(result.get("mode", "")).strip().lower() in {"wecom", "wecom_webhook", "wework"}:
        key = result.get("to") or result.get("chat_id")
        if key:
            result["credential_ref"] = store_delivery_secret(str(key))
            result["to"] = result["chat_id"] = None
    return result


def protect_run_record(raw: dict) -> dict:
    result = deepcopy(raw)
    if "delivery" in result:
        result["delivery"] = protect_delivery(result["delivery"])
    snapshot = result.get("delivery_snapshot")
    if isinstance(snapshot, dict):
        cleaned = sanitized_delivery_snapshot(snapshot)
        cleaned["config"] = protect_delivery(snapshot.get("config"))
        result["delivery_snapshot"] = cleaned
    for field in ("error", "delivery_error"):
        if isinstance(result.get(field), str):
            result[field] = re.sub(r"([?&]key=)[^\s&'\"]+", r"\1[redacted]", result[field])
    return result


def migrate_run_credentials(root: Path) -> int:
    marker = root / "state" / "credential-migration-v1.json"
    if marker.exists():
        return 0
    from cryptography.fernet import Fernet

    backup_dir = root / "state" / "credential-backups"
    migrated = 0
    skipped: list[str] = []
    for path in (root / "runs").glob("*/*.json"):
        original = path.read_bytes()
        try:
            raw = json.loads(original)
        except ValueError:
            skipped.append(str(path.relative_to(root)))
            continue
        if not isinstance(raw, dict):
            skipped.append(str(path.relative_to(root)))
            continue
        cleaned = protect_run_record(raw)
        if cleaned == raw:
            continue
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup = backup_dir / (
            hashlib.sha256(str(path.relative_to(root)).encode() + original).hexdigest() + ".json"
        )
        if not backup.exists():
            key = Fernet.generate_key()
            reference = store_delivery_secret(key.decode())
            # The credential is committed before the encrypted backup and atomic rewrite.
            if load_delivery_secret(reference) != key.decode():
                raise RuntimeError("Backup key could not be verified")
            write_json_atomic(
                backup,
                {
                    "path": str(path.relative_to(root)),
                    "key_ref": reference,
                    "ciphertext": Fernet(key).encrypt(original).decode(),
                },
            )
        write_json_atomic(path, cleaned)
        migrated += 1
    write_json_atomic(marker, {"version": 1, "migrated": migrated, "skipped": skipped})
    logger.info("automation_credential_migration migrated=%d skipped=%d", migrated, len(skipped))
    return migrated
