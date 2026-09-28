"""The native protocol, rather than file concatenation, owns online history."""

import pytest

from deepseek_tui.server.codex_history import CodexHistoryClient


def client_for(pages, *, after=None):
    client = CodexHistoryClient.__new__(CodexHistoryClient)
    calls = []
    reads = 0

    def call(method, params):
        nonlocal reads
        calls.append((method, params))
        if method == "thread/read":
            reads += 1
            return {
                "thread": (
                    after
                    if after is not None and reads > 1
                    else {"id": "source", "updatedAt": 1, "status": {"type": "idle"}}
                )
            }
        return pages.pop(0)

    client.call = call
    return client, calls


def test_native_history_reads_all_full_pages_without_resume():
    client, calls = client_for(
        [
            {"data": [{"id": "t1", "itemsView": "full", "items": []}], "nextCursor": "next"},
            {"data": [{"id": "t2", "itemsView": "full", "items": []}], "nextCursor": None},
        ]
    )
    _, turns = client.read("source")
    assert [t["id"] for t in turns] == ["t1", "t2"]
    assert {method for method, _ in calls} == {"thread/read", "thread/turns/list"}
    requests = [p for m, p in calls if m == "thread/turns/list"]
    assert [p["cursor"] for p in requests] == [None, "next"]
    assert all(p["itemsView"] == "full" and p["sortDirection"] == "asc" for p in requests)


@pytest.mark.parametrize(
    "pages,match",
    [
        ([{"data": [], "nextCursor": "same"}, {"data": [], "nextCursor": "same"}], "repeated"),
        ([{"data": [{"id": "t", "itemsView": "summary"}], "nextCursor": None}], "incomplete"),
        (
            [
                {"data": [{"id": "t", "itemsView": "full"}], "nextCursor": "next"},
                {"data": [{"id": "t", "itemsView": "full"}], "nextCursor": None},
            ],
            "overlapping",
        ),
    ],
)
def test_native_pagination_fails_closed(pages, match):
    client, _ = client_for(pages)
    with pytest.raises(ValueError, match=match):
        client.read("source")


def test_native_history_rejects_changes_during_pagination():
    client, _ = client_for([{"data": [], "nextCursor": None}], after={"updatedAt": 2})
    with pytest.raises(ValueError, match="changed"):
        client.read("source")
