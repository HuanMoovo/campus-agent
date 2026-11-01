"""Request-scoped, content-free accounting of counters reported by providers.

The transport publishes one event per actual HTTP attempt. Counters are not
estimates, and missing counters remain None. Streaming counters are snapshots,
never deltas to add. No credentials, endpoint URLs or prompts enter this module.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Callable


TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
                "cache_creation_input_tokens", "reasoning_tokens")
MAX_COUNTER = 2**53 - 1
_sink: ContextVar[Callable[[dict], None] | None] = ContextVar("model_usage_sink", default=None)


def _object(value):
    return value if isinstance(value, dict) else {}


def _counter(value):
    return value if type(value) is int and 0 <= value <= MAX_COUNTER else None


def _sum(*values):
    return _counter(sum(values)) if all(value is not None for value in values) else None


def _optional_counter(source, name):
    # Omitted cache/thought components denote no such component in these native
    # protocols. An explicitly malformed component is unknown, not zero.
    return _counter(source[name]) if name in source else 0


def normalize_usage(payload, protocol: str) -> dict:
    """Normalize only documented counters; subsets are not added twice.

    Anthropic cache-read/create inputs are additional to its ordinary input.
    Gemini candidates exclude thoughts; totalTokenCount can include other
    provider components, so its reported total is retained independently.
    """
    result = dict.fromkeys(TOKEN_FIELDS)
    payload = _object(payload)
    if protocol == "ollama":
        result["input_tokens"] = _counter(payload.get("prompt_eval_count"))
        result["output_tokens"] = _counter(payload.get("eval_count"))
    elif protocol == "gemini":
        usage = _object(payload.get("usageMetadata"))
        result["input_tokens"] = _counter(usage.get("promptTokenCount"))
        result["output_tokens"] = _sum(_counter(usage.get("candidatesTokenCount")),
                                       _optional_counter(usage, "thoughtsTokenCount"))
        result["total_tokens"] = _counter(usage.get("totalTokenCount"))
        result["cached_input_tokens"] = _counter(usage.get("cachedContentTokenCount"))
        result["reasoning_tokens"] = _counter(usage.get("thoughtsTokenCount"))
    elif protocol == "anthropic":
        usage = _object(payload.get("usage"))
        result["input_tokens"] = _sum(_counter(usage.get("input_tokens")),
                                      _optional_counter(usage, "cache_read_input_tokens"),
                                      _optional_counter(usage, "cache_creation_input_tokens"))
        result["output_tokens"] = _counter(usage.get("output_tokens"))
        result["cached_input_tokens"] = _counter(usage.get("cache_read_input_tokens"))
        result["cache_creation_input_tokens"] = _counter(usage.get("cache_creation_input_tokens"))
    elif protocol in ("chat_completions", "responses"):
        usage = _object(payload.get("usage"))
        input_name, output_name = (("input_tokens", "output_tokens") if protocol == "responses"
                                   else ("prompt_tokens", "completion_tokens"))
        result["input_tokens"] = _counter(usage.get(input_name))
        result["output_tokens"] = _counter(usage.get(output_name))
        result["total_tokens"] = _counter(usage.get("total_tokens"))
        result["cached_input_tokens"] = _counter(_object(usage.get(input_name + "_details")).get("cached_tokens"))
        result["reasoning_tokens"] = _counter(_object(usage.get(output_name + "_details")).get("reasoning_tokens"))
    if protocol != "gemini" and result["total_tokens"] is None:
        result["total_tokens"] = _sum(result["input_tokens"], result["output_tokens"])
    return result


class UsageSnapshot:
    """Keep the latest native usage snapshot, merging Anthropic start/delta.

    Only numeric usage metadata is retained, even if the surrounding response
    has private text. In particular, repeated snapshots are never accumulated.
    """

    def __init__(self, protocol: str):
        self.protocol = protocol
        self.counters = dict.fromkeys(TOKEN_FIELDS)
        self._anthropic = {}

    def observe(self, payload):
        payload = _object(payload)
        if self.protocol == "ollama":
            if not ({"prompt_eval_count", "eval_count"} & payload.keys()):
                return
        elif self.protocol == "gemini":
            if not isinstance(payload.get("usageMetadata"), dict):
                return
        elif not isinstance(payload.get("usage"), dict):
            return
        if self.protocol == "anthropic":
            source = payload["usage"]
            for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                if key in source:
                    self._anthropic[key] = _counter(source[key])
            payload = {"usage": self._anthropic}
        self.counters = normalize_usage(payload, self.protocol)


@contextmanager
def track_usage(sink: Callable[[dict], None]):
    """Install a sink for this request/task and its copied worker contexts."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


class usage_attempt:
    """One transport attempt; cleanup also accounts for async cancellation."""

    def __init__(self, provider: str, model: str, protocol: str):
        self.provider, self.model, self.protocol = provider, model, protocol
        self.sink = _sink.get()
        self.usage = dict.fromkeys(TOKEN_FIELDS)
        self.completed = False

    def __enter__(self):
        return self

    def observe(self, payload):
        self.usage = normalize_usage(payload, self.protocol)

    def __exit__(self, kind, value, traceback):
        cancelled = kind is not None and issubclass(kind, (asyncio.CancelledError, GeneratorExit))
        status = "cancelled" if cancelled else "completed" if kind is None and self.completed else "failed"
        if self.sink is not None:
            event = {"provider": self.provider, "model": self.model, "protocol": self.protocol,
                     "status": status, **self.usage}
            try:
                self.sink(event)
            except Exception:
                # Statistics failure must never replace an answer or its error.
                pass
        return False
