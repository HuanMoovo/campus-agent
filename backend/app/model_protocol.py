"""Pure model protocol rules; no configuration, credentials, or HTTP side effects."""
from __future__ import annotations

import json

from .model_reasoning import REASONING_LEVELS, normalize_reasoning_efforts
from .model_usage import UsageSnapshot


class ModelStreamError(RuntimeError):
    """A cloud stream failed after delivering content or reasoning."""


class ProtocolError(ValueError):
    """A safe error category, independent of private upstream error messages."""

    def __init__(self, error_code="invalid_response"):
        super().__init__(error_code)
        self.error_code = error_code


def normalize_request_options(value=None) -> dict:
    defaults = {"token_parameter": "max_tokens", "send_temperature": True,
                "supports_tools": True, "supports_streaming": True, "max_output_tokens": 900,
                "reasoning_efforts": None}
    if value is None:
        return defaults
    if not isinstance(value, dict) or set(value) - defaults.keys() - {"stream_usage"}:
        raise ValueError("Invalid model request options")
    for name, option in value.items():
        if name == "reasoning_efforts":
            normalize_reasoning_efforts(option)
        elif name == "token_parameter":
            if option not in ("max_tokens", "max_completion_tokens"):
                raise ValueError("Invalid token parameter")
        elif name == "max_output_tokens":
            if type(option) is not int or not 64 <= option <= 65536:
                raise ValueError("Output limit must be an integer between 64 and 65536")
        elif type(option) is not bool:
            raise ValueError("Model capability options must be booleans")
    return {**defaults, **value}


def build_body(provider, model, messages, *, stream=False, tools=None, reasoning=None,
               request_options=None, max_tokens=900) -> dict:
    options = normalize_request_options(request_options)
    deep = reasoning == "deep"
    # Preserve the historical alias behavior only for that exact legacy ID.
    # Explicit modern models and private deployment names must never be replaced.
    if provider == "deepseek" and deep and model == "deepseek-chat":
        model = "deepseek-reasoner"
    if provider == "ollama":
        body = {"model": model, "messages": messages, "stream": stream, "think": deep,
                "options": {"num_predict": max_tokens}}
        if options["send_temperature"]:
            body["options"]["temperature"] = 0.2
    else:
        body = {"model": model, "messages": messages, options["token_parameter"]: max_tokens}
        if stream:
            body["stream"] = True
            if options.get("stream_usage", False):
                body["stream_options"] = {"include_usage": True}
        if options["send_temperature"] and not (provider == "deepseek" and "reasoner" in model.lower()):
            body["temperature"] = 0.2
        if provider == "qwen" and reasoning not in REASONING_LEVELS:
            body["enable_thinking"] = deep if stream else False
    if tools and options["supports_tools"]:
        body.update(tools=tools, tool_choice="auto")
    return body


def upstream_error_code(payload, status=None) -> str:
    """Inspect only for categorization; callers never display upstream strings."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        labels = " ".join(str(error.get(key, "")) for key in ("code", "type", "message")).lower()
    else:
        labels = str(error or "").lower()
    if status in (401, 403):
        return "authentication"
    if any(word in labels for word in ("insufficient_quota", "quota_exceeded", "insufficient_balance", "余额不足", "额度不足")) or status == 402:
        return "quota_exceeded"
    if status == 429:
        return "rate_limited"
    if status == 404:
        return "not_found"
    if any(word in labels for word in ("unsupported_parameter", "unsupported parameter", "unknown parameter",
                                      "unrecognized request argument", "not supported", "not allowed")):
        return "unsupported_parameter"
    return "upstream_error"


def _finish(reason):
    if reason is not None and reason not in ("stop", "tool_calls"):
        raise ProtocolError("incomplete_response")


def _vendor_error(payload, provider):
    # Spark HTTP endpoints may report application failures inside HTTP 200.
    if provider == "spark" and "code" in payload:
        code = payload["code"]
        if type(code) is not int:
            raise ProtocolError()
        if code != 0:
            raise ProtocolError("upstream_error")


def _validate_message(message):
    if not isinstance(message, dict):
        raise ProtocolError()
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ProtocolError()
    calls = message.get("tool_calls")
    if calls is not None:
        if not isinstance(calls, list):
            raise ProtocolError()
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(function, dict) or not isinstance(function.get("name"), str)
                    or not function["name"] or not isinstance(function.get("arguments"), (str, dict))):
                raise ProtocolError()
    if not (isinstance(content, str) and content.strip()) and not calls:
        raise ProtocolError()
    return message


def parse_completion(payload, provider) -> dict:
    if not isinstance(payload, dict):
        raise ProtocolError()
    _vendor_error(payload, provider)
    if payload.get("error"):
        raise ProtocolError(upstream_error_code(payload))
    try:
        if provider == "ollama":
            _finish(payload.get("done_reason"))
            return _validate_message(payload["message"])
        choices = payload["choices"]
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProtocolError()
        choice = choices[0]
        _finish(choice.get("finish_reason"))
        return _validate_message(choice["message"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ProtocolError() from exc


class StreamParser:
    """Incremental validation shared by async generation and sync diagnostics.

    An abnormal finish is raised on the next advancement after yielding its
    deltas, so the caller can retain the last part of a truncated answer.
    """

    def __init__(self, provider):
        self.provider = provider
        self.done = False
        self._finished = False
        self._usage = UsageSnapshot("ollama" if provider == "ollama" else "chat_completions")

    @property
    def usage(self):
        return self._usage.counters

    def feed(self, line):
        if self.done or not line.strip():
            return
        if self.provider != "ollama":
            if not line.startswith("data:"):
                return
            line = line[5:].strip()
            if line == "[DONE]":
                self.done = True
                return
        try:
            payload = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise ProtocolError() from exc
        if not isinstance(payload, dict):
            raise ProtocolError()
        self._usage.observe(payload)
        _vendor_error(payload, self.provider)
        if payload.get("error"):
            raise ProtocolError(upstream_error_code(payload))
        if self.provider == "ollama":
            message = payload.get("message")
            if message is None and payload.get("done") is True:
                message = {}
            if not isinstance(message, dict):
                raise ProtocolError()
            thinking_key = "thinking"
            final = payload.get("done") is True
            finish_reason = payload.get("done_reason") if final else None
        else:
            choices = payload.get("choices")
            if not isinstance(choices, list):
                raise ProtocolError()
            if not choices and isinstance(payload.get("usage"), dict):
                return
            if not choices or not isinstance(choices[0], dict):
                raise ProtocolError()
            choice = choices[0]
            message = choice.get("delta", {})
            if not isinstance(message, dict):
                raise ProtocolError()
            thinking_key = "reasoning_content"
            finish_reason = choice.get("finish_reason")
            final = finish_reason is not None
        for key, kind in ((thinking_key, "thinking"), ("content", "content")):
            chunk = message.get(key)
            if chunk is not None and not isinstance(chunk, str):
                raise ProtocolError()
            if chunk:
                if self._finished:
                    raise ProtocolError("incomplete_response")
                yield kind, chunk
        if final:
            _finish(finish_reason)
            if self.provider == "ollama":
                self.done = True
            else:
                # A separate usage-only chunk may follow finish_reason. Keep
                # reading until [DONE] or EOF without accepting further text.
                self._finished = True

    def finish(self):
        if self._finished:
            self.done = True
        if not self.done:
            raise ProtocolError("incomplete_response")
