"""Offline coverage for request-scoped Ollama chat and grounded fallback behavior."""
import json

import httpx
import pytest
from pydantic import ValidationError

from app import agent, model_runtime as runtime
from app.schemas import ChatRequest


@pytest.mark.parametrize("provider", [None, "auto", "qwen", "deepseek"])
def test_explicit_local_model_cannot_route_to_cloud(provider):
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", model=provider, local_model="custom:latest")


@pytest.mark.parametrize("name", ["", "bad name", "model\nname", "model?bad", "a" * 129])
def test_invalid_request_model_names_are_rejected(name):
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", model="ollama", local_model=name)


def test_request_model_name_is_optional_and_accepts_installed_custom_models():
    assert ChatRequest(message="hello", model="ollama").local_model is None
    assert ChatRequest(message="hello", model="ollama", local_model="organization/custom:Q4_K_M").local_model == "organization/custom:Q4_K_M"


def test_resolve_installed_model_without_changing_saved_default(monkeypatch):
    monkeypatch.setattr(runtime, "provider_settings", lambda provider: {"model": "saved:latest"})
    monkeypatch.setattr(runtime, "local_models", lambda: {
        "running": True, "installed": [{"name": "saved:latest"}, {"name": "custom:Q4_K_M"}],
    })
    assert runtime.resolve_local_model("custom:Q4_K_M") == "custom:Q4_K_M"
    assert runtime.resolve_local_model() == "saved:latest"
    assert runtime.resolve_local_model("saved") == "saved:latest"


@pytest.mark.parametrize("running,status", [(True, 409), (False, 503)])
def test_unavailable_local_model_is_an_explicit_error(monkeypatch, running, status):
    monkeypatch.setattr(runtime, "local_models", lambda: {"running": running, "installed": []})
    with pytest.raises(runtime.LocalModelError) as error:
        runtime.resolve_local_model("custom:latest")
    assert error.value.status_code == status


def install_local_transport(monkeypatch, handler):
    requested_providers = []

    def settings(provider):
        requested_providers.append(provider)
        assert provider == "ollama"
        return {"model": "saved:latest", "base_url": "https://ignored.invalid/v1", "api_key": "unused"}

    real_client = httpx.Client

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"].read == 180
        assert kwargs["timeout"].connect == 5
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(agent, "provider_settings", settings)
    monkeypatch.setattr(agent.httpx, "Client", client)
    return requested_providers


def test_general_local_chat_calls_selected_model_without_tool_support(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert "authorization" not in request.headers
        assert body["model"] == "organization/custom:Q4_K_M"
        assert body["stream"] is False
        assert body["think"] is False
        assert "tools" not in body
        assert body["messages"][-1]["content"] == "用 Python 写一个列表推导式"
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "[n * 2 for n in range(3)]"}})

    providers = install_local_transport(monkeypatch, handler)
    monkeypatch.setattr(agent.knowledge_index, "search", lambda db, question: [])
    result = agent.run_agent(None, "用 Python 写一个列表推导式", [], "ollama", "organization/custom:Q4_K_M")
    assert result["mode"] == "llm"
    assert result["answer"] == "[n * 2 for n in range(3)]"
    assert len(requests) == 1
    assert providers == ["ollama"]


def test_empty_school_policy_retrieval_remains_grounded(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail("Ungrounded campus policy was sent to the model")

    monkeypatch.setattr(agent, "call_model", unexpected_call)
    state = {"question": "本校奖学金申请条件是什么？", "history": [], "intent": "knowledge",
             "requested_model": "ollama", "local_model": "custom:latest", "sources": []}
    assert "暂未找到可靠依据" in agent.respond(state)["answer"]
    state.update(question="需要什么材料？", history=[{"role": "user", "content": "本校奖学金申请条件是什么？"}])
    assert "暂未找到可靠依据" in agent.respond(state)["answer"]


def test_local_model_error_does_not_fall_back_to_cloud_or_demo(monkeypatch):
    providers = install_local_transport(monkeypatch, lambda request: httpx.Response(500, json={"error": "out of memory"}))
    with pytest.raises(runtime.LocalModelError) as error:
        agent.call_model([{"role": "user", "content": "hello"}], "ollama", "custom:latest")
    assert error.value.status_code == 502
    assert providers == ["ollama"]


def test_local_timeout_is_reported(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow model", request=request)

    install_local_transport(monkeypatch, handler)
    with pytest.raises(runtime.LocalModelError) as error:
        agent.call_model([{"role": "user", "content": "hello"}], "ollama", "custom:latest")
    assert error.value.status_code == 504


@pytest.mark.parametrize("payload", [{}, {"message": []}, {"message": {"content": ""}},
                                     {"message": {"thinking": "unshown reasoning"}}])
def test_invalid_or_empty_local_answer_is_reported(monkeypatch, payload):
    install_local_transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(runtime.LocalModelError) as error:
        agent.call_model([{"role": "user", "content": "hello"}], "ollama", "custom:latest")
    assert error.value.status_code == 502
