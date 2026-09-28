"""Offline audit 13 characterizations; only generated temporary fixtures."""

import asyncio
import json
import os
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from deepseek_tui.server import data_bundle as bundle
from deepseek_tui.server.metrics import TurnDeltaBatcher
from deepseek_tui.server.routes import stream_thread_events
from deepseek_tui.server.threads.broadcast import AsyncBroadcast
from deepseek_tui.server.threads.models import ThreadRecord
from deepseek_tui.server.threads.store import RuntimeThreadStore
from deepseek_tui.server.workbench_usage_ledger import _ledger_file_lock, _lock_path


def thread(id):
    now = datetime.now(timezone.utc)
    return ThreadRecord(
        id=id, created_at=now, updated_at=now, model="fixture", workspace="/fixture"
    )


async def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix="server-audit-") as directory:
        root = Path(directory)
        store = RuntimeThreadStore(root / "store")
        first = await store.append_event("thread", None, None, "item.created", {})
        reopened = RuntimeThreadStore(root / "store")
        second = await reopened.append_event("thread", None, None, "item.created", {})
        results["restart_sequence"] = {
            "first": first.seq,
            "after_reopen": second.seq,
            "visible_since_first": len(reopened.events_since("thread", first.seq)),
        }
        event = await reopened.append_event(
            "thread", None, None, "item.delta", {"delta": "x" * 3000}
        )
        results["live_delta_payload_keys"] = list(event.payload)
        store.save_thread(thread("../escaped"))
        results["store_id_escape"] = (root / "store" / "escaped.json").exists()
        bus = AsyncBroadcast(capacity=2)
        seed = first.model_copy(update={"seq": 10})
        manager = SimpleNamespace(
            event_bus=bus, subscribe_events=bus.subscribe, events_since=lambda *args: [seed]
        )
        stream = stream_thread_events(manager, "thread")
        await anext(stream)
        bus.send(first.model_copy(update={"seq": 11, "payload": {"marker": "lost"}}))
        for seq in [12, 13]:
            bus.send(first.model_copy(update={"seq": seq, "thread_id": "other"}))
        bus.send(first.model_copy(update={"seq": 14}))
        frame = await asyncio.wait_for(anext(stream), 1)
        results["sse_overflow"] = {
            "lost_own_event": "lost" not in frame,
            "next_frame": frame.strip(),
            "explicit_gap_notice": "gap" in frame or "resync" in frame,
        }
        await stream.aclose()
        results["subscriber_cleanup"] = bus.receiver_count
        attempts = []

        async def fail_emit(*args):
            attempts.append(args[-1])
            raise OSError("fixture write failure")

        batcher = TurnDeltaBatcher("thread", "turn", fail_emit)
        await batcher.append("item", "item.delta", "important")
        try:
            await batcher.flush()
        except OSError:
            pass
        results["failed_delta_flush"] = {
            "attempts": len(attempts),
            "retry_emitted": await batcher.flush(),
        }
        target = root / "target"
        existing = RuntimeThreadStore(target)
        existing.save_thread(thread("keep"))
        archive = root / "missing-records.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": bundle.BUNDLE_FORMAT,
                        "version": bundle.BUNDLE_VERSION,
                        "includes": {"threads": True},
                    }
                ),
            )
        report = bundle.import_bundle(
            archive,
            mode="replace",
            threads_dir=target,
            sessions_dir=root / "sessions",
            import_settings=False,
        )
        results["incomplete_replace_bundle"] = {
            "old_thread_deleted": not (target / "threads/keep.json").exists(),
            "reported_success": report,
        }
        export_root = root / "export-source"
        export_root.mkdir()
        outside = root / "outside"
        outside.write_text("fixture external bytes")
        (export_root / "link").symlink_to(outside)
        leak_zip = root / "export.zip"
        with zipfile.ZipFile(leak_zip, "w") as zf:
            bundle._zip_tree(zf, export_root, arc_prefix="threads")
        with zipfile.ZipFile(leak_zip) as zf:
            results["export_follows_symlink"] = zf.read("threads/link") == b"fixture external bytes"
        ledger_path = root / "usage.json"
        with _ledger_file_lock(ledger_path, timeout=0.2):
            old_time = time.time() - 60
            os.utime(_lock_path(ledger_path), (old_time, old_time))
            with _ledger_file_lock(ledger_path, timeout=0.2):
                results["live_usage_lock_stolen"] = True
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
