"""Pure reasoning capabilities shared by configuration, chat validation and wire.

Only documented OpenAI model IDs on the official endpoint are inferred. Other
Chat/Responses services require an explicit compatibility declaration.
"""
from urllib.parse import urlsplit


REASONING_LEVELS = ("low", "medium", "high", "xhigh", "max")


class ReasoningConfigurationError(ValueError):
    """A safe user-facing error; never constructed from upstream diagnostics."""

    def __init__(self):
        super().__init__("当前模型和接口不支持所选推理强度，请使用默认或配置支持的档位。")

# Sources (checked 2026-10-31):
# https://developers.openai.com/api/docs/guides/deployment-checklist
# https://developers.openai.com/api/docs/models/gpt-5.1
# https://developers.openai.com/api/docs/models/gpt-5.2
# https://developers.openai.com/api/docs/models/gpt-5.4
# https://developers.openai.com/api/docs/models/gpt-5.5
# Codex-only efforts, including ultra, are not part of this public API contract.
_OPENAI_EFFORTS = {
    "gpt-6-astra": REASONING_LEVELS,
    "gpt-6.1-sol": REASONING_LEVELS,
    "gpt-6-sol": REASONING_LEVELS,
    "gpt-6-luna": REASONING_LEVELS,
    "gpt-5.5": REASONING_LEVELS[:4],
    "gpt-5.5-2026-04-23": REASONING_LEVELS[:4],
    "gpt-5.4": REASONING_LEVELS[:4],
    "gpt-5.4-2026-03-05": REASONING_LEVELS[:4],
    "gpt-5.2": REASONING_LEVELS[:4],
    "gpt-5.2-2025-12-11": REASONING_LEVELS[:4],
    "gpt-5.1": REASONING_LEVELS[:3],
    "gpt-5.1-2025-11-13": REASONING_LEVELS[:3],
}


def normalize_reasoning_efforts(value):
    """None infers capabilities; a list explicitly declares the supported subset."""
    if value is None:
        return None
    if (type(value) is not list or any(type(level) is not str or level not in REASONING_LEVELS for level in value)
            or len(set(value)) != len(value)):
        raise ValueError("reasoning_efforts must be null or a unique list of supported reasoning levels")
    return list(value)


def _official_openai_endpoint(base_url):
    try:
        parsed = urlsplit(base_url)
        return (parsed.scheme == "https" and parsed.hostname == "api.openai.com"
                and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                and parsed.path.rstrip("/") == "/v1" and not parsed.query and not parsed.fragment)
    except (TypeError, ValueError):
        return False


def reasoning_capability(provider, model, protocol, base_url, request_options=None):
    """Describe controllable effort without treating thinking toggles as tiers."""
    override = normalize_reasoning_efforts((request_options or {}).get("reasoning_efforts"))
    if override == []:
        return {"mode": "unsupported", "levels": [], "source": "configured"}
    if protocol not in ("chat_completions", "responses"):
        return {"mode": "toggle" if protocol == "ollama" else "unsupported", "levels": []}
    if override is not None:
        return {"mode": "effort", "levels": [level for level in REASONING_LEVELS if level in override],
                "source": "configured"}
    if _official_openai_endpoint(base_url) and model in _OPENAI_EFFORTS:
        return {"mode": "effort", "levels": list(_OPENAI_EFFORTS[model]), "source": "model"}
    if provider == "qwen" and protocol == "chat_completions":
        return {"mode": "toggle", "levels": []}
    return {"mode": "unknown", "levels": []}


def validate_reasoning_effort(reasoning, provider, model, protocol, base_url, request_options=None):
    """Legacy fast/deep retain their existing adapter behavior."""
    if reasoning in (None, "auto", "fast", "deep"):
        return
    capability = reasoning_capability(provider, model, protocol, base_url, request_options)
    if reasoning not in REASONING_LEVELS or reasoning not in capability["levels"]:
        raise ReasoningConfigurationError()
