"""Offline contract tests for a separate OpenAI-compatible chat provider."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from app import agent, model_runtime as runtime
from app.schemas import ChatRequest, SettingsUpdate


@pytest.fixture
def config(monkeypatch, tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, qwen_api_key='', deepseek_api_key='',
        qwen_base_url='https://qwen.example/v1', qwen_model='qwen',
        deepseek_base_url='https://deepseek.example/v1', deepseek_model='deepseek')
    monkeypatch.setattr(runtime, 'get_settings', lambda: settings)
    monkeypatch.setattr(runtime, '_encrypt', lambda value: 'encrypted:' + value[::-1])
    monkeypatch.setattr(runtime, '_decrypt', lambda value: value.removeprefix('encrypted:')[::-1])
    return settings


def test_provider_config_is_separate_and_host_change_cannot_reuse_secret(config):
    result = runtime.update_provider('openai_compatible', {'base_url': 'https://models.example/v1', 'model': 'vendor/model', 'api_key': 'sensitive-key'})
    assert result['providers']['openai_compatible']['configured']
    assert 'sensitive-key' not in json.dumps(result)
    assert 'sensitive-key' not in runtime._config_path().read_text()
    with pytest.raises(ValueError, match='requires a new API key'):
        runtime.update_provider('openai_compatible', {'base_url': 'https://other.example/v1'})
    assert runtime.provider_settings('openai_compatible')['api_key'] == 'sensitive-key'
    assert not runtime.update_provider('openai_compatible', {'clear_api_key': True})['providers']['openai_compatible']['configured']


def test_compatible_model_is_explicitly_selectable_in_schemas_and_auto_fallback(config):
    assert ChatRequest(message='hello', model='openai_compatible').model == 'openai_compatible'
    assert SettingsUpdate(model='openai_compatible').model == 'openai_compatible'
    with pytest.raises(ValidationError):
        ChatRequest(message='hello', model='openai_compatible', local_model='local')
    runtime.update_provider('openai_compatible', {'base_url': 'https://models.example/v1', 'model': 'vendor/model', 'api_key': 'key'})
    assert agent.choose_model('openai_compatible')[0] == 'openai_compatible'
    assert agent.choose_model('auto')[0] == 'openai_compatible'


def test_compatible_completion_uses_configured_model_without_vendor_options(monkeypatch):
    captured = []
    real_client = httpx.Client
    def handle(req):
        captured.append(req)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    monkeypatch.setattr(agent, 'provider_settings', lambda provider: {'api_key': 'key', 'base_url': 'https://models.example/v1', 'model': 'vendor/model'})
    monkeypatch.setattr(agent.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    assert agent.call_model([{'role': 'user', 'content': 'hello'}], 'openai_compatible', reasoning='deep') == 'ok'
    req = captured[0]
    body = json.loads(req.content)
    assert str(req.url) == 'https://models.example/v1/chat/completions'
    assert req.headers['authorization'] == 'Bearer key'
    assert body['model'] == 'vendor/model'
    assert 'enable_thinking' not in body and 'think' not in body


def test_compatible_stream_uses_standard_sse(monkeypatch):
    captured = []
    real_client = httpx.AsyncClient
    def handle(req):
        captured.append(req)
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(agent, 'provider_settings', lambda provider: {'api_key': 'key', 'base_url': 'https://models.example/v1', 'model': 'vendor/model'})
    monkeypatch.setattr(agent.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    async def collect():
        return [chunk async for chunk in agent.stream_model([{'role': 'user', 'content': 'hello'}], 'openai_compatible', reasoning='deep')]
    assert asyncio.run(collect()) == [('content', 'answer')]
    body = json.loads(captured[0].content)
    assert body['model'] == 'vendor/model' and body['stream'] is True
    assert 'enable_thinking' not in body and 'think' not in body


def test_connection_test_posts_to_custom_base_path_with_configured_model(monkeypatch, config):
    runtime.update_provider('openai_compatible', {'base_url': 'https://models.example/gateway/v2', 'model': 'vendor/model', 'api_key': 'key'})
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    monkeypatch.setattr(runtime.httpx, 'post', post)
    result = runtime.test_provider('openai_compatible')
    assert result['ok'] is True
    assert result['capabilities'] == {'chat': 'verified', 'streaming': 'not_tested', 'tools': 'not_tested'}
    assert calls[0][0] == 'https://models.example/gateway/v2/chat/completions'
    assert calls[0][1]['headers']['Authorization'] == 'Bearer key'
    assert calls[0][1]['json']['model'] == 'vendor/model'


def test_connection_test_requires_a_model_before_calling_provider(monkeypatch, config):
    runtime.update_provider('openai_compatible', {'api_key': 'key'})
    monkeypatch.setattr(runtime.httpx, 'post', lambda *a, **kw: pytest.fail('must not call without a model'))
    assert runtime.test_provider('openai_compatible')['ok'] is False


@pytest.mark.parametrize('body', [b'<html>login</html>', b'{}', b'{"choices": []}'])
def test_connection_test_rejects_non_chat_responses(monkeypatch, config, body):
    runtime.update_provider('openai_compatible', {'model': 'vendor/model', 'api_key': 'key'})
    monkeypatch.setattr(runtime.httpx, 'post', lambda *args, **kwargs: httpx.Response(200, content=body))
    assert runtime.test_provider('openai_compatible')['ok'] is False


@pytest.mark.parametrize('status', [301, 302, 307])
def test_connection_test_rejects_redirects(monkeypatch, config, status):
    runtime.update_provider('openai_compatible', {'model': 'vendor/model', 'api_key': 'key'})
    monkeypatch.setattr(runtime.httpx, 'post', lambda *args, **kwargs: httpx.Response(status, json={'choices': [{'message': {'content': 'ok'}}]}))
    assert runtime.test_provider('openai_compatible')['ok'] is False


@pytest.mark.parametrize('address', ['http://models.example/v1', 'https://user:pass@models.example/v1',
                                     'https://models.example/a/../v1', 'https://models.example/v1?key=secret',
                                     'https://models.example/a%2f..%2fv1'])
def test_compatible_base_url_rejects_unsafe_forms(config, address):
    with pytest.raises(ValueError):
        runtime.update_provider('openai_compatible', {'base_url': address})
