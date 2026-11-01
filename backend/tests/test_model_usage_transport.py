"""Offline HTTP accounting: no provider or actual user data is accessed."""
import asyncio
import importlib
import importlib.util
import json

import httpx
import pytest

from app import model_client
from app.model_protocol import ModelStreamError, normalize_request_options
from app.model_wire import build_request


SELECTED = ("openai_compatible", "synthetic-private-key", "https://models.invalid/private/v1", "model")
MESSAGES = [{"role": "user", "content": "synthetic private prompt"}]


def tracker(sink):
    assert importlib.util.find_spec("app.model_usage") is not None, "transport usage collector is missing"
    return importlib.import_module("app.model_usage").track_usage(sink)


def install(monkeypatch, handler, asynchronous=False):
    name = "AsyncClient" if asynchronous else "Client"
    real = getattr(httpx, name)
    monkeypatch.setattr(httpx, name, lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def frame(payload):
    return "data: " + json.dumps(payload) + "\n\n"


def delta(text="", finish=None):
    return frame({"choices": [{"delta": {"content": text}, "finish_reason": finish}]})


def collect(**kwargs):
    async def run():
        return [item async for item in model_client.stream(SELECTED, MESSAGES, **kwargs)]
    return asyncio.run(run())


@pytest.mark.parametrize("usage", [{"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}, None])
def test_sync_completion_records_one_safe_event_and_unchanged_answer(monkeypatch, usage):
    payload = {"choices": [{"message": {"content": "answer"}}], "usage": usage, "model": "untrusted-payload-id"}
    install(monkeypatch, lambda request: httpx.Response(200, json=payload))
    events = []
    with tracker(events.append):
        assert model_client.complete(SELECTED, MESSAGES) == {"content": "answer"}
    assert len(events) == 1 and events[0]["status"] == "completed"
    assert events[0]["provider"] == "openai_compatible" and events[0]["model"] == "model"
    assert events[0]["total_tokens"] == (13 if usage else None)
    assert not any(secret in json.dumps(events) for secret in (SELECTED[1], SELECTED[2], MESSAGES[0]["content"]))


def test_stream_usage_opt_in_is_explicit_and_chat_only():
    assert "stream_options" not in build_request(SELECTED, MESSAGES, stream=True).body
    assert build_request(SELECTED, MESSAGES, stream=True, request_options={"stream_usage": True}).body["stream_options"] == {"include_usage": True}
    assert "stream_options" not in build_request(SELECTED, MESSAGES, stream=False, request_options={"stream_usage": True}).body
    assert "stream_options" not in build_request(SELECTED, MESSAGES, stream=True, protocol="responses", request_options={"stream_usage": True}).body
    for value in (None, 1, "true"):
        with pytest.raises(ValueError):
            normalize_request_options({"stream_usage": value})


def test_usage_after_finish_and_repeated_snapshots_replace_not_sum(monkeypatch):
    text = delta("answer") + frame({"choices": [], "usage": {"total_tokens": 9}}) + delta(finish="stop")
    text += frame({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}) * 2
    text += "data: [DONE]\n\n"
    install(monkeypatch, lambda request: httpx.Response(200, text=text), True)
    events = []
    with tracker(events.append):
        assert collect() == [("content", "answer")]
    assert len(events) == 1 and events[0]["total_tokens"] == 13 and events[0]["status"] == "completed"


@pytest.mark.parametrize("ending", [delta(finish="stop"), "data: [DONE]\n\n"])
def test_valid_stream_without_usage_reports_unknown_counts(monkeypatch, ending):
    install(monkeypatch, lambda request: httpx.Response(200, text=delta("answer") + ending), True)
    events = []
    with tracker(events.append):
        assert collect() == [("content", "answer")]
    assert events[0]["status"] == "completed" and events[0]["total_tokens"] is None


@pytest.mark.parametrize("ending", ["", delta(finish="length"), "data: malformed\n\n"])
def test_partial_failed_stream_preserves_content_and_records_failure(monkeypatch, ending):
    install(monkeypatch, lambda request: httpx.Response(200, text=delta("partial") + ending), True)
    events, chunks = [], []
    async def run():
        with tracker(events.append):
            with pytest.raises(ModelStreamError):
                async for item in model_client.stream(SELECTED, MESSAGES):
                    chunks.append(item)
    asyncio.run(run())
    assert chunks == [("content", "partial")]
    assert len(events) == 1 and events[0]["status"] == "failed" and events[0]["total_tokens"] is None


def test_disabled_streaming_records_nonstream_usage(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3}}), True)
    events = []
    with tracker(events.append):
        assert collect(request_options={"supports_streaming": False}) == [("content", "answer")]
    assert len(events) == 1 and events[0]["total_tokens"] == 13


@pytest.mark.parametrize("asynchronous", [False, True])
def test_ollama_retry_counts_two_actual_attempts(monkeypatch, asynchronous):
    def respond(request):
        body = json.loads(request.content)
        if body.get("think"):
            return httpx.Response(400, json={"error": "unsupported thinking"})
        payload = {"message": {"content": "answer"}, "done": True, "prompt_eval_count": 10, "eval_count": 3}
        return httpx.Response(200, text=json.dumps(payload) + "\n") if asynchronous else httpx.Response(200, json=payload)
    install(monkeypatch, respond, asynchronous)
    events = []
    selected = ("ollama", "", "https://ignored.invalid/v1", "local-model")
    async def run():
        return [item async for item in model_client.stream(selected, MESSAGES, reasoning="deep")]
    with tracker(events.append):
        answer = asyncio.run(run()) if asynchronous else model_client.complete(selected, MESSAGES, reasoning="deep")
    assert answer == ([("content", "answer")] if asynchronous else {"content": "answer"})
    assert [item["status"] for item in events] == ["failed", "completed"]
    assert [item["total_tokens"] for item in events] == [None, 13]


def test_skipped_requests_do_not_record_attempts(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("no HTTP"))
    events = []
    with tracker(events.append):
        assert model_client.complete(None, MESSAGES) is None
        assert model_client.complete(SELECTED, MESSAGES, tools=[{}], request_options={"supports_tools": False}) is None
    assert events == []


def test_closing_stream_after_one_chunk_records_cancelled(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, text=delta("first") + delta("second") + delta(finish="stop")), True)
    events = []
    async def run():
        with tracker(events.append):
            iterator = model_client.stream(SELECTED, MESSAGES)
            assert await anext(iterator) == ("content", "first")
            await iterator.aclose()
    asyncio.run(run())
    assert len(events) == 1 and events[0]["status"] == "cancelled" and events[0]["total_tokens"] is None


