"""Standalone share storage: uvicorn deepseek_tui.server.share_service:create_app --factory.

Deploy separately from the local runtime. Upload/deletion require an operator key;
reads require an unguessable capability. No tools or model calls run here.
"""

from __future__ import annotations

import hmac
import html
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from deepseek_tui.server.session_snapshot import (
    MAX_SNAPSHOT_BYTES,
    SessionSnapshot,
    validate_snapshot,
)
from deepseek_tui.utils import write_json_atomic


async def bounded_body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(413, "Snapshot exceeds 32 MiB")
    return bytes(data)


def create_app(*, storage: Path | None = None, upload_key: str | None = None) -> FastAPI:
    root = storage or Path(os.environ.get("DEEPSEEK_SHARE_DIR", "./share-data"))
    key = upload_key or os.environ.get("DEEPSEEK_SHARE_UPLOAD_KEY", "")
    if len(key) < 24:
        raise ValueError("DEEPSEEK_SHARE_UPLOAD_KEY must contain at least 24 characters")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    app = FastAPI(title="DeepSeek Session Shares", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def private_response(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def authorize(request: Request) -> None:
        if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {key}"):
            raise HTTPException(401, "Upload key required")

    def share_path(token: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise HTTPException(404, "Share not found")
        return root / f"{token}.json"

    @app.post("/v1/shares", status_code=201)
    async def create(request: Request):
        authorize(request)
        try:
            payload = json.loads(await bounded_body(request))
            if not isinstance(payload, dict):
                raise ValueError("Expected a snapshot object")
            days = int(payload.get("expires_in_days", 7))
            if not 1 <= days <= 30:
                raise ValueError("Expiry must be between 1 and 30 days")
            snapshot = SessionSnapshot.model_validate(payload["snapshot"])
            validate_snapshot(snapshot)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, "Invalid session snapshot") from exc
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        write_json_atomic(
            share_path(token),
            {
                "expires_at": expires.isoformat(),
                "snapshot": snapshot.model_dump(mode="json"),
            },
        )
        return {"token": token, "expires_at": expires.isoformat()}

    @app.get("/v1/shares/{token}")
    async def get(token: str):
        path = share_path(token)
        if not path.is_file():
            raise HTTPException(404, "Share not found or revoked")
        payload = json.loads(path.read_text())
        if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(timezone.utc):
            path.unlink(missing_ok=True)
            raise HTTPException(410, "Share expired")
        return payload

    @app.delete("/v1/shares/{token}", status_code=204)
    async def delete(token: str, request: Request):
        authorize(request)
        share_path(token).unlink(missing_ok=True)
        return Response(status_code=204)

    @app.get("/s/{token}", response_class=HTMLResponse)
    async def landing(token: str, request: Request):
        try:
            payload = await get(token)
        except HTTPException as exc:
            return HTMLResponse(
                '<!doctype html><meta charset="utf-8"><title>分享已失效</title>'
                "<h1>这个分享已失效</h1><p>请联系分享者获取新的链接。</p>",
                status_code=exc.status_code,
            )
        snapshot = payload["snapshot"]
        title = html.escape(snapshot["title"])
        url = str(request.url.replace(query="", fragment=""))
        app_link = html.escape("deepseek-gui://share?url=" + quote(url, safe=""), quote=True)
        messages = []
        for item in snapshot["items"]:
            if item["kind"] not in {"user_message", "agent_message"}:
                continue
            role = "你" if item["kind"] == "user_message" else "AI"
            text = html.escape(item.get("detail") or item["summary"])
            messages.append(f'<article><b>{role}</b><div class="message">{text}</div></article>')
        images = "".join(
            f'<img alt="对话图片" src="data:image/png;base64,{html.escape(data, quote=True)}">'
            for data in snapshot.get("media", {}).values()
        )
        return HTMLResponse(
            '<!doctype html><html lang="zh"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title><style>"
            "body{font:16px/1.7 system-ui;max-width:760px;margin:48px auto;padding:0 24px;"
            "color:#202124;background:#fafafa}h1{line-height:1.3}.hint{color:#666;font-size:14px}"
            "a{display:inline-block;background:#2463eb;color:white;padding:10px 18px;"
            "border-radius:10px;text-decoration:none}"
            "article{background:white;border:1px solid #eee;"
            "border-radius:14px;padding:20px;margin:18px 0}.message{white-space:pre-wrap;"
            "overflow-wrap:anywhere}img{max-width:100%;border-radius:12px;margin:12px 0}"
            "</style><body>"
            f'<h1>{title}</h1><p class="hint">这是分享时的对话副本，后续消息不会更新到这里。</p>'
            f'<a href="{app_link}">在应用中继续</a>'
            '<p class="hint">已安装 DeepSeek Workbench？点击上方按钮即可。'
            "如果没有自动打开，也可复制本页链接，在应用中选择「分享 → 打开分享」。</p>"
            + "".join(messages)
            + images
            + "</body></html>",
            headers={
                "Content-Security-Policy": "default-src 'none'; img-src data:; "
                "style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
            },
        )

    return app
