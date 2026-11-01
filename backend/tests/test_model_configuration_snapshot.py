"""A model status operation reads one coherent, immediately fresh snapshot."""
import json
from types import SimpleNamespace

import pytest

from app import model_runtime as runtime


@pytest.fixture
def settings(monkeypatch, tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, qwen_api_key="environment-key", deepseek_api_key="",
                               qwen_base_url="https://qwen.example/v1", qwen_model="qwen",
                               deepseek_base_url="https://deepseek.example/v1", deepseek_model="deepseek")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    return settings


def test_configuration_reads_once_and_refreshes_next_operation(settings, monkeypatch):
    path = settings.data_dir / "model-providers.json"
    path.write_text(json.dumps({"qwen": {"api_key": runtime._encrypt("synthetic-key"), "model": "first"}}))
    original = runtime._load
    loads = []
    def load():
        loads.append(1)
        return original()
    monkeypatch.setattr(runtime, "_load", load)
    first = runtime.configuration()
    assert first["providers"]["qwen"]["configured"] is True
    assert len(loads) == 1
    assert "synthetic-key" not in json.dumps(first)
    path.write_text(json.dumps({"qwen": {"api_key": "", "model": "second"}}))
    second = runtime.configuration()
    assert second["providers"]["qwen"]["configured"] is False
    assert second["providers"]["qwen"]["model"] == "second"
    assert len(loads) == 2
    path.unlink()
    assert runtime.configuration()["providers"]["qwen"]["configured"] is True
    assert len(loads) == 3


def test_configuration_keeps_one_snapshot_during_atomic_replacement(settings, monkeypatch):
    path = settings.data_dir / "model-providers.json"
    path.write_text(json.dumps({"ollama": {"model": "before"}}))
    original = runtime._load
    def replace_after_read():
        snapshot = original()
        replacement = path.with_suffix(".tmp")
        replacement.write_text(json.dumps({"ollama": {"model": "after"}}))
        replacement.replace(path)
        return snapshot
    monkeypatch.setattr(runtime, "_load", replace_after_read)
    assert runtime.configuration()["ollama"]["model"] == "before"
    assert runtime.configuration()["ollama"]["model"] == "after"


@pytest.mark.parametrize("stored", ["[]", "{broken", '{"qwen":{"api_key":"foreign:bad"}}'])
def test_snapshot_preserves_invalid_storage_errors(settings, stored):
    (settings.data_dir / "model-providers.json").write_text(stored)
    with pytest.raises(ValueError):
        runtime.configuration()
