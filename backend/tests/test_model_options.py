"""Saved compatibility options never change key or endpoint security rules."""
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import model_runtime as runtime
from app.schemas import ModelProviderUpdate


DEFAULTS = {"token_parameter": "max_tokens", "send_temperature": True,
            "supports_tools": True, "supports_streaming": True, "max_output_tokens": 900,
            "reasoning_efforts": None}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, qwen_api_key="", deepseek_api_key="",
                               qwen_base_url="https://qwen.example/v1", qwen_model="qwen",
                               deepseek_base_url="https://deepseek.example/v1", deepseek_model="deepseek")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_encrypt", lambda value: "encrypted:" + value[::-1])
    monkeypatch.setattr(runtime, "_decrypt", lambda value: value.removeprefix("encrypted:")[::-1])


def test_legacy_configuration_gets_request_defaults_without_rewriting_file():
    runtime._save({"openai_compatible": {"model": "custom", "api_key": ""}})
    original = runtime._config_path().read_bytes()
    row = runtime.configuration()["providers"]["openai_compatible"]
    assert row["request_options"] == DEFAULTS
    assert row["api_key_set"] is False
    assert runtime.provider_settings("openai_compatible")["request_options"] == DEFAULTS
    assert runtime._config_path().read_bytes() == original


def test_options_round_trip_and_key_presence_is_independent_of_complete_config():
    result = runtime.update_provider("openai_compatible", {
        "api_key": "private-sentinel", "request_options": {"token_parameter": "max_completion_tokens",
        "send_temperature": False, "supports_tools": False, "supports_streaming": False}})
    row = result["providers"]["openai_compatible"]
    assert row["api_key_set"] is True and row["configured"] is False
    assert row["request_options"]["supports_streaming"] is False
    assert "private-sentinel" not in json.dumps(result)
    runtime.update_provider("openai_compatible", {"model": "new-model"})
    assert runtime.provider_settings("openai_compatible")["request_options"] == row["request_options"]
    cleared = runtime.update_provider("openai_compatible", {"clear_api_key": True})
    assert cleared["providers"]["openai_compatible"]["api_key_set"] is False
    assert cleared["providers"]["openai_compatible"]["request_options"] == row["request_options"]


@pytest.mark.parametrize("options", [None, [], "auto", {"send_temperature": None},
    {"send_temperature": 0}, {"supports_tools": "false"}, {"supports_streaming": 1},
    {"token_parameter": "auto"}, {"token_parameter": None}, {"extra": True}])
def test_bad_options_rejected_by_storage_and_http_schema(options):
    with pytest.raises(ValueError):
        runtime.update_provider("qwen", {"request_options": options})
    with pytest.raises(ValidationError):
        ModelProviderUpdate(request_options=options)
    assert not runtime._config_path().exists()


def test_partial_option_update_keeps_other_saved_options():
    runtime.update_provider("qwen", {"request_options": {"send_temperature": False}})
    runtime.update_provider("qwen", {"request_options": {"supports_tools": False}})
    assert runtime.provider_settings("qwen")["request_options"] == {
        **DEFAULTS, "send_temperature": False, "supports_tools": False}


@pytest.mark.parametrize("changes", [{"typo": True}, {"clear_api_key": "yes"}, {"clear_api_key": None}])
def test_unknown_or_unsafe_control_fields_do_not_get_silently_saved(changes):
    with pytest.raises(ValueError):
        runtime.update_provider("qwen", changes)


def test_local_model_rejects_cloud_options():
    with pytest.raises(ValueError):
        runtime.update_provider("ollama", {"model": "tiny:latest", "request_options": DEFAULTS})


def test_options_do_not_bypass_saved_key_host_guard():
    runtime.update_provider("qwen", {"api_key": "original-private-key"})
    with pytest.raises(ValueError, match="requires a new API key"):
        runtime.update_provider("qwen", {"base_url": "https://other.example/v1",
                                        "request_options": {"send_temperature": False}})
    assert runtime.provider_settings("qwen")["request_options"] == DEFAULTS
