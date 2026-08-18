"""Tests for local inspiration discussion persistence."""
from __future__ import annotations

from server import discussions


def test_saved_discussion_can_be_listed_and_restored(monkeypatch, tmp_path):
    """A saved exchange remains available for a later continued discussion."""
    monkeypatch.setattr(discussions, "DISCUSSIONS_PATH", tmp_path / "history.json")

    discussion_id = discussions.save_discussion_message(
        None,
        "如何建立预测模型？",
        "可以先明确预测目标。",
        [{"source_file": "reference.md", "document_id": "doc-id", "content": "预测资料"}],
    )

    assert discussions.list_discussions()[0]["id"] == discussion_id
    restored = discussions.get_discussion(discussion_id)
    assert restored is not None
    assert restored["messages"][1]["sources"][0]["source_file"] == "reference.md"
