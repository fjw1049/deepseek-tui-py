"""Offline state/media audit; all writes and fake credentials stay in a temporary home."""

import io
import json
import os
import tempfile
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from deepseek_tui.state.context import ContextConfig, UserTurnInput, process_turn_input
from deepseek_tui.state.paste_file import write_paste_txt
from deepseek_tui.state.secrets import write_api_key
from deepseek_tui.state.session import checkpoint_path, save_checkpoint
from deepseek_tui.tui.session_restore import try_restore_crash_checkpoint
from deepseek_tui.protocol.messages import Message, MessageRequest


def main():
    result = {}
    with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, {"DEEPSEEK_HOME": raw}):
        root = Path(raw)
        save_checkpoint({"schema_version": 999})
        result["caller_can_override_checkpoint_version"] = json.loads(
            checkpoint_path().read_text()
        )["schema_version"]
        checkpoint_path().write_text("[]")
        try:
            try_restore_crash_checkpoint(SimpleNamespace())
        except Exception as exc:
            result["malformed_checkpoint_restore_exception"] = type(exc).__name__
        save_checkpoint(
            {
                "metadata": {"workspace": str(root / "workspace-a")},
                "messages": [Message.user("workspace-a task").model_dump()],
            }
        )
        engine = SimpleNamespace(
            session_messages=[],
            tool_context=SimpleNamespace(working_directory=root / "workspace-b"),
        )
        result["other_workspace_restored"] = try_restore_crash_checkpoint(engine) is not None
        folder = root / "directory"
        folder.mkdir()
        for i in range(3):
            (folder / (str(i) + "long-name" * 8)).touch()
        expanded = process_turn_input(
            UserTurnInput("@directory"),
            workspace=root,
            cwd=root,
            config=ContextConfig(max_total_inline_bytes=20),
        )
        result["directory_inline_bytes_with_20_budget"] = sum(
            ref.bytes_inlined for ref in expanded.references
        )
        config = root / "fake-config.toml"
        config.write_text('provider = "deepseek"\n[providers . deepseek]\napi_key = "fake-old"\n')
        tomllib.loads(config.read_text())
        write_api_key("deepseek", "fake-new", path=config)
        try:
            tomllib.loads(config.read_text())
            result["valid_spaced_toml_header_after_write"] = True
        except tomllib.TOMLDecodeError:
            result["valid_spaced_toml_header_after_write"] = False
        barrier = threading.Barrier(2)
        original_exists = Path.exists

        class Clock:
            @classmethod
            def now(cls):
                return datetime(2026, 9, 27, 12, 0, 0)

        def exists(path):
            value = original_exists(path)
            if path.name == "paste-20260927-120000.txt":
                barrier.wait(timeout=3)
            return value

        with (
            patch("deepseek_tui.state.paste_file.datetime", Clock),
            patch.object(Path, "exists", exists),
            ThreadPoolExecutor(2) as pool,
        ):
            paths = list(
                pool.map(lambda text: write_paste_txt(text, root), ["first paste", "second paste"])
            )
        result["concurrent_paste_distinct_paths"] = len(set(paths))
        from deepseek_tui import media
        from deepseek_tui.client.media import budget_media_request
        from deepseek_tui.client.chat_messages import build_chat_messages

        output = io.BytesIO()
        Image.new("RGB", (32, 32), "red").save(output, format="PNG")
        (root / "image.png").write_bytes(output.getvalue())
        with patch(
            "deepseek_tui.media.import_image_path",
            side_effect=FileNotFoundError("deleted after classification"),
        ):
            try:
                process_turn_input(UserTurnInput("@image.png"), workspace=root, cwd=root)
            except Exception as exc:
                result["image_disappears_during_expansion"] = type(exc).__name__
        block = media.import_image(output.getvalue())
        request = MessageRequest(
            model="deepseek-chat", messages=[Message.user("image", images=[block])]
        )
        original = media.image_data_url
        with (
            patch("deepseek_tui.client.media.image_data_url", wraps=original) as budgeting,
            patch("deepseek_tui.media.image_data_url", wraps=original) as serialization,
        ):
            budget_media_request(request, None)
            build_chat_messages(request.messages, model=request.model)
            result["image_encodes_per_budget_and_serialize"] = (
                budgeting.call_count + serialization.call_count
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
