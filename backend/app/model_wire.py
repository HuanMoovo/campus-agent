"""Choose protocol, authentication and payload without performing HTTP."""
from dataclasses import dataclass
from urllib.parse import quote

from . import model_protocol, model_responses, model_anthropic, model_gemini
from .provider_catalog import CLOUD_PROTOCOLS, PROVIDERS
from .model_reasoning import REASONING_LEVELS, reasoning_capability, validate_reasoning_effort


@dataclass
class ModelRequest:
    protocol: str
    url: str
    headers: dict
    body: dict


def resolve_protocol(provider, protocol=None):
    if provider == "ollama":
        if protocol not in (None, "ollama"):
            raise ValueError("Local model protocol is fixed")
        return "ollama"
    value = protocol or PROVIDERS.get(provider, {}).get("protocol", "chat_completions")
    if value not in CLOUD_PROTOCOLS:
        raise ValueError("Unknown model protocol")
    return value


def _module(protocol):
    return {"responses": model_responses, "anthropic": model_anthropic,
            "gemini": model_gemini}.get(protocol, model_protocol)


def build_request(selected, messages, *, protocol=None, stream=False, tools=None,
                  reasoning=None, request_options=None, max_tokens=None):
    provider, key, base, model = selected
    protocol = resolve_protocol(provider, protocol)
    options = model_protocol.normalize_request_options(request_options)
    validate_reasoning_effort(reasoning, provider, model, protocol, base, options)
    limit = options["max_output_tokens"] if max_tokens is None else max_tokens
    arguments = dict(stream=stream, tools=tools, reasoning=reasoning,
                     request_options=options, max_tokens=limit)
    module = _module(protocol)
    body = (module.build_body(provider, model, messages, **arguments) if module is model_protocol
            else module.build_body(model, messages, **arguments))
    if reasoning in REASONING_LEVELS:
        if protocol == "responses":
            body["reasoning"] = {"effort": reasoning}
        else:
            body["reasoning_effort"] = reasoning
    base = base.rstrip("/")
    if protocol == "ollama":
        url, headers = "http://127.0.0.1:11434/api/chat", {}
    elif protocol == "anthropic":
        url = base + "/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif protocol == "gemini":
        model_id = model[7:] if model.startswith("models/") else model
        url = base + "/models/" + quote(model_id, safe="")
        url += ":streamGenerateContent?alt=sse" if stream else ":generateContent"
        headers = {"x-goog-api-key": key}
    else:
        url = base + ("/responses" if protocol == "responses" else "/chat/completions")
        if protocol == "chat_completions" and PROVIDERS.get(provider, {}).get("auth_header") == "api-key":
            headers = {"api-key": key}
        else:
            headers = {"Authorization": "Bearer " + key}
    return ModelRequest(protocol, url, headers, body)


def parse_completion(payload, provider, protocol=None):
    protocol = resolve_protocol(provider, protocol)
    module = _module(protocol)
    return (module.parse_completion(payload, provider) if module is model_protocol
            else module.parse_completion(payload))


def stream_parser(provider, protocol=None):
    protocol = resolve_protocol(provider, protocol)
    module = _module(protocol)
    return module.StreamParser(provider) if module is model_protocol else module.StreamParser()
