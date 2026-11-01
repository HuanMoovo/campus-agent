"""Pure OpenAI Responses wire adapter; no credentials, configuration, or HTTP.

Contracts follow the official Responses migration and streaming references:
https://developers.openai.com/api/docs/guides/migrate-to-responses
https://developers.openai.com/api/reference/resources/responses/streaming-events
"""
from __future__ import annotations

import copy
import json

from .model_protocol import ProtocolError, normalize_request_options, upstream_error_code
from .model_usage import UsageSnapshot


def build_body(model, messages, *, stream=False, tools=None, reasoning=None,
               request_options=None, max_tokens=900) -> dict:
    options = normalize_request_options(request_options)
    if not isinstance(messages, list):
        raise ValueError("Unsupported Responses history")
    history = []
    for message in messages:
        if (not isinstance(message, dict) or set(message) - {"role", "content"}
                or message.get("role") not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)):
            raise ValueError("Unsupported Responses history")
        history.append({"role": message["role"], "content": message["content"]})
    body = {"model": model, "input": history, "store": False,
            "max_output_tokens": max_tokens}
    if stream:
        body["stream"] = True
    if options["send_temperature"]:
        body["temperature"] = 0.2
    if reasoning == "deep":
        body["reasoning"] = {"effort": "high", "summary": "auto"}
    if tools and options["supports_tools"]:
        if not isinstance(tools, list):
            raise ValueError("Unsupported Responses tools")
        converted = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if (not isinstance(function, dict) or tool.get("type") != "function"
                    or not isinstance(function.get("name"), str) or not function["name"]
                    or not isinstance(function.get("parameters", {}), dict)
                    or set(function) - {"name", "description", "parameters", "strict"}
                    or ("description" in function and not isinstance(function["description"], str))
                    or ("strict" in function and type(function["strict"]) is not bool)):
                raise ValueError("Unsupported Responses tools")
            converted.append({"type": "function", "strict": False, **copy.deepcopy(function)})
        body.update(tools=converted, tool_choice="auto")
    return body


def _validate_status(payload):
    if not isinstance(payload, dict):
        raise ProtocolError()
    if payload.get("error"):
        raise ProtocolError(upstream_error_code(payload))
    status = payload.get("status")
    if status is None:
        raise ProtocolError()
    if status != "completed" or payload.get("incomplete_details"):
        raise ProtocolError("incomplete_response")


def _function_call(item):
    if (not isinstance(item.get("call_id"), str) or not item["call_id"]
            or not isinstance(item.get("name"), str) or not item["name"]
            or not isinstance(item.get("arguments"), str)):
        raise ProtocolError()
    try:
        arguments = json.loads(item["arguments"], parse_constant=_invalid_json_constant)
    except (ValueError, TypeError) as exc:
        raise ProtocolError() from exc
    if not isinstance(arguments, dict):
        raise ProtocolError()
    return {"id": item["call_id"], "type": "function",
            "function": {"name": item["name"], "arguments": item["arguments"]}}


def _invalid_json_constant(value):
    raise ValueError("Invalid JSON constant")


def parse_completion(payload) -> dict:
    _validate_status(payload)
    output = payload.get("output")
    if not isinstance(output, list):
        raise ProtocolError()
    texts, calls = [], []
    for item in output:
        if not isinstance(item, dict):
            raise ProtocolError()
        if item.get("status") not in (None, "completed"):
            raise ProtocolError("incomplete_response")
        kind = item.get("type")
        if kind == "reasoning":
            continue
        if kind == "function_call":
            calls.append(_function_call(item))
            continue
        if kind != "message" or item.get("role") != "assistant" or not isinstance(item.get("content"), list):
            raise ProtocolError()
        for part in item["content"]:
            if (not isinstance(part, dict) or part.get("type") != "output_text"
                    or not isinstance(part.get("text"), str)):
                raise ProtocolError()
            texts.append(part["text"])
    text = "".join(texts)
    if not text.strip() and not calls:
        raise ProtocolError()
    message = {"role": "assistant", "content": text if texts else None}
    if calls:
        message["tool_calls"] = calls
    return message


class StreamParser:
    """Consume one SSE line at a time; only a validated terminal proves success.

    Tool argument events are ignored: production tool planning uses the
    non-streaming adapter. A tool-only stream cannot complete a text answer.
    """

    def __init__(self):
        self.done = False
        self._error = None
        self._text = ""
        self._usage = UsageSnapshot("responses")

    @property
    def usage(self):
        return self._usage.counters

    def feed(self, line):
        if self._error is not None:
            raise ProtocolError(self._error)
        if self.done:
            return
        try:
            yield from self._feed(line)
        except ProtocolError as exc:
            self._error = exc.error_code
            raise

    def _feed(self, line):
        if not isinstance(line, str):
            raise ProtocolError()
        if not line.startswith("data:"):
            return
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except (ValueError, TypeError) as exc:
            raise ProtocolError() from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
            raise ProtocolError()
        kind = payload["type"]
        if isinstance(payload.get("response"), dict):
            self._usage.observe(payload["response"])
        if kind == "error":
            raise ProtocolError(upstream_error_code({"error": payload}))
        if payload.get("error"):
            raise ProtocolError(upstream_error_code(payload))
        if kind in ("response.failed", "response.incomplete"):
            response = payload.get("response")
            if isinstance(response, dict) and response.get("error"):
                raise ProtocolError(upstream_error_code(response))
            raise ProtocolError("incomplete_response" if kind == "response.incomplete" else "upstream_error")
        if kind in ("response.refusal.delta", "response.refusal.done"):
            raise ProtocolError()
        if kind in ("response.output_text.delta", "response.reasoning_summary_text.delta"):
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise ProtocolError()
            if delta:
                if kind == "response.output_text.delta":
                    self._text += delta
                    yield "content", delta
                else:
                    yield "thinking", delta
        elif kind == "response.completed":
            message = parse_completion(payload.get("response"))
            text = message["content"]
            if not isinstance(text, str) or not text.strip():
                raise ProtocolError()
            # A full terminal response can recover a stream with no text deltas.
            # Once deltas were emitted, a mismatch means lost/corrupt content.
            if self._text and self._text != text:
                raise ProtocolError("incomplete_response")
            if not self._text:
                self._text = text
                yield "content", text
            self.done = True

    def finish(self):
        if self._error is not None:
            raise ProtocolError(self._error)
        if not self.done:
            raise ProtocolError("incomplete_response")
