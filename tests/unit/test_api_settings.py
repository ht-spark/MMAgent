"""API 配置本地持久化端点测试（无 LLM、无网络）。"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from server import main


def _use_tmp_settings(monkeypatch, tmp_path):
    path = tmp_path / "api_settings.json"
    monkeypatch.setattr(main, "API_SETTINGS_PATH", path)
    return path


def test_get_returns_unsaved_when_no_file(monkeypatch, tmp_path):
    _use_tmp_settings(monkeypatch, tmp_path)
    result = asyncio.run(main.get_api_settings_endpoint())
    assert result["saved"] is False
    assert result["configs"] == []
    assert result["active_id"] is None


def test_put_then_get_roundtrip(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    snapshot = {
        "configs": [
            {
                "id": "cfg_1",
                "name": "DeepSeek",
                "provider": "deepseek",
                "apiKey": "sk-test",
                "baseUrl": "https://api.deepseek.com",
                "model": "deepseek-chat",
                "createdAt": 1,
            }
        ],
        "active_id": "cfg_1",
        "external_services": {"tavily": {"apiKey": "tvly-x", "baseUrl": ""}},
    }

    asyncio.run(main.save_api_settings_endpoint(snapshot))
    assert path.exists()

    result = asyncio.run(main.get_api_settings_endpoint())
    assert result["saved"] is True
    assert result["configs"][0]["id"] == "cfg_1"
    assert result["active_id"] == "cfg_1"
    assert result["external_services"]["tavily"]["apiKey"] == "tvly-x"


def test_put_rejects_malformed_configs(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.save_api_settings_endpoint({"configs": "not-a-list"}))
    assert exc.value.status_code == 422
    assert not path.exists()


def test_put_sanitizes_non_string_active_id(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    asyncio.run(
        main.save_api_settings_endpoint({"configs": [], "active_id": 123, "external_services": None})
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["active_id"] is None
    assert data["external_services"] == {}


def test_get_survives_corrupt_file(monkeypatch, tmp_path):
    path = _use_tmp_settings(monkeypatch, tmp_path)
    path.write_text("{broken json", encoding="utf-8")
    result = asyncio.run(main.get_api_settings_endpoint())
    assert result["saved"] is False