def native_payload(protocol):
    if protocol == "responses":
        return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "answer"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}}
    if protocol == "anthropic":
        return {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "answer"}],
            "usage": {"input_tokens": 2, "cache_read_input_tokens": 4, "cache_creation_input_tokens": 4, "output_tokens": 3}}
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": "answer"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2, "thoughtsTokenCount": 1, "totalTokenCount": 13}}


@pytest.mark.parametrize("protocol", ["responses", "anthropic", "gemini"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_native_nonstream_usage_uses_protocol_counts_not_text_length(monkeypatch, protocol, asynchronous):
    install(monkeypatch, lambda request: httpx.Response(200, json=native_payload(protocol)), asynchronous)
    events = []
    with tracker(events.append):
        answer = collect(protocol=protocol, request_options={"supports_streaming": False}) if asynchronous else model_client.complete(
            SELECTED, MESSAGES, protocol=protocol)
    assert answer == ([("content", "answer")] if asynchronous else {"role": "assistant", "content": "answer"})
    assert len(events) == 1 and events[0]["protocol"] == protocol and events[0]["status"] == "completed"
    assert events[0]["input_tokens"] == 10 and events[0]["output_tokens"] == 3 and events[0]["total_tokens"] == 13


@pytest.mark.parametrize("protocol", ["responses", "anthropic", "gemini"])
def test_native_stream_usage_preserves_start_and_final_snapshot_without_changing_chunks(monkeypatch, protocol):
    if protocol == "responses":
        text = frame({"type": "response.output_text.delta", "delta": "answer"})
        text += frame({"type": "response.completed", "response": native_payload(protocol)})
    elif protocol == "anthropic":
        text = frame({"type": "message_start", "message": {"role": "assistant", "content": [],
            "usage": {"input_tokens": 2, "cache_read_input_tokens": 4, "cache_creation_input_tokens": 4, "output_tokens": 0}}})
        text += frame({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "answer"}})
        text += frame({"type": "content_block_stop", "index": 0})
        text += frame({"type": "message_delta", "delta": {"stop_reason": None}, "usage": {"output_tokens": 1}})
        text += frame({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}})
        text += frame({"type": "message_stop"})
    else:
        payload = native_payload(protocol)
        text = frame({"candidates": [{"content": {"parts": [{"text": "an"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 1, "totalTokenCount": 11}})
        payload["candidates"][0]["content"]["parts"][0]["text"] = "swer"
        text += frame(payload)
    install(monkeypatch, lambda request: httpx.Response(200, text=text), True)
    events = []
    with tracker(events.append):
        chunks = collect(protocol=protocol)
    assert "".join(value for kind, value in chunks if kind == "content") == "answer"
    assert {kind for kind, value in chunks} == {"content"}
    assert len(events) == 1 and events[0]["total_tokens"] == 13
    assert events[0]["input_tokens"] == 10 and events[0]["output_tokens"] == 3


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("status,payload", [(503, {"error": "synthetic upstream error"}),
    (200, {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}})])
def test_actual_http_failure_is_counted_even_without_usable_answer(monkeypatch, asynchronous, status, payload):
    install(monkeypatch, lambda request: httpx.Response(status, json=payload), asynchronous)
    events = []
    with tracker(events.append):
        answer = collect(request_options={"supports_streaming": False}) if asynchronous else model_client.complete(SELECTED, MESSAGES)
    assert answer == ([] if asynchronous else None)
    assert len(events) == 1 and events[0]["status"] == "failed"
    assert events[0]["total_tokens"] == (13 if status == 200 else None)


def test_cancellation_during_network_wait_records_cancelled_once(monkeypatch):
    events = []
    async def run():
        started = asyncio.Event()
        async def respond(request):
            started.set()
            await asyncio.Future()
        install(monkeypatch, respond, True)
        async def consume():
            with tracker(events.append):
                return [item async for item in model_client.stream(SELECTED, MESSAGES)]
        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert len(events) == 1 and events[0]["status"] == "cancelled" and events[0]["total_tokens"] is None


def test_usage_sink_exception_cannot_break_answer(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]}))
    def failed_sink(event):
        raise RuntimeError("synthetic ledger unavailable")
    with tracker(failed_sink):
        assert model_client.complete(SELECTED, MESSAGES) == {"content": "answer"}


def test_selected_legacy_deepseek_rewrites_are_measured_as_actual_model(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]}))
    events = []
    with tracker(events.append):
        model_client.complete(("deepseek", "synthetic", "https://models.invalid/v1", "deepseek-chat"), MESSAGES, reasoning="deep")
    assert events[0]["model"] == "deepseek-reasoner"


@pytest.mark.parametrize("reported", [False, True])
def test_optional_usage_tail_disconnect_does_not_reject_a_completed_answer(monkeypatch, reported):
    class TailDisconnect(httpx.AsyncByteStream):
        async def __aiter__(self):
            text = delta("answer") + delta(finish="stop")
            if reported:
                text += frame({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}})
            yield text.encode()
            raise httpx.ReadError("synthetic tail disconnected")
    install(monkeypatch, lambda request: httpx.Response(200, stream=TailDisconnect()), True)
    events = []
    with tracker(events.append):
        assert collect() == [("content", "answer")]
    assert len(events) == 1 and events[0]["status"] == "completed"
    assert events[0]["total_tokens"] == (13 if reported else None)
