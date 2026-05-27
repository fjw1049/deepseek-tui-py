"""Expand ``@path`` mentions and attached-media lines into model context.

Mirrors Rust ``tui/file_mention.rs``: parse mentions, resolve against the
workspace, classify by kind, inline small text files, and append a
``Local context from @mentions`` block to the model payload while keeping
the user's raw prompt for UI display.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from deepseek_tui.context.types import (
    ContextConfig,
    ContextReference,
    ProcessedTurnInput,
    UserTurnInput,
)

_EXPANSION_MARKER = "---"
_MEDIA_EXTENSIONS = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "tif",
        "tiff",
        "ppm",
        "heic",
        "mp4",
        "mov",
        "m4v",
        "webm",
        "avi",
        "mkv",
    }
)


def process_turn_input(
    inp: UserTurnInput,
    *,
    workspace: Path,
    cwd: Path | None = None,
    session_id: str | None = None,
    config: ContextConfig | None = None,
) -> ProcessedTurnInput:
    """Parse ``@mentions``, expand file context, return display vs model text."""
    cfg = config or ContextConfig()
    raw = inp.raw_text or ""
    display_text = raw

    if _already_expanded(raw, cfg):
        return ProcessedTurnInput(
            display_text=display_text,
            model_text=raw,
            references=[],
            warnings=[],
        )

    ws = workspace.expanduser().resolve()
    proc_cwd = (cwd or Path.cwd()).expanduser().resolve()

    tokens = _collect_tokens(raw)
    if not tokens:
        return ProcessedTurnInput(
            display_text=display_text,
            model_text=raw,
            references=[],
            warnings=[],
        )

    blocks: list[str] = []
    references: list[ContextReference] = []
    warnings: list[str] = []
    total_inlined = 0

    for idx, (token, source) in enumerate(tokens):
        if idx >= cfg.max_mentions:
            warnings.append(
                f"Only the first {cfg.max_mentions} file mentions are expanded; "
                f"remaining @ references are left for read_file."
            )
            break

        resolved = _resolve_mention(token, ws, proc_cwd)
        if resolved is None:
            ref = ContextReference(
                kind="missing",
                source="at_mention",
                label=token,
                target=token,
                included=False,
                expanded=False,
                detail="outside workspace or invalid path",
            )
            references.append(ref)
            blocks.append(
                _render_missing_block(token, token, "path outside workspace or invalid")
            )
            continue

        path, display_path = resolved
        kind = _classify_path(path)

        if kind == "missing":
            ref = ContextReference(
                kind="missing",
                source=source,
                label=token,
                target=display_path,
                included=False,
                expanded=False,
                detail="not found",
            )
            references.append(ref)
            blocks.append(_render_missing_block(token, display_path, "not found"))
            continue

        if kind == "directory":
            body = _list_directory(path, cfg.max_directory_entries)
            ref = ContextReference(
                kind="directory",
                source=source,
                label=token,
                target=str(path),
                included=True,
                expanded=True,
                detail="directory listing",
                bytes_inlined=len(body.encode("utf-8")),
            )
            references.append(ref)
            total_inlined += ref.bytes_inlined
            blocks.append(_render_directory_block(token, display_path, body))
            continue

        if kind == "media":
            ref = ContextReference(
                kind="media",
                source=source,
                label=token,
                target=str(path),
                included=False,
                expanded=False,
                detail="use /attach for media bytes",
            )
            references.append(ref)
            blocks.append(_render_media_hint_block(token, display_path))
            continue

        if kind == "binary":
            ref = ContextReference(
                kind="binary",
                source=source,
                label=token,
                target=str(path),
                included=False,
                expanded=False,
                detail="binary or unreadable",
            )
            references.append(ref)
            blocks.append(_render_unreadable_block(token, display_path, "binary file"))
            continue

        # text file
        size = path.stat().st_size
        mode = _text_inclusion_mode(size, cfg, total_inlined)

        if mode == "reference":
            artifact = _spill_artifact(ws, session_id, path.name, path)
            ref = ContextReference(
                kind="file",
                source=source,
                label=token,
                target=str(path),
                included=True,
                expanded=False,
                detail="reference only",
                artifact_path=str(artifact) if artifact else None,
            )
            references.append(ref)
            blocks.append(
                _render_reference_block(token, display_path, str(path), artifact, size)
            )
            continue

        try:
            content, truncated = _read_text_budget(path, cfg.max_inline_bytes)
        except OSError as exc:
            ref = ContextReference(
                kind="binary",
                source=source,
                label=token,
                target=str(path),
                included=False,
                expanded=False,
                detail=str(exc),
            )
            references.append(ref)
            blocks.append(_render_unreadable_block(token, display_path, str(exc)))
            continue

        if truncated and cfg.large_file_mode == "reference":
            artifact = _spill_artifact(ws, session_id, path.name, path)
            ref = ContextReference(
                kind="file",
                source=source,
                label=token,
                target=str(path),
                included=True,
                expanded=False,
                detail="reference only (large file)",
                artifact_path=str(artifact) if artifact else None,
            )
            references.append(ref)
            blocks.append(
                _render_reference_block(token, display_path, str(path), artifact, size)
            )
            continue

        if total_inlined + len(content.encode("utf-8")) > cfg.max_total_inline_bytes:
            warnings.append(
                f"Skipped inline content for @{token}: total context budget exceeded."
            )
            ref = ContextReference(
                kind="file",
                source=source,
                label=token,
                target=str(path),
                included=False,
                expanded=False,
                detail="total inline budget exceeded",
            )
            references.append(ref)
            blocks.append(
                _render_reference_block(token, display_path, str(path), None, size)
            )
            continue

        ref = ContextReference(
            kind="file",
            source=source,
            label=token,
            target=str(path),
            included=True,
            expanded=True,
            detail="truncated" if truncated else "included",
            bytes_inlined=len(content.encode("utf-8")),
        )
        references.append(ref)
        total_inlined += ref.bytes_inlined
        blocks.append(
            _render_file_block(token, display_path, content, truncated=truncated)
        )

    expansion = _assemble_expansion(blocks, cfg)
    model_text = f"{raw}\n\n{expansion}" if expansion else raw
    return ProcessedTurnInput(
        display_text=display_text,
        model_text=model_text,
        references=references,
        warnings=warnings,
    )


def pending_context_previews(
    raw: str,
    *,
    workspace: Path,
    cwd: Path | None = None,
    config: ContextConfig | None = None,
) -> list[dict[str, object]]:
    """Lightweight preview for UI: which mentions will be included."""
    processed = process_turn_input(
        UserTurnInput(raw_text=raw),
        workspace=workspace,
        cwd=cwd,
        config=config,
    )
    return [
        {
            "kind": ref.kind,
            "label": ref.label,
            "target": ref.target,
            "included": ref.included,
            "detail": ref.detail,
        }
        for ref in processed.references
    ]


def _already_expanded(raw: str, cfg: ContextConfig) -> bool:
    return _EXPANSION_MARKER in raw and cfg.expansion_header in raw


def _collect_tokens(raw: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for token in _extract_at_mentions(raw):
        key = token.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, "at_mention"))
    for token in _extract_attached_media_paths(raw):
        key = token.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, "attached_media"))
    return out


def _extract_at_mentions(text: str) -> list[str]:
    chars = list(text)
    mentions: list[str] = []
    idx = 0
    while idx < len(chars):
        if chars[idx] != "@" or not _is_mention_start(chars, idx):
            idx += 1
            continue
        next_idx = idx + 1
        if next_idx >= len(chars):
            break
        nxt = chars[next_idx]
        if nxt.isspace():
            idx += 1
            continue
        if nxt in "\"'":
            quote = nxt
            end = next_idx + 1
            raw: list[str] = []
            while end < len(chars) and chars[end] != quote:
                raw.append(chars[end])
                end += 1
            token = "".join(raw).strip()
            if token:
                mentions.append(token)
            idx = end + 1
            continue
        end = next_idx
        raw = []
        while end < len(chars) and not chars[end].isspace():
            raw.append(chars[end])
            end += 1
        token = _trim_trailing_punct("".join(raw))
        if token:
            mentions.append(token)
        idx = end
    return mentions


def _is_mention_start(chars: list[str], idx: int) -> bool:
    if idx == 0:
        return True
    prev = chars[idx - 1]
    return prev.isspace() or prev in "([{<\"'"


def _trim_trailing_punct(raw: str) -> str:
    trimmed = raw.strip()
    while len(trimmed) > 1 and trimmed[-1] in ",;:!?)]}":
        trimmed = trimmed[:-1]
    return trimmed.strip()


def _extract_attached_media_paths(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed.startswith("[Attached ") or not trimmed.endswith("]"):
            continue
        body = trimmed[len("[Attached ") : -1]
        if ": " not in body:
            continue
        _kind, rest = body.split(": ", 1)
        path = rest.rsplit(" at ", 1)[-1].strip()
        if path:
            paths.append(path)
    return paths


def _expand_home(path: str) -> Path:
    if path == "~":
        return Path.home()
    if path.startswith("~/"):
        return Path.home() / path[2:]
    return Path(path)


def _resolve_mention(
    token: str,
    workspace: Path,
    cwd: Path,
) -> tuple[Path, str] | None:
    raw = token.strip().strip('"').strip("'")
    if not raw:
        return None
    candidate = _expand_home(raw)
    try:
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = None
            for base in (cwd, workspace):
                attempt = (base / candidate).resolve()
                if attempt.exists():
                    resolved = attempt
                    break
            if resolved is None:
                resolved = (workspace / candidate).resolve()
    except OSError:
        return None

    try:
        resolved.relative_to(workspace)
    except ValueError:
        return None

    display = _display_path(resolved, workspace)
    return resolved, display


def _display_path(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _classify_path(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "directory"
    if not path.is_file():
        return "binary"
    if _is_media_path(path):
        return "media"
    if _is_binary_file(path):
        return "binary"
    return "text"


def _is_media_path(path: Path) -> bool:
    ext = path.suffix.lstrip(".").lower()
    return ext in _MEDIA_EXTENSIONS


def _is_binary_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def _text_inclusion_mode(
    size: int,
    cfg: ContextConfig,
    total_inlined: int,
) -> str:
    if cfg.large_file_mode == "reference" and size > cfg.max_inline_bytes:
        return "reference"
    if total_inlined >= cfg.max_total_inline_bytes:
        return "reference"
    return "inline"


def _read_text_budget(path: Path, max_bytes: int) -> tuple[str, bool]:
    with path.open("rb") as fh:
        data = fh.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    if b"\x00" in data:
        raise OSError("file appears to be binary")
    text = data.decode("utf-8", errors="replace")
    return text, truncated


def _list_directory(path: Path, limit: int) -> str:
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return str(exc)
    lines: list[str] = []
    for entry in entries[:limit]:
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    if len(entries) > limit:
        lines.append(f"... {len(entries) - limit} more entries")
    return "\n".join(lines)


def _spill_artifact(workspace: Path, session_id: str | None, name: str, src: Path) -> Path | None:
    sid = session_id or "session"
    dest_dir = workspace / ".deepseek" / "context-artifacts" / sid
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        if src.is_file():
            dest.write_bytes(src.read_bytes())
        return dest
    except OSError:
        return None


def _render_file_block(
    token: str,
    display_path: str,
    content: str,
    *,
    truncated: bool,
) -> str:
    trunc_attr = ' truncated="true"' if truncated else ""
    return (
        f'<file mention="@{token}" path="{display_path}"{trunc_attr}>\n'
        f"{content}\n"
        f"</file>"
    )


def _render_directory_block(token: str, display_path: str, body: str) -> str:
    return (
        f'<directory mention="@{token}" path="{display_path}">\n'
        f"{body}\n"
        f"</directory>"
    )


def _render_media_hint_block(token: str, display_path: str) -> str:
    return (
        f'<media-file mention="@{token}" path="{display_path}">\n'
        f"Use /attach {token} when the intent is to attach this image or video.\n"
        f"</media-file>"
    )


def _render_missing_block(token: str, display_path: str, reason: str) -> str:
    return f'<missing-file mention="@{token}" path="{display_path}">{reason}</missing-file>'


def _render_unreadable_block(token: str, display_path: str, reason: str) -> str:
    return (
        f'<unreadable-file mention="@{token}" path="{display_path}">\n'
        f"{reason}\n"
        f"</unreadable-file>"
    )


def _render_reference_block(
    token: str,
    display_path: str,
    abs_path: str,
    artifact: Path | None,
    size: int,
) -> str:
    artifact_line = f"\nArtifact: {artifact}" if artifact else ""
    return (
        f'<file-reference mention="@{token}" path="{display_path}" bytes="{size}">\n'
        f"Full path: {abs_path}. Use read_file for content.{artifact_line}\n"
        f"</file-reference>"
    )


def _assemble_expansion(blocks: list[str], cfg: ContextConfig) -> str:
    if not blocks:
        return ""
    body = "\n\n".join(blocks)
    return f"{_EXPANSION_MARKER}\n\n{cfg.expansion_header}\n{body}"


def detect_mime(path: Path) -> str | None:
    mime, _ = mimetypes.guess_type(path.name)
    return mime
