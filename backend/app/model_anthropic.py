"""Pure Anthropic Messages wire adapter; credentials and transport live elsewhere."""
from __future__ import annotations

import json

from .model_protocol import ProtocolError, normalize_request_options, upstream_error_code
from .model_usage import UsageSnapshot


def build_body(model, messages, *, stream=False, tools=None, reasoning=None,
               request_options=None, max_tokens=900) -> dict:
    options = normalize_request_options(request_options)
    if not isinstance(model, str) or not model.strip() or type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("Invalid model or output token limit")
    if type(stream) is not bool:
        raise ValueError("Invalid stream option")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Messages must be a nonempty list")
    history, system = [], []
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message.get("role") not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)):
            raise ValueError("Native Messages requires plain text history")
        if message["role"] == "system":
            system.append(message["content"])
        else:
            history.append(dict(message))
    if not history:
        raise ValueError("Conversation history is required")
    body = {"model": model, "messages": history, "max_tokens": max_tokens}
    if system:
        body["system"] = "\n\n".join(system)
    if stream:
        body["stream"] = True
    if options["send_temperature"]:
        body["temperature"] = 0.2
    # Thinking enablement differs by model. Do not invent a token budget or an
    # adaptive-thinking capability for private deployment names.
    if tools is not None and options["supports_tools"]:
        if not isinstance(tools, list):
            raise ValueError("Tools must be a list")
        native_tools = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if (not isinstance(function, dict) or tool.get("type") != "function"
                    or not isinstance(function.get("name"), str) or not function["name"].strip()
                    or not isinstance(function.get("parameters", {}), dict)
                    or ("description" in function and not isinstance(function["description"], str))):
                raise ValueError("Invalid function tool definition")
            native = {"name": function["name"], "input_schema": function.get("parameters", {"type": "object"})}
            if "description" in function:
                native["description"] = function["description"]
            native_tools.append(native)
        if native_tools:
            if stream:
                raise ValueError("Native tool planning requires a nonstreaming request")
            body.update(tools=native_tools, tool_choice={"type": "auto"})
    return body


def _stop(reason):
    if reason not in ("end_turn", "tool_use"):
        raise ProtocolError("incomplete_response")


def _text(value):
    if not isinstance(value, str):
        raise ProtocolError()
    return value


def _tool(block):
    name, call_id, args = block.get("name"), block.get("id"), block.get("input")
    if not isinstance(name, str) or not name.strip() or not isinstance(call_id, str) or not call_id.strip() or not isinstance(args, dict):
        raise ProtocolError()
    try:
        arguments = json.dumps(args, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ProtocolError() from exc
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def parse_completion(payload) -> dict:
    if not isinstance(payload, dict):
        raise ProtocolError()
    if "error" in payload:
        raise ProtocolError(upstream_error_code(payload))
    _stop(payload.get("stop_reason"))
    if payload.get("role", "assistant") != "assistant" or payload.get("type", "message") != "message":
        raise ProtocolError()
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        raise ProtocolError()
    text, calls = [], []
    for block in blocks:
        if not isinstance(block, dict):
            raise ProtocolError()
        kind = block.get("type")
        if kind == "text":
            text.append(_text(block.get("text")))
        elif kind == "tool_use":
            calls.append(_tool(block))
        elif kind == "thinking":
            _text(block.get("thinking"))
        elif kind == "redacted_thinking":
            _text(block.get("data"))
        else:
            raise ProtocolError()
    content = "".join(text)
    if (payload["stop_reason"] == "tool_use") != bool(calls):
        raise ProtocolError()
    if not content.strip() and not calls:
        raise ProtocolError()
    result = {"role": "assistant", "content": content or None}
    if calls:
        result["tool_calls"] = calls
    return result


class StreamParser:
    """Messages SSE requires a normal stop reason *and* message_stop."""

    def __init__(self):
        self.done = False
        self._started = False
        self._blocks = {}
        self._stopped = set()
        self._stop_reason = None
        self._has_text = False
        self._usage = UsageSnapshot("anthropic")

    @property
    def usage(self):
        return self._usage.counters

    def feed(self, line):
        if self.done or not line.strip() or not line.startswith("data:"):
            return
        try:
            payload = json.loads(line[5:].strip())
        except (ValueError, TypeError) as exc:
            raise ProtocolError() from exc
        if not isinstance(payload, dict):
            raise ProtocolError()
        self._usage.observe(payload)
        if "error" in payload or payload.get("type") == "error":
            raise ProtocolError(upstream_error_code(payload))
        kind = payload.get("type")
        if not isinstance(kind, str):
            raise ProtocolError()
        if kind == "ping":
            return
        if kind == "message_start":
            message = payload.get("message")
            if (self._started or not isinstance(message, dict)
                    or message.get("role") != "assistant" or message.get("content") != []):
                raise ProtocolError()
            self._started = True
            self._usage.observe(message)
            return
        if not self._started:
            raise ProtocolError()
        if kind in ("content_block_start", "content_block_delta", "content_block_stop"):
            index = payload.get("index")
            if type(index) is not int or index < 0 or self._stop_reason is not None:
                raise ProtocolError()
            if kind == "content_block_start":
                block = payload.get("content_block")
                if index in self._blocks or not isinstance(block, dict):
                    raise ProtocolError()
                block_type = block.get("type")
                if block_type not in ("text", "thinking", "redacted_thinking"):
                    # Tool planning is nonstreaming, so an unexpected tool call
                    # cannot be silently discarded as a successful answer.
                    raise ProtocolError()
                self._blocks[index] = block_type
                if block_type == "redacted_thinking":
                    _text(block.get("data"))
                    return
                key = "text" if block_type == "text" else "thinking"
                value = _text(block.get(key))
                if value:
                    self._has_text |= block_type == "text" and bool(value.strip())
                    yield "content" if block_type == "text" else "thinking", value
            elif kind == "content_block_stop":
                if index not in self._blocks or index in self._stopped:
                    raise ProtocolError()
                self._stopped.add(index)
            else:
                delta = payload.get("delta")
                if index not in self._blocks or index in self._stopped or not isinstance(delta, dict):
                    raise ProtocolError()
                delta_type, block_type = delta.get("type"), self._blocks[index]
                if delta_type == "signature_delta" and block_type == "thinking":
                    _text(delta.get("signature"))
                    return
                if delta_type == "text_delta" and block_type == "text":
                    value = _text(delta.get("text"))
                    if value:
                        self._has_text |= bool(value.strip())
                        yield "content", value
                elif delta_type == "thinking_delta" and block_type == "thinking":
                    value = _text(delta.get("thinking"))
                    if value:
                        yield "thinking", value
                else:
                    raise ProtocolError()
        elif kind == "message_delta":
            delta = payload.get("delta")
            if not isinstance(delta, dict):
                raise ProtocolError()
            reason = delta.get("stop_reason")
            if reason is not None:
                if reason != "end_turn":
                    raise ProtocolError("incomplete_response")
                self._stop_reason = reason
        elif kind == "message_stop":
            if (self._stop_reason != "end_turn" or set(self._blocks) != self._stopped
                    or not self._has_text):
                raise ProtocolError("incomplete_response")
            self.done = True
        # Anthropic documents that new event types may appear. Unknown event
        # metadata is harmless; unknown content blocks above remain an error.

    def finish(self):
        if not self.done:
            raise ProtocolError("incomplete_response")
