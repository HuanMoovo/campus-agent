"""Pure request/response contracts shared by production calls and diagnostics."""
import pytest

from app.model_protocol import build_body, normalize_request_options, parse_completion


MESSAGES = [{"role": "user", "content": "hello"}]


def test_legacy_options_supply_independent_defaults():
    options = normalize_request_options()
    assert options == {"token_parameter": "max_tokens", "send_temperature": True,
                       "supports_tools": True, "supports_streaming": True, "max_output_tokens": 900,
                       "reasoning_efforts": None}
    options["supports_tools"] = False
    assert normalize_request_options()["supports_tools"] is True


@pytest.mark.parametrize("value", [[], "auto", True, {"extra": True}, {"token_parameter": None},
    {"token_parameter": "max_output_tokens"}, {"send_temperature": None},
    {"supports_tools": 0}, {"supports_streaming": "false"}])
def test_invalid_options_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_request_options(value)


def test_compatible_body_obeys_options_without_vendor_fields():
    body = build_body("openai_compatible", "vendor/model", MESSAGES, stream=True,
                      request_options={"token_parameter": "max_completion_tokens", "send_temperature": False})
    assert body == {"model": "vendor/model", "messages": MESSAGES,
                    "max_completion_tokens": 900, "stream": True}


@pytest.mark.parametrize("stream,deep,expected", [(False, "deep", False), (True, "deep", True), (True, None, False)])
def test_qwen_thinking_is_only_enabled_for_deep_streams(stream, deep, expected):
    assert build_body("qwen", "qwen", MESSAGES, stream=stream, reasoning=deep)["enable_thinking"] is expected


def test_deepseek_reasoning_switches_model_and_omits_temperature():
    body = build_body("deepseek", "deepseek-chat", MESSAGES, reasoning="deep")
    assert body["model"] == "deepseek-reasoner"
    assert "temperature" not in body


@pytest.mark.parametrize("model", ["deepseek-v4-pro", "deepseek-flash", "custom-deployment"])
def test_deepseek_preserves_explicit_modern_or_custom_models(model):
    assert build_body("deepseek", model, MESSAGES, reasoning="deep")["model"] == model


def test_ollama_body_keeps_native_protocol():
    assert build_body("ollama", "qwen:latest", MESSAGES, reasoning="deep", stream=True) == {
        "model": "qwen:latest", "messages": MESSAGES, "stream": True, "think": True,
        "options": {"temperature": 0.2, "num_predict": 900}}


def test_tools_use_auto_and_can_be_disabled():
    tools = [{"type": "function", "function": {"name": "probe"}}]
    body = build_body("qwen", "qwen", MESSAGES, tools=tools)
    assert body["tools"] == tools and body["tool_choice"] == "auto"
    assert "tools" not in build_body("qwen", "qwen", MESSAGES, tools=tools,
                                     request_options={"supports_tools": False})


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [None]},
    {"choices": [{"message": {}}]}, {"choices": [{"message": {"content": 5}}]},
    {"choices": [{"message": {"content": "ok", "tool_calls": "bad"}}]},
    {"choices": [{"message": {"content": ""}}]}, {"error": {"message": "private"}}])
def test_malformed_or_empty_completion_is_rejected(payload):
    with pytest.raises(ValueError):
        parse_completion(payload, "qwen")


@pytest.mark.parametrize("reason", ["length", "content_filter", "unknown"])
def test_truncated_completion_is_not_reported_as_success(reason):
    with pytest.raises(ValueError):
        parse_completion({"choices": [{"message": {"content": "partial"}, "finish_reason": reason}]}, "qwen")


def test_valid_chat_and_tool_only_completions_are_preserved():
    message = {"role": "assistant", "content": "answer"}
    assert parse_completion({"choices": [{"message": message, "finish_reason": "stop"}]}, "qwen") == message
    tool_message = {"content": None, "tool_calls": [{"type": "function", "function": {"name": "probe", "arguments": "{}"}}]}
    assert parse_completion({"choices": [{"message": tool_message}]}, "qwen") == tool_message
    assert parse_completion({"message": message}, "ollama") == message
