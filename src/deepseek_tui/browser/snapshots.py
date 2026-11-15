"""Bounded, memory-only reading of already collected observations. Never touches the page."""

from deepseek_tui.browser.context import PAGE_CONTENT_NOTICE


def remember(cache, observation):
    identity = observation.get("observation_id")
    if not identity or identity in cache:
        return
    # Store only public observation text and names, never backend nodes or field values.
    text = observation.get("text", "")
    names = "\n".join(str(e.get("name", "")) for e in observation.get("elements", []))
    cache[identity] = {
        "observation_id": identity,
        "url": observation.get("url", ""),
        "document_id": observation.get("document_id"),
        "frame_id": observation.get("frame_id"),
        "scope_selector": observation.get("scope_selector"),
        "coverage": "collected_observation_only",
        "continuation": {k: observation[k] for k in (
            "next_text_offset", "next_element_offset", "next_frame_offset")
            if observation.get(k) is not None},
        "text": (text + "\n" + names)[:64000],
        "cache_truncated": len(text) + 1 + len(names) > 64000,
    }
    while len(cache) > 4:
        cache.pop(next(iter(cache)))


def read(cache, identity, query="", offset=0):
    if identity not in cache:
        raise ValueError("Observation is not cached (only the latest four are retained); "
                         "observe again")
    snapshot = cache[identity]
    text = snapshot["text"]
    result = {k: v for k, v in snapshot.items() if k != "text"}
    result.update(source=PAGE_CONTENT_NOTICE, historical=True, actionable=False,
                  total_chars=len(text))
    if query:
        # Literal and case-sensitive: offsets always address the unchanged original text.
        matches = []
        position = text.find(query, offset)
        while position >= 0 and len(matches) < 8:
            start, end = max(0, position - 100), min(len(text), position + len(query) + 100)
            matches.append({"offset": position, "text": text[start:end][:1000]})
            position = text.find(query, position + max(1, len(query)))
        result.update(matches=matches, next_text_offset=position if position >= 0 else None)
    else:
        end = min(len(text), offset + 3000)
        result.update(text=text[offset:end], text_offset=offset,
                      next_text_offset=end if end < len(text) else None)
    return result
