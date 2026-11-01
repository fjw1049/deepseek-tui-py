"""Open a page a task built, in a real browser, and report what a person would hit first.

Runs as its own process: the grader is synchronous and a browser must not outlive a check.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from deepseek_tui.browser.service import BrowserAction, BrowserActionError, BrowserService

THREAD = "page-probe"


async def _act(service: BrowserService, root: Path, **arguments: Any) -> dict[str, Any]:
    action = BrowserAction.model_validate(arguments, context={"local_root": root})
    try:
        return await service.action(THREAD, action, require_observation=True)
    except BrowserActionError as exc:
        return exc.response


async def probe(page: Path, root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="deepseek-eval-page-") as scratch:
        service = BrowserService(Path(scratch) / "artifacts", profile_root=Path(scratch) / "private")
        service.configure(THREAD, persistent=False)
        try:
            # Console capture starts on request, so it must be on before the page loads.
            await _act(service, root, action="open", url="about:blank")
            await _act(service, root, action="console")
            await _act(service, root, action="open", url=page.resolve().as_uri())
            observed = await _act(service, root, action="observe")
            console = await _act(service, root, action="console")
        finally:
            await service.close(THREAD)
    entries = (console.get("content") or {}).get("entries") or []
    return {
        "controls": (observed.get("observation") or {}).get("total_elements", 0),
        "errors": [entry for entry in entries if entry.get("level") == "error"],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe(Path(sys.argv[1]), Path(sys.argv[2]))), ensure_ascii=False))
