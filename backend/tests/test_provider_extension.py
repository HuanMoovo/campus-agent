"""International presets and MiMo/GLM are concrete wire contracts, not labels."""
import json
from types import SimpleNamespace

import httpx
import pytest

from app import model_client, model_runtime as runtime
from app.provider_catalog import PROVIDERS
from app.schemas import ChatRequest


NEW_IDS = ("xiaomi", "zai", "xai", "openrouter", "groq", "mistral", "together", "fireworks",
           "deepinfra", "cerebras", "huggingface", "cohere")


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path,
        qwen_api_key="", deepseek_api_key="", qwen_model="qwen", deepseek_model="deepseek",
        qwen_base_url="https://qwen.invalid/v1", deepseek_base_url="https://deepseek.invalid/v1"))
    monkeypatch.setattr(runtime, "_encrypt", lambda value: "test:" + value[::-1])
    monkeypatch.setattr(runtime, "_decrypt", lambda value: value[5:][::-1])


@pytest.mark.parametrize("provider", NEW_IDS)
def test_new_provider_can_be_configured_and_addressed_by_chat(config, provider):
    assert ChatRequest(message="hello", model=provider).model == provider
    result = runtime.update_provider(provider, {"api_key": "synthetic-key", "model": "my-model"})
    assert result["providers"][provider]["configured"]
    assert "synthetic-key" not in json.dumps(result)
    assert PROVIDERS[provider]["docs_url"].startswith("https://")
    assert PROVIDERS[provider]["base_url"].startswith("https://")


def test_xiaomi_uses_documented_raw_api_key_and_completion_token_field(config, monkeypatch):
    runtime.update_provider("xiaomi", {"api_key": "synthetic-mimo-key", "model": "my-mimo-model"})
    current = runtime.provider_settings("xiaomi")
    requests = []
    real = httpx.Client
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs))
    assert model_client.complete(("xiaomi", current["api_key"], current["base_url"], current["model"]),
        [{"role": "user", "content": "hello"}], request_options=current["request_options"])["content"] == "answer"
    assert str(requests[0].url) == "https://api.xiaomimimo.com/v1/chat/completions"
    assert requests[0].headers["api-key"] == "synthetic-mimo-key"
    assert "authorization" not in requests[0].headers
    body = json.loads(requests[0].content)
    assert body["max_completion_tokens"] == 900 and "max_tokens" not in body and "temperature" not in body
    def post(url, **kwargs):
        return respond(httpx.Request("POST", url, headers=kwargs["headers"], json=kwargs["json"]))
    monkeypatch.setattr(httpx, "post", post)
    assert runtime.test_provider("xiaomi")["ok"] is True
    assert requests[-1].headers["api-key"] == "synthetic-mimo-key"


def test_domestic_and_international_glm_keys_and_endpoints_are_independent(config):
    runtime.update_provider("zhipu", {"api_key": "domestic-key", "model": "domestic-model"})
    runtime.update_provider("zai", {"api_key": "global-key", "model": "global-model"})
    assert runtime.provider_settings("zhipu")["api_key"] == "domestic-key"
    assert runtime.provider_settings("zai")["api_key"] == "global-key"
    assert runtime.provider_settings("zhipu")["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert runtime.provider_settings("zai")["base_url"] == "https://api.z.ai/api/paas/v4"
    runtime.update_provider("zai", {"clear_api_key": True})
    assert runtime.provider_settings("zhipu")["api_key"] == "domestic-key"


@pytest.mark.parametrize("provider", ["xai", "openrouter", "groq", "mistral", "together", "fireworks",
    "deepinfra", "cerebras", "huggingface", "cohere", "zai"])
def test_international_saved_preset_reaches_its_documented_endpoint_and_auth(config, monkeypatch, provider):
    runtime.update_provider(provider, {"api_key": "synthetic-key", "model": "account/model"})
    requests = []
    def post(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "post", post)
    assert runtime.test_provider(provider)["ok"] is True
    assert requests[0][0] == PROVIDERS[provider]["base_url"].rstrip("/") + "/chat/completions"
    assert requests[0][1]["headers"]["Authorization"] == "Bearer synthetic-key"
