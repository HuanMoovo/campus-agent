"""Model HTTP transports and saved-configuration capability diagnostics."""
from __future__ import annotations

import json
import time

import httpx

from .model_protocol import ModelStreamError, ProtocolError, normalize_request_options, upstream_error_code
from .model_reasoning import ReasoningConfigurationError
from .model_wire import build_request, parse_completion, resolve_protocol, stream_parser
from .model_usage import usage_attempt


OLLAMA_URL = "http://127.0.0.1:11434"
_INTERRUPTED = "模型响应中断，已生成的内容可能不完整，请重试。"
_ERRORS = {
    "missing_key": ("请先填写 API Key", "保存 API Key 后重试。"),
    "missing_model": ("请先填写模型名称", "保存服务商支持的模型名称后重试。"),
    "authentication": ("API Key 未通过服务商验证", "检查并重新保存有效的 API Key。"),
    "rate_limited": ("模型服务商请求限流", "稍后重试，或检查服务商的请求速率限制。"),
    "quota_exceeded": ("模型服务商额度不足", "检查服务商账户余额和模型额度。"),
    "not_found": ("模型或 API 地址不存在", "检查 API 地址的路径和模型名称。"),
    "unsupported_parameter": ("模型服务商不接受当前请求参数", "检查兼容选项中的令牌参数、温度及工具支持。"),
    "timeout": ("模型服务商响应超时", "稍后重试，或检查网络和模型状态。"),
    "connection": ("无法连接模型服务商", "检查网络和已保存的 API 地址。"),
    "invalid_response": ("服务商未返回兼容的模型响应", "确认所选协议、API 地址和模型匹配，且模型可返回文本。"),
    "upstream_error": ("模型服务商请求失败", "检查服务商状态、模型名称和账户额度。"),
    "capability_disabled": ("当前配置已关闭此能力", "启用对应兼容选项并保存后再测试。"),
    "tool_not_observed": ("本次未观察到工具调用", "模型可能选择了普通回答；可重试，此结果不能证明模型不支持工具。"),
    "incomplete_response": ("模型响应未正常完成", "检查令牌限制和服务商状态后重试。"),
}


def _timeout(provider):
    return httpx.Timeout(180, connect=5) if provider == "ollama" else 25


def _local_error(exc):
    # Runtime also invokes diagnostics, so importing it at module load would cycle.
    from .model_runtime import LocalModelError
    if isinstance(exc, httpx.TimeoutException):
        return LocalModelError("本地模型响应超时，请选择更小的模型或稍后重试", 504)
    if isinstance(exc, httpx.HTTPError):
        return LocalModelError("无法调用所选本地模型，请检查 Ollama 是否运行、模型是否支持聊天及可用内存", 502)
    if isinstance(exc, ProtocolError) and exc.error_code == "incomplete_response":
        return LocalModelError("本地模型响应中断，已生成的内容可能不完整，请重试或切换模型", 502)
    return LocalModelError("本地模型返回了无效内容，请重试或切换模型", 502)


def complete(selected, messages, *, tools=None, reasoning=None, request_options=None, protocol=None) -> dict | None:
    if selected is None:
        return None
    options = normalize_request_options(request_options)
    if tools and not options["supports_tools"]:
        return None
    provider, key, base, model = selected
    try:
        request = build_request(selected, messages, tools=tools, reasoning=reasoning, request_options=options, protocol=protocol)
        body = request.body
        with httpx.Client(timeout=_timeout(provider), trust_env=False) as client:
            for attempt in range(2):
                with usage_attempt(provider, body.get("model", model), request.protocol) as usage:
                    response = client.post(request.url, headers=request.headers, json=body)
                    try:
                        payload = response.json()
                    except ValueError:
                        payload = None
                    usage.observe(payload)
                    if (provider == "ollama" and body.get("think") and attempt == 0
                            and response.status_code == 400):
                        body["think"] = False
                        continue
                    response.raise_for_status()
                    message = parse_completion(payload, provider, request.protocol)
                    usage.completed = True
                    return message
    except ReasoningConfigurationError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        if provider == "ollama":
            raise _local_error(exc) from exc
        return None


