"""Verify the per-request access log never reflects query-string secrets.

SSE clients pass ``?token=<bearer>`` so a regression that logged the full URL
(rather than ``request.url.path``) would leak the runtime token to log
aggregators. This test asserts both the current behaviour and the
defense-in-depth ``split('?')`` strip in ``server._access_log``.
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_access_log_strips_query(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="deepseek_tui.app_server.server")
    r = await client.get("/health?token=should-not-leak")
    assert r.status_code == 200

    logged_paths = [
        rec.getMessage()
        for rec in caplog.records
        if "http_access" in rec.getMessage()
    ]
    assert logged_paths, "expected at least one http_access log entry"
    for line in logged_paths:
        assert "should-not-leak" not in line, line
        assert "?" not in line, line
