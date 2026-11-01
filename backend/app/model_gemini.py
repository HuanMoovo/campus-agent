"""Pure Gemini generateContent adapter for plaintext history and function plans."""
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
    contents, system = [], []
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message.get("role") not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)):
            raise ValueError("Native Gemini requires plain text history")
        part = {"text": message["content"]}
        if message["role"] == "system":
            system.append(part)
        else:
            contents.append({"role": "model" if message["role"] == "assistant" else "user", "parts": [part]})
    if not contents:
        raise ValueError("Conversation history is required")
    config = {"maxOutputTokens": max_tokens}
    if options["send_temperature"]:
        config["temperature"] = 0.2
    body = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": system}
    # Model-specific thinking settings are deliberately not inferred from names.
    if tools is not None and options["supports_tools"]:
        if not isinstance(tools, list):
            raise ValueError("Tools must be a list")
        functions = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if (not isinstance(function, dict) or tool.get("type") != "function"
                    or not isinstance(function.get("name"), str) or not function["name"].strip()
                    or not isinstance(function.get("parameters", {}), dict)
                    or ("description" in function and not isinstance(function["description"], str))):
                raise ValueError("Invalid function tool definition")
            declaration = {"name": function["name"]}
            if "description" in function:
                declaration["description"] = function["description"]
            if "parameters" in function:
                # Canonical tools use JSON Schema constraints such as
                # additionalProperties, outside Gemini's narrower Schema type.
                # This field accepts JSON Schema and excludes `parameters`.
                declaration["parametersJsonSchema"] = function["parameters"]
            functions.append(declaration)
        if functions:
            if stream:
                raise ValueError("Native tool planning requires a nonstreaming request")
            body.update(tools=[{"functionDeclarations": functions}],
                        toolConfig={"functionCallingConfig": {"mode": "AUTO"}})
    return body


def _candidate(payload):
    if not isinstance(payload, dict):
        raise ProtocolError()
    if "error" in payload:
        raise ProtocolError(upstream_error_code(payload))
    feedback = payload.get("promptFeedback")
    if feedback is not None:
        if not isinstance(feedback, dict):
            raise ProtocolError()
        if feedback.get("blockReason") not in (None, "BLOCK_REASON_UNSPECIFIED"):
            raise ProtocolError("incomplete_response")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise ProtocolError()
    candidate = candidates[0]
    ratings = candidate.get("safetyRatings", [])
    if not isinstance(ratings, list) or any(not isinstance(rating, dict) for rating in ratings):
        raise ProtocolError()
    if any(rating.get("blocked") is True for rating in ratings):
        raise ProtocolError("incomplete_response")
    return candidate


def _parts(candidate, *, allow_missing=False):
    content = candidate.get("content")
    if content is None and allow_missing:
        return []
    if not isinstance(content, dict) or content.get("role", "model") != "model":
        raise ProtocolError()
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ProtocolError()
    for part in parts:
        if not isinstance(part, dict) or type(part.get("thought", False)) is not bool:
            raise ProtocolError()
        # A Part is a union. A text or function call cannot also contain media.
        known_data = {"text", "functionCall", "functionResponse", "inlineData", "fileData",
                      "executableCode", "codeExecutionResult", "toolCall", "toolResponse"}
        fields = set(part) & known_data
        if fields not in ({"text"}, {"functionCall"}):
            raise ProtocolError()
        if "text" in part and not isinstance(part["text"], str):
            raise ProtocolError()
        if "functionCall" in part and part.get("thought", False):
            raise ProtocolError()
    return parts


def _tool(call, index):
    if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not call["name"].strip():
        raise ProtocolError()
    args = call.get("args", {})
    call_id = call.get("id", f"gemini_call_{index}")
    if not isinstance(args, dict) or not isinstance(call_id, str) or not call_id.strip():
        raise ProtocolError()
    try:
        arguments = json.dumps(args, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ProtocolError() from exc
    return {"id": call_id, "type": "function", "function": {"name": call["name"], "arguments": arguments}}


def parse_completion(payload) -> dict:
    candidate = _candidate(payload)
    if candidate.get("finishReason") != "STOP":
        raise ProtocolError("incomplete_response")
    text, calls = [], []
    for part in _parts(candidate):
        if "functionCall" in part:
            calls.append(_tool(part["functionCall"], len(calls)))
        elif not part.get("thought", False):
            text.append(part["text"])
    content = "".join(text)
    if not content.strip() and not calls:
        raise ProtocolError()
    result = {"role": "assistant", "content": content or None}
    if calls:
        result["tool_calls"] = calls
    return result


class StreamParser:
    """Gemini SSE finishes only on STOP, preserving text before truncation."""

    def __init__(self):
        self.done = False
        self._has_text = False
        self._usage = UsageSnapshot("gemini")

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
        candidate = _candidate(payload)
        reason = candidate.get("finishReason")
        for part in _parts(candidate, allow_missing=reason is not None):
            if "functionCall" in part:
                raise ProtocolError()
            value = part["text"]
            if value:
                thought = part.get("thought", False)
                self._has_text |= not thought and bool(value.strip())
                yield "thinking" if thought else "content", value
        if reason is not None:
            if reason != "STOP" or not self._has_text:
                raise ProtocolError("incomplete_response")
            self.done = True

    def finish(self):
        if not self.done:
            raise ProtocolError("incomplete_response")
