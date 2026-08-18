"""Persistent local storage for inspiration discussion history."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


DISCUSSIONS_PATH = Path(__file__).resolve().parent / "discussion_history.json"
_DISCUSSIONS_LOCK = Lock()


def list_discussions() -> list[dict[str, Any]]:
    """Return local discussions ordered by most recently updated."""
    with _DISCUSSIONS_LOCK:
        discussions = _read_discussions()
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "updated_at": item["updated_at"],
        }
        for item in sorted(discussions, key=lambda item: item["updated_at"], reverse=True)
    ]


def get_discussion(discussion_id: str) -> dict[str, Any] | None:
    """Return one saved discussion, including all of its messages."""
    with _DISCUSSIONS_LOCK:
        return next(
            (item for item in _read_discussions() if item["id"] == discussion_id),
            None,
        )


def save_discussion_message(
    discussion_id: str | None,
    user_message: str,
    assistant_message: str,
    sources: list[dict[str, str]],
) -> str:
    """Append one exchange and return its persistent discussion ID."""
    now = datetime.now(timezone.utc).isoformat()
    with _DISCUSSIONS_LOCK:
        discussions = _read_discussions()
        discussion = next(
            (item for item in discussions if item["id"] == discussion_id),
            None,
        )
        if discussion is None:
            discussion = {
                "id": str(uuid.uuid4()),
                "title": user_message[:40],
                "created_at": now,
                "updated_at": now,
                "messages": [],
            }
            discussions.append(discussion)
        discussion["messages"].extend([
            {"role": "user", "content": user_message, "sources": []},
            {"role": "assistant", "content": assistant_message, "sources": sources},
        ])
        discussion["updated_at"] = now
        _write_discussions(discussions)
        return str(discussion["id"])


def _read_discussions() -> list[dict[str, Any]]:
    if not DISCUSSIONS_PATH.exists():
        return []
    try:
        content = json.loads(DISCUSSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return content if isinstance(content, list) else []


def _write_discussions(discussions: list[dict[str, Any]]) -> None:
    temporary_path = DISCUSSIONS_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(discussions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(DISCUSSIONS_PATH)
