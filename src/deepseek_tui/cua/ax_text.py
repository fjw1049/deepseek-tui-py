"""Shorten an accessibility listing that is too large to show whole.

A big listing is almost always one long run of look-alike siblings (rows of a file list,
cells of a table) while the controls the model needs sit before or after it. Only those
runs are cut, to their first and last few members plus one line that names how many were
left out and their index range. Selected and focused elements always stay, and nothing
else (headers, documentation, other blocks) is touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Runtime listings start with one of these; anything else (documentation, notes) is kept.
_LISTING = re.compile(r"^(Window: |The following is a diff from the previous accessibility tree)")
_INDEX = re.compile(r"^(\d+)\s")
_FOCUSED = re.compile(r"The focused UI element is (\d+)")


@dataclass
class _Node:
    line: str
    depth: int
    index: int | None
    children: list[_Node] = field(default_factory=list)

    def indices(self) -> list[int]:
        own = [self.index] if self.index is not None else []
        return own + [i for child in self.children for i in child.indices()]


def is_listing(text: str) -> bool:
    return bool(_LISTING.match(text))


def _parse(text: str) -> _Node:
    root = _Node("", -1, None)
    stack = [root]
    for line in text.split("\n"):
        # Diff lines carry a +/~ marker before their indentation.
        body = line[1:] if line[:1] in "+~" else line
        depth = len(body) - len(body.lstrip("\t"))
        match = _INDEX.match(body.lstrip("\t"))
        node = _Node(line, depth if line.strip() else 0, int(match.group(1)) if match else None)
        while stack[-1].depth >= node.depth and len(stack) > 1:
            stack.pop()
        stack[-1].children.append(node)
        stack.append(node)
    return root


def _kept(text: str) -> set[int]:
    """Indices the listing itself points at: the selection and the focused element."""
    kept = {int(m) for m in _FOCUSED.findall(text)}
    selected = text.split("\nSelected:\n", 1)
    if len(selected) == 2:
        for line in selected[1].split("\n"):
            if not line.strip():
                break
            if match := _INDEX.match(line.strip().lstrip("+~")):
                kept.add(int(match.group(1)))
    return kept


def shorten(text: str, first: int, last: int) -> tuple[str, int]:
    """The listing with long sibling runs cut, and how many elements were left out."""
    kept = _kept(text)
    out: list[str] = []
    omitted = 0

    def emit(node: _Node) -> None:
        nonlocal omitted
        if node.depth >= 0:
            out.append(node.line)
        children = node.children
        # The root's children are the listing's own header lines and top-level windows.
        if node.depth < 0 or len(children) <= first + last + 1:
            for child in children:
                emit(child)
            return
        skipped: list[_Node] = []

        def flush() -> None:
            nonlocal omitted
            if not skipped:
                return
            indices = [i for child in skipped for i in child.indices()]
            span = f", indices {min(indices)}-{max(indices)}" if indices else ""
            out.append("\t" * (node.depth + 1)
                       + f"… {len(skipped)} more items here not shown{span}")
            omitted += len(indices) or len(skipped)
            skipped.clear()

        for position, child in enumerate(children):
            edge = position < first or position >= len(children) - last
            if edge or kept.intersection(child.indices()):
                flush()
                emit(child)
            else:
                skipped.append(child)
        flush()

    emit(_parse(text))
    return "\n".join(out), omitted
