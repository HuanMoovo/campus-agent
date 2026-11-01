"""Reported provider counters stay distinct from missing/estimated consumption."""
import asyncio
import importlib
import importlib.util

import pytest


FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
          "cache_creation_input_tokens", "reasoning_tokens")


def usage_module():
    assert importlib.util.find_spec("app.model_usage") is not None, "provider usage collector is missing"
    return importlib.import_module("app.model_usage")


@pytest.mark.parametrize("protocol,payload,expected", [
    ("chat_completions", {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
       "prompt_tokens_details": {"cached_tokens": 30}, "completion_tokens_details": {"reasoning_tokens": 5}}},
       {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "cached_input_tokens": 30, "reasoning_tokens": 5}),
    ("responses", {"usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
       "input_tokens_details": {"cached_tokens": 30}, "output_tokens_details": {"reasoning_tokens": 5}}},
       {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "cached_input_tokens": 30, "reasoning_tokens": 5}),
    ("anthropic", {"usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
       "cache_creation_input_tokens": 40}},
       {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100, "cached_input_tokens": 30,
        "cache_creation_input_tokens": 40}),
    ("gemini", {"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20,
       "thoughtsTokenCount": 5, "cachedContentTokenCount": 30, "totalTokenCount": 140}},
       {"input_tokens": 100, "output_tokens": 25, "total_tokens": 140, "cached_input_tokens": 30,
        "reasoning_tokens": 5}),
    ("ollama", {"prompt_eval_count": 100, "eval_count": 20},
       {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}),
])
def test_protocol_counts_preserve_subsets_and_protocol_specific_totals(protocol, payload, expected):
    result = usage_module().normalize_usage(payload, protocol)
    assert result == {name: expected.get(name) for name in FIELDS}


@pytest.mark.parametrize("payload", [None, {}, {"usage": None}, {"usage": {}},
    {"usage": {"prompt_tokens": True, "completion_tokens": "3", "total_tokens": -1}},
    {"usage": {"prompt_tokens": 2**53, "completion_tokens": 1.1, "total_tokens": float("inf")}}])
def test_missing_or_invalid_counts_are_unknown_never_fake_zero(payload):
    assert usage_module().normalize_usage(payload, "chat_completions") == dict.fromkeys(FIELDS)


def test_zero_is_a_reported_count_and_total_only_is_preserved():
    module = usage_module()
    assert module.normalize_usage({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}, "chat_completions")["total_tokens"] == 0
    assert module.normalize_usage({"usage": {"total_tokens": 12}}, "chat_completions") == {
        **dict.fromkeys(FIELDS), "total_tokens": 12}


def test_anthropic_and_gemini_missing_components_do_not_invent_visible_output():
    module = usage_module()
    assert module.normalize_usage({"usage": {"cache_read_input_tokens": 8}}, "anthropic")["input_tokens"] is None
    result = module.normalize_usage({"usageMetadata": {"promptTokenCount": 8, "thoughtsTokenCount": 3}}, "gemini")
    assert result["reasoning_tokens"] == 3 and result["output_tokens"] is None and result["total_tokens"] is None


def test_usage_context_is_nested_scoped_and_safe_if_sink_fails():
    module = usage_module()
    outer, inner = [], []
    with module.track_usage(outer.append):
        with module.usage_attempt("qwen", "model", "chat_completions") as attempt:
            attempt.completed = True
        with module.track_usage(inner.append):
            with module.usage_attempt("gemini", "model", "gemini") as attempt:
                attempt.completed = True
        with module.usage_attempt("qwen", "model", "chat_completions"):
            pass
    with module.usage_attempt("qwen", "model", "chat_completions"):
        pass
    assert [item["status"] for item in outer] == ["completed", "failed"]
    assert len(inner) == 1 and inner[0]["provider"] == "gemini"
    def broken_sink(event):
        raise OSError("synthetic storage failure")
    with module.track_usage(broken_sink), module.usage_attempt("qwen", "model", "chat_completions") as attempt:
        attempt.completed = True


def test_async_contexts_and_copied_worker_context_do_not_mix_sinks():
    module = usage_module()
    first, second = [], []
    def record(provider):
        with module.usage_attempt(provider, "model", "chat_completions") as attempt:
            attempt.completed = True
    async def collect(provider, sink):
        with module.track_usage(sink.append):
            await asyncio.sleep(0)
            await asyncio.to_thread(record, provider)
    async def run():
        await asyncio.gather(collect("qwen", first), collect("deepseek", second))
    asyncio.run(run())
    assert [event["provider"] for event in first] == ["qwen"]
    assert [event["provider"] for event in second] == ["deepseek"]
