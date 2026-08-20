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


def test_delete_discussion_removes_persisted_messages(monkeypatch, tmp_path):
    """Deleting a discussion removes the complete local conversation record."""
    monkeypatch.setattr(discussions, "DISCUSSIONS_PATH", tmp_path / "history.json")
    discussion_id = discussions.save_discussion_message(None, "问题", "回答", [])

    assert discussions.delete_discussion(discussion_id) is True
    assert discussions.get_discussion(discussion_id) is None
    assert discussions.list_discussions() == []


def test_discussion_title_is_user_supplied_and_can_be_renamed(monkeypatch, tmp_path):
    """A custom discussion title persists and is reflected in history."""
    monkeypatch.setattr(discussions, "DISCUSSIONS_PATH", tmp_path / "history.json")
    discussion_id = discussions.save_discussion_message(None, "问题", "回答", [], "预测模型讨论")

    assert discussions.list_discussions()[0]["title"] == "预测模型讨论"
    assert discussions.rename_discussion(discussion_id, "最终方案") is True
    assert discussions.list_discussions()[0]["title"] == "最终方案"


def test_saved_discussion_retains_attachment_context(monkeypatch, tmp_path):
    """Parsed attachment content is retained for later discussion turns."""
    monkeypatch.setattr(discussions, "DISCUSSIONS_PATH", tmp_path / "history.json")
    attachments = [{"kind": "text", "name": "data.json", "content": '{"x": 1}'}]
    discussion_id = discussions.save_discussion_message(None, "分析附件", "已分析", [], attachments=attachments)

    assert discussions.get_discussion(discussion_id)["messages"][0]["attachments"] == attachments
