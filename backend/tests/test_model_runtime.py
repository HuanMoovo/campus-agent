"""Small, offline model-management tests; no model weights or network are used."""
import hashlib
import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from app import model_runtime as runtime


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        data_dir=tmp_path, qwen_api_key="", deepseek_api_key="",
        qwen_base_url="https://qwen.example/v1", qwen_model="qwen",
        deepseek_base_url="https://deepseek.example/v1", deepseek_model="deepseek",
    )
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_jobs", {})
    return settings


def dns(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


def mock_clients(monkeypatch, handler):
    real_client = httpx.Client
    options = []

    def create(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs.get("follow_redirects", False) is False
        options.append(kwargs)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(runtime.httpx, "Client", create)
    return options


def tiny_spec(monkeypatch, data=b"tiny gguf test data"):
    spec = {
        "id": "test:tiny", "repo": "owner/test", "revision": "pinned-revision",
        "file": "tiny.gguf", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }
    monkeypatch.setattr(runtime, "_catalog", {spec["id"]: spec})
    return spec, data


def job():
    return runtime.DownloadJob("offline-test", "test:tiny", "huggingface")


def test_provider_configuration_never_echoes_keys_and_can_clear_them(isolated_settings):
    secret = "secret-qwen-key"
    result = runtime.update_provider("qwen", {"api_key": secret, "model": "qwen-test"})
    assert result["providers"]["qwen"]["configured"] is True
    assert secret not in json.dumps(result)
    assert "api_key" not in result["providers"]["qwen"]
    assert runtime.provider_settings("qwen")["api_key"] == secret
    stored = (isolated_settings.data_dir / "model-providers.json").read_text(encoding="utf-8")
    assert secret not in stored
    result = runtime.update_provider("qwen", {"model": "qwen-next"})
    assert result["providers"]["qwen"]["configured"] is True
    assert runtime.provider_settings("qwen")["api_key"] == secret
    assert runtime.update_provider("qwen", {"clear_api_key": True})["providers"]["qwen"]["configured"] is False
    assert runtime.provider_settings("qwen")["api_key"] == ""


@pytest.mark.parametrize("changes", [{"base_url": None}, {"api_key": None}, {"model": None},
                                    {"base_url": "https://qwen.example:invalid/v1"},
                                    {"base_url": "https://qwen.example:0/v1"},
                                    {"base_url": "https://@qwen.example/v1"}])
def test_invalid_or_null_provider_fields_fail_cleanly(changes):
    with pytest.raises(ValueError):
        runtime.update_provider("qwen", changes)
    assert runtime.configuration()["providers"]["qwen"]["configured"] is False


@pytest.mark.parametrize("new_url", ["https://another-provider.example/v1", "https://qwen.example:8443/v1"])
def test_provider_authority_change_cannot_reuse_saved_key(new_url):
    runtime.update_provider("qwen", {"api_key": "key-for-original-host"})
    with pytest.raises(ValueError, match="requires a new API key"):
        runtime.update_provider("qwen", {"base_url": new_url})
    assert runtime.provider_settings("qwen")["base_url"] == "https://qwen.example/v1"
    assert runtime.provider_settings("qwen")["api_key"] == "key-for-original-host"
    runtime.update_provider("qwen", {"base_url": new_url, "api_key": "key-for-new-host"})
    assert runtime.provider_settings("qwen")["base_url"] == new_url
    assert runtime.provider_settings("qwen")["api_key"] == "key-for-new-host"


def test_provider_authority_change_requires_action_for_environment_key(isolated_settings):
    isolated_settings.qwen_api_key = "environment-secret"
    with pytest.raises(ValueError, match="requires a new API key"):
        runtime.update_provider("qwen", {"base_url": "https://new.example/v1"})
    runtime.update_provider("qwen", {"base_url": "https://new.example/v1", "clear_api_key": True})
    assert runtime.provider_settings("qwen")["api_key"] == ""


def test_same_provider_authority_may_retain_saved_key():
    runtime.update_provider("qwen", {"api_key": "same-authority-secret"})
    runtime.update_provider("qwen", {"base_url": "https://QWEN.example:443/compatible-mode/v1"})
    assert runtime.provider_settings("qwen")["api_key"] == "same-authority-secret"


@pytest.mark.parametrize("payload", [None, [], "models", {}, {"models": None}, {"models": {}}, {"models": "bad"}])
def test_malformed_local_model_lists_are_handled(monkeypatch, payload):
    monkeypatch.setattr(runtime.httpx, "get", lambda *a, **kw: httpx.Response(
        200, json=payload, request=httpx.Request("GET", runtime.OLLAMA_URL)))
    result = runtime.local_models()
    assert result["running"] is False
    assert result["installed"] == []
    assert len(result["catalog"]) == 3


def test_local_models_filters_bad_rows_and_sizes(monkeypatch):
    payload = {"models": [None, [], {"name": 42}, {"name": ""}, {"name": "qwen3:0.6b", "size": 10},
                          {"name": "local:bad-size", "size": {"bad": 1}}]}
    monkeypatch.setattr(runtime.httpx, "get", lambda *a, **kw: httpx.Response(
        200, json=payload, request=httpx.Request("GET", runtime.OLLAMA_URL)))
    result = runtime.local_models()
    assert result["running"] is True
    assert result["installed"] == [{"name": "qwen3:0.6b", "size_bytes": 10}, {"name": "local:bad-size", "size_bytes": 0}]
    assert result["catalog"][0]["installed"] is True


@pytest.mark.parametrize("url", [
    "http://huggingface.co/file", "https://huggingface.co:444/file",
    "https://huggingface.co:invalid/file", "https://user@huggingface.co/file",
    "https://@huggingface.co/file", "https://huggingface.co/file#fragment",
    "https://huggingface.co.evil.example/file", "https://evil.example/file",
    "https://hf.co/file", "https://huggingface.co./file", "https://huggingface.co/\nfile",
    "https://huggingface.co\\@evil.example/file", "https://huggingface.co/ file",
])
def test_untrusted_download_urls_never_resolve(monkeypatch, url):
    def unexpected_dns(*args, **kwargs):
        pytest.fail("Invalid download URL reached DNS")
    monkeypatch.setattr(runtime.socket, "getaddrinfo", unexpected_dns)
    with pytest.raises(ValueError):
        runtime._download_target(url)


@pytest.mark.parametrize("addresses", [[], dns("127.0.0.1"), dns("169.254.169.254"),
                                      dns("8.8.8.8") + dns("10.0.0.1"), dns("::1")])
def test_download_rejects_private_or_mixed_dns(monkeypatch, addresses):
    monkeypatch.setattr(runtime.socket, "getaddrinfo", lambda *a, **kw: addresses)
    with pytest.raises(ValueError):
        runtime._download_target("https://huggingface.co/file")


def test_download_pins_ipv6_and_keeps_signed_query(monkeypatch):
    monkeypatch.setattr(runtime.socket, "getaddrinfo", lambda *a, **kw: dns("2606:4700:4700::1111"))
    pinned, host = runtime._download_target("https://cas-bridge.xethub.hf.co:443/file?sig=a%2Bb")
    assert pinned == "https://[2606:4700:4700::1111]/file?sig=a%2Bb"
    assert host == "cas-bridge.xethub.hf.co"


def test_download_pins_each_redirect_and_checks_before_import(monkeypatch, isolated_settings):
    spec, data = tiny_spec(monkeypatch)
    resolved, requests = [], []

    def resolve(host, *args, **kwargs):
        resolved.append(host)
        return dns("8.8.8.8" if host == "huggingface.co" else "1.1.1.1")

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            if request.headers["Host"] == "huggingface.co":
                assert request.url.host == "8.8.8.8"
                assert request.extensions["sni_hostname"] == "huggingface.co"
                return httpx.Response(302, headers={"Location": "https://cdn-lfs.hf.co/file?signature=kept"})
            assert request.url.host == "1.1.1.1"
            assert request.headers["Host"] == "cdn-lfs.hf.co"
            assert request.extensions["sni_hostname"] == "cdn-lfs.hf.co"
            assert request.url.query == b"signature=kept"
            return httpx.Response(200, content=data)
        if "/api/blobs/" in request.url.path:
            assert request.read() == data
            assert request.headers["Content-Length"] == str(len(data))
            assert request.url.path.endswith(spec["sha256"])
            return httpx.Response(201)
        assert request.url.path == "/api/create"
        assert json.loads(request.read())["stream"] is True
        return httpx.Response(200, content=b'{"status":"success"}\n')

    monkeypatch.setattr(runtime.socket, "getaddrinfo", resolve)
    clients = mock_clients(monkeypatch, respond)
    current = job()
    runtime._run_download(current)
    assert current.status == "completed"
    assert current.progress == 1
    assert resolved == ["huggingface.co", "cdn-lfs.hf.co"]
    assert len(requests) == 4 and len(clients) == 2
    assert list((isolated_settings.data_dir / "model-downloads").iterdir()) == []


def test_redirect_rechecks_dns_and_blocks_rebinding(monkeypatch, isolated_settings):
    tiny_spec(monkeypatch)
    answers = iter([dns("8.8.8.8"), dns("127.0.0.1")])
    monkeypatch.setattr(runtime.socket, "getaddrinfo", lambda *a, **kw: next(answers))
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == "8.8.8.8"
        return httpx.Response(302, headers={"Location": "/other-file"})

    mock_clients(monkeypatch, respond)
    current = job()
    runtime._run_download(current)
    assert current.status == "failed"
    assert len(requests) == 1
    assert list((isolated_settings.data_dir / "model-downloads").iterdir()) == []


@pytest.mark.parametrize("response_body", [b"", b"x" * len(b"tiny gguf test data"), b"overlong model bytes" * 10])
def test_checksum_or_size_failure_never_imports(monkeypatch, isolated_settings, response_body):
    tiny_spec(monkeypatch)
    monkeypatch.setattr(runtime.socket, "getaddrinfo", lambda *a, **kw: dns("8.8.8.8"))
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(200, content=response_body)

    mock_clients(monkeypatch, respond)
    current = job()
    runtime._run_download(current)
    assert current.status == "failed" and current.error
    assert len(requests) == 1
    assert list((isolated_settings.data_dir / "model-downloads").iterdir()) == []


@pytest.mark.parametrize("location, expected_requests", [(None, 1), ("https://evil.example/file", 1), ("/loop", 5)])
def test_invalid_or_excessive_redirects_fail_closed(monkeypatch, location, expected_requests):
    tiny_spec(monkeypatch)
    monkeypatch.setattr(runtime.socket, "getaddrinfo", lambda *a, **kw: dns("8.8.8.8"))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": location} if location is not None else {})

    mock_clients(monkeypatch, respond)
    current = job()
    runtime._run_download(current)
    assert current.status == "failed"
    assert len(requests) == expected_requests


def test_cancel_before_start_makes_no_request(monkeypatch):
    monkeypatch.setattr(runtime, "_gguf_pull", lambda *a: pytest.fail("Cancelled job performed network work"))
    current = job()
    current.cancel.set()
    runtime._run_download(current)
    assert current.status == "cancelled" and not current.error


@pytest.mark.parametrize("phase", ["download", "upload"])
def test_cancel_cleans_file_and_never_creates_model(monkeypatch, isolated_settings, phase):
    _, data = tiny_spec(monkeypatch)
    monkeypatch.setattr(runtime.socket, "getaddrinfo", lambda *a, **kw: dns("8.8.8.8"))
    current = job()

    class CancelStream(httpx.SyncByteStream):
        def __iter__(self):
            current.cancel.set()
            yield data

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, stream=CancelStream()) if phase == "download" else httpx.Response(200, content=data)
        assert "/api/blobs/" in request.url.path
        current.cancel.set()
        request.read()
        return httpx.Response(201)

    mock_clients(monkeypatch, respond)
    runtime._run_download(current)
    assert current.status == "cancelled" and not current.error
    assert list((isolated_settings.data_dir / "model-downloads").iterdir()) == []


def test_cancel_during_network_error_stays_cancelled(monkeypatch):
    def disconnect(current):
        current.cancel.set()
        raise httpx.ReadTimeout("private diagnostic URL")
    monkeypatch.setattr(runtime, "_gguf_pull", disconnect)
    current = job()
    runtime._run_download(current)
    assert current.status == "cancelled" and not current.error


@pytest.mark.parametrize("events", [b"", b'{"status":"downloading","total":100,"completed":50}\n',
                                    b'[]\n', b'{"error":"private service details"}\n'])
def test_ollama_partial_or_error_stream_is_not_success(monkeypatch, events):
    mock_clients(monkeypatch, lambda request: httpx.Response(200, content=events))
    current = runtime.DownloadJob("test-pull", "qwen3:0.6b", "ollama")
    runtime._run_download(current)
    assert current.status == "failed"
    assert "private service details" not in current.error


def test_ollama_success_stream_completes(monkeypatch):
    mock_clients(monkeypatch, lambda request: httpx.Response(
        200, content=b'{"status":"downloading","total":100,"completed":50}\n{"status":"success"}\n'))
    current = runtime.DownloadJob("test-pull", "qwen3:0.6b", "ollama")
    runtime._run_download(current)
    assert current.status == "completed" and current.progress == 1