async def stream(selected, messages, *, reasoning=None, request_options=None, protocol=None):
    if selected is None:
        return
    provider, key, base, model = selected
    options = normalize_request_options(request_options)
    streaming = options["supports_streaming"]
    emitted = False
    try:
        request = build_request(selected, messages, stream=streaming, reasoning=reasoning, request_options=options, protocol=protocol)
        body = request.body
        async with httpx.AsyncClient(timeout=_timeout(provider), trust_env=False) as client:
            if not streaming:
                for attempt in range(2):
                    with usage_attempt(provider, body.get("model", model), request.protocol) as usage:
                        response = await client.post(request.url, headers=request.headers, json=body)
                        try:
                            payload = response.json()
                        except ValueError:
                            payload = None
                        usage.observe(payload)
                        if (provider == "ollama" and body.get("think") and attempt == 0
                                and response.status_code == 400):
                            body["think"] = False
                            continue
                        response.raise_for_status()
                        message = parse_completion(payload, provider, request.protocol)
                        usage.completed = True
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        emitted = True
                        yield "content", content
                    break
                return
            for attempt in range(2):
                parser = stream_parser(provider, request.protocol)
                try:
                    with usage_attempt(provider, body.get("model", model), request.protocol) as usage:
                        try:
                            async with client.stream("POST", request.url, headers=request.headers, json=body) as response:
                                response.raise_for_status()
                                async for line in response.aiter_lines():
                                    for item in parser.feed(line):
                                        emitted = True
                                        yield item
                                    if parser.done:
                                        usage.completed = True
                                        return
                                parser.finish()
                                usage.completed = True
                                return
                        except httpx.HTTPError:
                            # Chat text can be complete before the optional
                            # usage trailer arrives. A trailer disconnect must
                            # not turn that validated answer into an error.
                            # finish() still rejects every pre-finish failure.
                            if request.protocol != "chat_completions":
                                raise
                            parser.finish()
                            usage.completed = True
                            return
                        finally:
                            usage.usage = parser.usage
                except httpx.HTTPStatusError as exc:
                    if not (provider == "ollama" and body.get("think") and attempt == 0
                            and not emitted and exc.response.status_code == 400):
                        raise
                    body["think"] = False
    except ReasoningConfigurationError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        if provider == "ollama":
            raise _local_error(exc) from exc
        if emitted:
            raise ModelStreamError(_INTERRUPTED) from exc


_PROBE_TOOLS = [{"type": "function", "function": {
    "name": "mens_connection_probe", "description": "A connection test with no side effects; call with an empty object.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}]


def _status_error(response):
    if 200 <= response.status_code < 300:
        return
    try:
        payload = response.json()
    except (ValueError, httpx.ResponseNotRead):
        payload = {}
    raise ProtocolError(upstream_error_code(payload, response.status_code))


def _verify_probe_tool(message):
    calls = message.get("tool_calls")
    if not calls:
        raise ProtocolError("tool_not_observed")
    if len(calls) != 1:
        raise ProtocolError()
    function = calls[0]["function"]
    if function.get("name") != "mens_connection_probe":
        raise ProtocolError()
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise ProtocolError()
    try:
        parsed = json.loads(arguments)
    except ValueError as exc:
        raise ProtocolError() from exc
    if not isinstance(parsed, dict) or parsed:
        raise ProtocolError()


def probe_provider(provider, current, capability="chat") -> dict:
    if capability not in ("chat", "streaming", "tools"):
        raise ValueError("Unknown model capability")
    started = time.perf_counter()
    result = {"ok": False, "error_code": "", "provider": provider, "model": current.get("model", ""),
              "protocol": resolve_protocol(provider, current.get("protocol")), "capability": capability,
              "capabilities": {"chat": "not_tested", "streaming": "not_tested", "tools": "not_tested"}}
    try:
        if not current.get("api_key"):
            raise ProtocolError("missing_key")
        if not current.get("model"):
            raise ProtocolError("missing_model")
        options = normalize_request_options(current.get("request_options"))
        if ((capability == "streaming" and not options["supports_streaming"])
                or (capability == "tools" and not options["supports_tools"])):
            raise ProtocolError("capability_disabled")
        messages = [{"role": "user", "content": (
            "Call mens_connection_probe with an empty JSON object to verify the connection."
            if capability == "tools" else "Reply with OK to verify the connection.")}]
        selected = (provider, current["api_key"], current["base_url"], current["model"])
        request = build_request(selected, messages, protocol=result["protocol"], stream=capability == "streaming",
                                tools=_PROBE_TOOLS if capability == "tools" else None, request_options=options)
        kwargs = {"headers": request.headers, "json": request.body, "timeout": 20, "trust_env": False}
        if capability == "streaming":
            parser = stream_parser(provider, request.protocol)
            visible = False
            with httpx.stream("POST", request.url, **kwargs) as response:
                result["http_status"] = response.status_code
                if not 200 <= response.status_code < 300:
                    response.read()
                _status_error(response)
                for line in response.iter_lines():
                    for kind, text in parser.feed(line):
                        visible = visible or (kind == "content" and bool(text.strip()))
                    if parser.done:
                        break
                parser.finish()
            if not visible:
                raise ProtocolError()
        else:
            response = httpx.post(request.url, **kwargs)
            result["http_status"] = response.status_code
            _status_error(response)
            message = parse_completion(response.json(), provider, request.protocol)
            if capability == "tools":
                _verify_probe_tool(message)
            elif not isinstance(message.get("content"), str) or not message["content"].strip():
                raise ProtocolError()
        result["ok"] = True
        result["capabilities"][capability] = "verified"
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, httpx.TimeoutException):
            code = "timeout"
        elif isinstance(exc, httpx.HTTPError):
            code = "connection"
        elif isinstance(exc, ProtocolError):
            code = exc.error_code
        else:
            code = "invalid_response"
        result["error_code"] = code
        result["error"], result["hint"] = _ERRORS.get(code, _ERRORS["upstream_error"])
        result["capabilities"][capability] = "not_verified"
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result
